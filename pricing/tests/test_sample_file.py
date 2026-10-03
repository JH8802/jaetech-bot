"""모의 테스트용 예제 엑셀(랜덤 가짜 데이터)이 실제로 일괄 등록되는지 검증."""
import io
from collections import Counter

import pytest
from pricing import db, importer, make_sample, trends


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()


def sample_bytes():
    buf = io.BytesIO()
    make_sample.build().save(buf)
    return buf.getvalue()


def test_sample_parses_without_errors_and_has_expected_volume():
    p = importer.parse_file(sample_bytes(), "sample.xlsx")
    assert not p.errors, p.errors[:5]
    names = {r["name"] for r in p.ingredients}
    assert len(names) == 12 and len({r["name"] for r in p.materials}) == 10
    assert {r["currency"] for r in p.fx_rates} == {"USD", "VND", "TRY"}
    assert len(p.fx_rates) == 3 * 367                                   # 2025-10-01 ~ 2026-10-02 일별
    currencies = {r["currency"] for r in p.ingredients}
    assert {"USD", "VND", "TRY", None} <= currencies                    # 원화·미국·베트남·튀르키예 모두 포함
    assert any(r["fx_fixed"] for r in p.ingredients)                    # 고정(계약)환율 예시 줄
    assert {m["category"] for m in p.materials if m["category"]} == {"roll", "pack", "split", "incase", "box", "etc"}


def test_sample_imports_cleanly_and_reimport_is_noop(tmpdb):
    p = importer.parse_file(sample_bytes(), "sample.xlsx")
    res = db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-10-03")
    assert Counter(r["status"] for r in res)["오류"] == 0, [r for r in res if r["status"] == "오류"][:3]
    assert Counter(r["status"] for r in res)["신규"] > 1000
    again = db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-10-04")
    assert {r["status"] for r in again} == {"변경없음"}


def test_sample_data_supports_trend_analysis_and_fx_decomposition(tmpdb):
    p = importer.parse_file(sample_bytes(), "sample.xlsx")
    db.bulk_apply(p.ingredients, p.materials, p.fx_rates, today="2026-10-03")
    pb = db.load_pricebook()
    ids = {i["name"]: i["id"] for i in db.list_ingredients()}
    s = trends.daily_series(pb, "ingredient", ids["아몬드(미국산)"], "2026-01-03", "2026-06-05")
    assert len(s) == 154 and trends.decompose(s) is not None             # 일별 154일, 환율 분해 가능
    rank = trends.ranking_table(pb, "ingredient", ids and {v: k for k, v in ids.items()}, "2025-10-01", "2026-10-02")
    assert len(rank) == 12
    yr = trends.yearly_table(pb, "ingredient", {v: k for k, v in ids.items()}, [2025, 2026], today="2026-10-03")
    assert yr
    prod = db.save_product("예제 제품", 30, 20, 0, 300, "",
                           [{"ingredient_id": ids["아몬드(미국산)"], "ratio": .5}, {"ingredient_id": ids["건무화과(튀르키예산)"], "ratio": .5}],
                           [])
    q, r = db.calculate_quote(prod)
    assert r.price > 0 and not any("등록되어 있지 않아" in w for w in r.warnings)


def test_committed_sample_file_is_importable():
    from pathlib import Path
    f = Path(make_sample.OUT)
    if not f.exists():
        pytest.skip("예제 파일이 없습니다 (python -m pricing.make_sample 로 생성)")
    p = importer.parse_file(f.read_bytes(), f.name)
    assert not p.errors and p.ingredients and p.materials and p.fx_rates
