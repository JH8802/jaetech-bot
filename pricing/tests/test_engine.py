"""가짜 숫자로 계산 규칙 자체를 검증 (실제 원가 아님 - git에 올려도 안전)."""
import pytest
from pricing.engine import (QuoteInput, IngredientLine as I, MaterialLine as M,
                            calculate, apply_rounding)


def base(**kw):
    d = dict(
        product_name="테스트", bag_count=10, unit_weight_g=20,
        ingredients=[I("A", 0.6, 10000, 0.05), I("B", 0.4, 20000, 0.02)],
        materials=[M("포장", "pack", 10, 10, 1, 0.03), M("소분", "split", 50, 10),
                   M("박스", "box", 1000, 1, 10, 0.03)],
        shipping_cost=100)
    d.update(kw)
    return QuoteInput(**d)


def test_direct_cost_breakdown():
    r = calculate(base())
    # 원물가: A 10000*12g*10/1000=1200, B 20000*8g*10/1000=1600
    assert r.materials_cost == pytest.approx(2800)
    assert r.loss_cost == pytest.approx(1200 * .05 + 1600 * .02)
    assert r.pack_cost == pytest.approx(10 * 10 * 1.03)
    assert r.split_cost == pytest.approx(500)           # 소분비는 loss 없음
    assert r.box_cost == pytest.approx(1000 / 10 * 1.03)
    assert r.direct_cost == pytest.approx(
        2800 + r.loss_cost + r.pack_cost + 500 + r.box_cost + 100)


def test_gross_up_is_self_consistent():
    """납품가 기준 % 를 역산하면 원가합계 == 납품가 (반올림 안 할 때)."""
    q = base(sga_rate=.05, margin_rate=.05, logistics_rate=.0275, rounding="none")
    r = calculate(q)
    assert r.total_cost + r.margin * 0 == pytest.approx(r.price)   # 마진은 센터도착가에 포함됨
    assert r.profit == pytest.approx(0, abs=1e-6)
    assert r.sga == pytest.approx(r.price * .05)


def test_vat_logistics():
    q = base(logistics_rate=.03, logistics_vat=True, rounding="none")
    r = calculate(q)
    assert r.logistics == pytest.approx(r.price * 1.1 * .03)
    assert r.profit == pytest.approx(0, abs=1e-6)


def test_optional_items_off():
    r = calculate(base())
    assert r.sga == r.margin == r.logistics == 0
    assert r.price == apply_rounding(r.direct_cost, "round")


def test_rounding_modes():
    assert apply_rounding(12519.04, "ceil10") == 12520
    assert apply_rounding(12520.0, "ceil10") == 12520
    assert apply_rounding(8821.41, "round") == 8821
    assert apply_rounding(8821.5, "round") == 8822
    assert apply_rounding(1.2345, "none") == 1.2345


def test_ceil_gives_positive_profit():
    r = calculate(base(sga_rate=.05, rounding="ceil10"))
    assert 0 <= r.profit < 10


def test_fixed_price_loss_warning():
    r = calculate(base(sga_rate=.05, fixed_price=1000))
    assert r.price == 1000
    assert r.profit < 0
    assert any("적자" in w for w in r.warnings)


def test_ratio_warning():
    r = calculate(base(ingredients=[I("A", 0.5, 10000)]))
    assert any("구성비" in w for w in r.warnings)


def test_invalid_rates():
    with pytest.raises(ValueError):
        calculate(base(sga_rate=.6, margin_rate=.4))
    with pytest.raises(ValueError):
        calculate(base(materials=[M("박스", "box", 100, 1, 0)]))
