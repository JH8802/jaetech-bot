"""화면 스모크 테스트: 모든 메뉴가 예외 없이 열리고 핵심 흐름이 동작하는지 (가짜 데이터)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from pricing import db  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PAGES = ["견적 계산", "제품 관리", "원료 단가", "부자재", "환율", "판매처", "가격 추이",
         "엑셀 일괄 등록", "견적 이력", "설정"]


@pytest.fixture()
def app_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui.db")
    db.init_db()
    for d, r in [("2026-01-02", 1300), ("2026-03-01", 1350), ("2026-06-01", 1420)]:
        db.add_fx_rate("USD", r, d)
    db.add_fx_rate("VND", 5.5, "2026-01-02")
    a = db.upsert_ingredient("수입A(가상)", "미국", "가상", .025, .03, .005, 300, 200)
    db.add_price(a, None, "2026-01-02", currency="USD", foreign_price=7.0)
    db.add_price(a, None, "2026-05-01", currency="USD", foreign_price=7.5)
    h = db.upsert_ingredient("국내B(가상)")
    db.add_price(h, 9000, "2026-01-02")
    db.add_price(h, 9900, "2026-07-01")
    m1 = db.upsert_material("롤필름", "roll", None, .03)
    db.add_material_price(m1, None, "2026-01-02", currency="VND", foreign_price=500)
    m2 = db.upsert_material("카톤", "box", 1000, .03)
    pid = db.save_product("제품(가상)", 30, 20, 0, 100, "",
                          [{"ingredient_id": a, "ratio": .5}, {"ingredient_id": h, "ratio": .5}],
                          [{"material_id": m1, "qty": 1, "divisor": 1, "per_bag": True},
                           {"material_id": m2, "qty": 1, "divisor": 10}], three_pl_cost=200)
    db.upsert_channel({"name": "가상마트", "kind": "offline", "logistics_rate": .03, "logistics_fixed": 100})
    db.upsert_channel({"name": "가상몰", "kind": "online", "fee_rate": .12, "promo_rate": .02, "event_rate": .01,
                       "parcel_cost": 3000, "margin_rate": .05})
    return pid


def open_page(page, who="홍길동"):
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.sidebar.text_input[0].set_value(who).run()
    at.sidebar.radio[0].set_value(page).run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_every_page_opens_without_exception(app_db, page):
    at = open_page(page)
    assert not at.exception, [str(e.value)[:200] for e in at.exception]


def test_sidebar_menu_order_and_new_menus(app_db):
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert list(at.sidebar.radio[0].options) == PAGES


def test_quote_with_channel_and_save(app_db):
    at = open_page("견적 계산")
    base = at.metric[0].value
    online = [o for o in at.selectbox[1].options if "가상몰" in o][0]
    at.selectbox[1].set_value(online).run()
    assert at.metric[0].value != base and not at.exception
    [b for b in at.button if "이력에 저장" in b.label][0].click().run()
    assert any("저장됨" in s.value for s in at.success)
    q, r, meta = db.search_quotes()[0]
    assert q.channel_name == "가상몰" and q.as_of_date and r.parcel == 3000 and meta["created_by"] == "홍길동"


def test_trends_page_draws_charts_and_downloads(app_db):
    at = open_page("가격 추이")
    kinds = {getattr(e, "type", "") for e in at.main}
    assert "vega_lite_chart" in kinds and "download_button" in kinds


def test_fx_page_saves_rate_for_selected_currency_and_adds_other_currency(app_db):
    at = open_page("환율")
    sb = [s for s in at.selectbox if s.label == "통화"][0]
    assert "USD" in sb.options[0]                                  # 미국이 맨 위 (미국 → 베트남 → 튀르키예)
    sb.set_value(sb.options[0])
    [n for n in at.number_input if n.label.startswith("환율")][0].set_value(1450.0)
    at.run()
    [b for b in at.button if "환율 저장" in b.label][0].click().run()
    assert db.list_fx_rates("USD")[0]["rate"] == 1450.0 and not at.exception
    for ti in at.text_input:
        if ti.label.startswith("통화 코드"):
            ti.set_value("eur")
        elif ti.label == "통화 이름":
            ti.set_value("유로")
    at.run()
    [b for b in at.button if b.label == "통화 추가"][0].click().run()
    assert "EUR" in {c["code"] for c in db.list_currencies()}


def test_ingredient_foreign_price_form(app_db):
    at = open_page("원료 단가")
    at.selectbox[0].set_value("수입A(가상)").run()
    cur = [s for s in at.selectbox if s.label == "통화"][0]
    cur.set_value([o for o in cur.options if "USD" in o][0]).run()
    [n for n in at.number_input if n.label.startswith("외화 단가")][0].set_value(8.0)
    at.run()
    [b for b in at.button if "단가 추가" in b.label][0].click().run()
    assert not at.exception
    ing = next(i for i in db.list_ingredients() if i["name"] == "수입A(가상)")
    assert ing["foreign_price"] == 8.0 and ing["currency"] == "USD"
    assert ing["price_per_kg"] == pytest.approx(8.0 * ing["fx"])


def test_bulk_page_with_fx_sheet(app_db, monkeypatch):
    import io
    import streamlit as st
    from openpyxl import Workbook
    from pricing import importer
    wb = Workbook()
    wi = wb.active; wi.title = "원료"; wi.append(importer.ING_HEADERS)
    wi.append(["신규수입원료", None, None, None, None, None, None, "2026-02-01", None, None, None, "USD", 5.0, None])
    wb.create_sheet("부자재").append(importer.MAT_HEADERS)
    wf = wb.create_sheet("환율"); wf.append(importer.FX_HEADERS); wf.append(["USD", "2026-02-01", 1310])
    buf = io.BytesIO(); wb.save(buf)

    class Fake:
        name = "x.xlsx"
        def getvalue(self): return buf.getvalue()
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: Fake())
    at = open_page("엑셀 일괄 등록")
    assert not at.exception and [m.label for m in at.metric] == ["신규", "수정", "변경없음", "오류"]
    [b for b in at.button if "등록 실행" in b.label][0].click().run()
    assert any("등록 완료" in s.value for s in at.success)
    assert any(i["name"] == "신규수입원료" for i in db.list_ingredients())
    assert any(r["rate_date"] == "2026-02-01" and r["rate"] == 1310 for r in db.list_fx_rates("USD"))


def _charts(at):
    return [e for e in at.main if getattr(e, "type", "") == "vega_lite_chart"]


def test_trends_bar_views_and_fx_decomposition(app_db):
    ing = {i["name"]: i["id"] for i in db.list_ingredients()}
    at = open_page("가격 추이")
    at.selectbox(key="tr_item1").set_value(ing["수입A(가상)"]).run()          # 달러 수입 원료
    assert not at.exception
    assert any("변동 원인 분해" in m.value for m in at.markdown)               # 현지가 × 환율 분해
    assert any("환율 변동 효과" in c.value for c in at.caption)
    n_line = len(_charts(at))
    assert n_line >= 2                                                       # 일별 선 + 지수 선
    for label in ("막대 그래프 (주별 평균)", "막대 그래프 (월별 평균)"):
        at.radio(key="tr_view1").set_value(label).run()
        assert not at.exception and len(_charts(at)) >= 2


def test_trends_ranking_yearly_and_product_tabs_render(app_db):
    at = open_page("가격 추이")
    assert not at.exception
    # 탭 4개 모두 렌더링됨: 변동률 순위(상승/하락 지표), 연도별 표, 제품 원가 추이 지표
    labels = [m.label for m in at.metric]
    assert "상승 품목" in labels and "시작 납품가" in labels
    assert len(at.tabs) == 4
