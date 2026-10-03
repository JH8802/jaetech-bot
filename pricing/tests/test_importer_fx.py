"""엑셀 일괄 등록: 환율 시트·외화 단가·로스팅/선별비·새 분류 (가짜 데이터)."""
import io
import pytest
from openpyxl import Workbook
from pricing import db, importer


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()


def xlsx(ing=(), mat=(), fx=()):
    wb = Workbook()
    wi = wb.active; wi.title = "원료"; wi.append(importer.ING_HEADERS)
    for r in ing: wi.append(list(r))
    wm = wb.create_sheet("부자재"); wm.append(importer.MAT_HEADERS)
    for r in mat: wm.append(list(r))
    wf = wb.create_sheet("환율"); wf.append(importer.FX_HEADERS)
    for r in fx: wf.append(list(r))
    b = io.BytesIO(); wb.save(b); return b.getvalue()


# 원료 행: 이름, 원산지, 공급처, 수분, 소분, 선별loss, 단가, 적용일, 메모, 로스팅비, 선별비, 통화, 외화단가, 고정환율
ING = [
    ("수입아몬드", "미국", "가상상사", 2.5, 3, 0.54, None, "2026-02-01", None, 300, 200, "미국", 7.5, None),
    ("수입캐슈", "베트남", None, 2.5, 3, 0.8, None, "2026-02-01", None, None, None, "VND", 250000, None),
    ("계약호두", "튀르키예", None, 0, 3, .5, None, "2026-02-01", None, None, None, "터키", 6.0, 1450),
    ("국내땅콩", None, None, None, None, None, 5000, "2026-02-01", None, None, None, None, None, None),
]
MAT = [("롤필름", "롤포장지", None, 3, None, "2026-02-01", "USD", 0.05, None),
       ("인케이스A", "IC", 600, 3, None, "2026-02-01", None, None, None),
       ("스티커", "기타", 5, 0, None, None, None, None, None),
       ("카톤", "카톤박스", 1000, 3, None, "2026-02-01", None, None, None)]
FX = [("USD", "2026-01-01", 1300), ("USD", "2026-03-01", 1400), ("VND", "2026-01-01", 5.5), ("TRY", "2026-01-01", 40)]


def test_parse_new_columns_aliases():
    p = importer.parse_file(xlsx(ING, MAT, FX), "x.xlsx")
    assert not p.errors, p.errors
    a, c, w, k = p.ingredients
    assert (a["currency"], a["foreign_price"], a["roasting_cost_per_kg"], a["sorting_cost_per_kg"]) == ("USD", 7.5, 300, 200)
    assert c["currency"] == "VND" and w["currency"] == "TRY" and w["fx_fixed"] == 1450   # '터키' → TRY
    assert k["currency"] is None and k["price"] == 5000
    assert [m["category"] for m in p.materials] == ["roll", "incase", "etc", "box"]
    assert len(p.fx_rates) == 4 and p.fx_rates[0] == {"src": p.fx_rates[0]["src"], "currency": "USD",
                                                       "date": "2026-01-01", "rate": 1300, "memo": None}


def test_parse_validation_errors():
    bad = [("A", None, None, None, None, None, None, None, None, None, None, "USD", None, None),      # 통화 있는데 외화단가 없음
           ("B", None, None, None, None, None, None, None, None, None, None, None, 5.0, None),        # 외화단가 있는데 통화 없음
           ("C", None, None, None, None, None, -5, None, None, None, None, None, None, None),         # 음수
           ("D", None, None, None, None, None, None, None, None, -1, None, None, None, None)]         # 음수 로스팅비
    p = importer.parse_file(xlsx(bad, [("E", "이상한분류", 1, 0, None, None, None, None, None)],
                                 [("USD", None, 1300), (None, "2026-01-01", 1300), ("USD", "2026-01-01", 0)]), "x.xlsx")
    text = "\n".join(p.errors)
    assert "외화 단가가 없습니다" in text and "통화(USD/VND/TRY 등)가 없습니다" in text
    assert "음수" in text and "이상한분류" in text
    assert "기준일이 비어" in text and "통화가 비어" in text and "0보다 커야" in text
    assert len(p.errors) == 8


def test_apply_foreign_prices_follow_fx_and_report(tmpdb):
    p = importer.parse_file(xlsx(ING, MAT, FX), "x.xlsx")
    res = db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-09-01")
    assert all(r["status"] == "신규" for r in res), res
    assert [r["kind"] for r in res[:4]] == ["환율"] * 4          # 환율이 먼저 처리됨
    pb = db.load_pricebook()
    ids = {i["name"]: i["id"] for i in db.list_ingredients()}
    assert pb.ingredient(ids["수입아몬드"], "2026-02-15")["krw"] == pytest.approx(7.5 * 1300)
    assert pb.ingredient(ids["수입아몬드"], "2026-04-01")["krw"] == pytest.approx(7.5 * 1400)   # 환율 변동 반영
    assert pb.ingredient(ids["수입캐슈"], "2026-04-01")["krw"] == pytest.approx(250000 * 0.055)  # VND 100동당 5.5원
    assert pb.ingredient(ids["계약호두"], "2026-04-01")["krw"] == pytest.approx(6 * 1450)        # 고정환율
    ing = {i["name"]: i for i in db.list_ingredients()}
    assert ing["수입아몬드"]["roasting_cost_per_kg"] == 300 and ing["수입아몬드"]["sorting_cost_per_kg"] == 200
    mats = {m["name"]: m for m in db.list_materials("2026-04-01")}
    assert mats["롤필름"]["category"] == "roll" and mats["롤필름"]["unit_price"] == pytest.approx(0.05 * 1400)
    assert mats["인케이스A"]["category"] == "incase" and mats["스티커"]["category"] == "etc"


def test_foreign_price_without_any_fx_is_an_error_and_rolls_back(tmpdb):
    p = importer.parse_file(xlsx(ING[:1] + ING[3:], [], []), "x.xlsx")             # 환율 시트가 없음
    res = db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-09-01")
    assert any(r["status"] == "오류" and "환율 이력" in r["detail"] for r in res)
    assert db.list_ingredients() == []                                             # 전체 취소
    # 알 수 없는 통화 코드
    p2 = importer.parse_file(xlsx([], [], [("XYZ", "2026-01-01", 10)]), "x.xlsx")
    res2 = db.bulk_apply([], [], p2.fx_rates)
    assert res2[0]["status"] == "오류" and "등록되지 않은 통화" in res2[0]["detail"]


def test_other_currency_after_adding_it(tmpdb):
    db.add_currency("EUR", "유로", "유럽연합")
    p = importer.parse_file(xlsx([("유럽올리브", None, None, None, None, None, None, "2026-02-01", None, None, None, "EUR", 8, None)],
                                 [], [("EUR", "2026-01-01", 1500)]), "x.xlsx")
    res = db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-09-01")
    assert all(r["status"] == "신규" for r in res)
    assert db.list_ingredients("2026-03-01")[0]["price_per_kg"] == pytest.approx(12000)


def test_roundtrip_export_is_noop_with_foreign_and_fixed(tmpdb):
    p = importer.parse_file(xlsx(ING, MAT, FX), "x.xlsx")
    db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-09-01")
    blob = importer.build_workbook(db.list_ingredients(), db.list_materials(), db.list_fx_rates())
    again = importer.parse_file(blob, "export.xlsx")
    assert not again.errors, again.errors
    res = db.bulk_apply(again.ingredients, again.materials, again.fx_rates, today="2026-09-02")
    assert all(r["status"] == "변경없음" for r in res), [r for r in res if r["status"] != "변경없음"]


def test_changed_foreign_price_adds_history_and_change_detail(tmpdb):
    p = importer.parse_file(xlsx(ING[:1], [], FX), "x.xlsx")
    db.bulk_apply(p.ingredients, [], p.fx_rates, today="2026-09-01")
    new = [("수입아몬드", None, None, None, None, None, None, "2026-05-01", None, None, None, "USD", 8.2, None)]
    r = db.bulk_apply(importer.parse_file(xlsx(new), "x.xlsx").ingredients, [], today="2026-09-01")
    assert r[0]["status"] == "수정" and "7.50 USD→8.20 USD" in r[0]["detail"]
    ing = db.list_ingredients("2026-06-01")[0]
    assert ing["foreign_price"] == 8.2 and ing["price_per_kg"] == pytest.approx(8.2 * 1400)
    assert len(db.price_history(ing["id"])) == 2


def test_fx_update_and_nochange(tmpdb):
    p = importer.parse_file(xlsx([], [], FX), "x.xlsx")
    assert [r["status"] for r in db.bulk_apply([], [], p.fx_rates)] == ["신규"] * 4
    assert [r["status"] for r in db.bulk_apply([], [], p.fx_rates)] == ["변경없음"] * 4
    p2 = importer.parse_file(xlsx([], [], [("USD", "2026-01-01", 1310)]), "x.xlsx")
    r = db.bulk_apply([], [], p2.fx_rates)
    assert r[0]["status"] == "수정" and "1,300.0000→1,310.0000" in r[0]["detail"]


def test_old_style_single_sheet_still_parses():
    """예전 양식(9열)도 그대로 읽힌다."""
    wb = Workbook(); ws = wb.active; ws.title = "단가표"
    ws.append(importer.ING_HEADERS[:9]); ws.append(["아몬드", "미국", None, 2.5, 3, 0.5, 10500, "2026-09-01", None])
    b = io.BytesIO(); wb.save(b)
    p = importer.parse_file(b.getvalue(), "old.xlsx")
    assert not p.errors and p.ingredients[0]["price"] == 10500 and p.ingredients[0]["currency"] is None


def test_reimport_is_noop_even_when_file_has_redundant_unchanged_price_lines(tmpdb):
    """값이 안 바뀐 줄(0.05→0.05)이 있고 이후 날짜에 다른 단가가 있어도, 같은 파일 재업로드는 '변경없음'."""
    rows = [("A원료", None, None, None, None, None, 100, "2026-01-01", None, None, None, None, None, None),
            ("A원료", None, None, None, None, None, 100, "2026-02-01", None, None, None, None, None, None),   # 변동 없음
            ("A원료", None, None, None, None, None, 120, "2026-03-01", None, None, None, None, None, None)]
    p = importer.parse_file(xlsx(rows), "x.xlsx")
    first = db.bulk_apply(p.ingredients, [], [], today="2026-09-01")
    assert first[0]["status"] == "신규" and first[1]["status"] == "변경없음" and first[2]["status"] == "수정"
    assert {r["status"] for r in db.bulk_apply(p.ingredients, [], [], today="2026-09-02")} == {"변경없음"}
    ing = db.list_ingredients()[0]
    assert len(db.price_history(ing["id"])) == 2                       # 중복 줄은 이력으로 쌓이지 않음


def test_price_returning_to_old_value_later_is_recorded(tmpdb):
    rows = [("B원료", None, None, None, None, None, 100, "2026-01-01", None, None, None, None, None, None),
            ("B원료", None, None, None, None, None, 120, "2026-03-01", None, None, None, None, None, None),
            ("B원료", None, None, None, None, None, 100, "2026-05-01", None, None, None, None, None, None)]  # 다시 100으로
    p = importer.parse_file(xlsx(rows), "x.xlsx")
    assert [r["status"] for r in db.bulk_apply(p.ingredients, [], [])] == ["신규", "수정", "수정"]
    assert len(db.price_history(db.list_ingredients()[0]["id"])) == 3
