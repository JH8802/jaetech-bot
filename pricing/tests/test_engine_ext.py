"""확장 항목(로스팅·3PL·봉수연동·판매처 비용·환율 민감도) 테스트 - 가짜 숫자."""
import pytest
from pricing.engine import (QuoteInput, IngredientLine as I, MaterialLine as M, calculate,
                            fx_exposure, fx_sensitivity)


def base(**kw):
    d = dict(product_name="t", bag_count=10, unit_weight_g=20,
             ingredients=[I("A", .6, 10000, .05, roasting_per_kg=300, sorting_per_kg=200),
                          I("B", .4, 20000, .02)],
             materials=[M("롤", "roll", 25, 1, 1, .03, per_bag=True),
                        M("인케이스", "incase", 600, 1, 1, .03),
                        M("카톤", "box", 1000, 1, 10, .03),
                        M("소분", "split", 50, 1, 1, 0, per_bag=True),
                        M("스티커", "etc", 5, 1, 1, 0)],
             shipping_cost=100, rounding="none")
    d.update(kw)
    return QuoteInput(**d)


def test_roasting_and_per_ingredient_sorting():
    r = calculate(base())
    kg_a = 20 * .6 * 10 / 1000          # 0.12kg
    assert r.roasting_cost == pytest.approx(300 * kg_a)
    assert r.sorting_cost == pytest.approx(200 * kg_a)
    assert r.materials_cost == pytest.approx(10000 * kg_a + 20000 * 0.08)


def test_sorting_product_level_plus_ingredient_level():
    r = calculate(base(sorting_cost_per_kg=100))
    assert r.sorting_cost == pytest.approx(100 * 0.2 + 200 * 0.12)       # 총 0.2kg


def test_per_bag_quantity_scales_with_bags():
    r10 = calculate(base(bag_count=10))
    r60 = calculate(base(bag_count=60))
    roll10 = next(x for x in r10.material_rows if x["name"] == "롤")
    roll60 = next(x for x in r60.material_rows if x["name"] == "롤")
    assert roll10["qty"] == 10 and roll60["qty"] == 60
    assert roll60["base"] == pytest.approx(6 * roll10["base"])
    inc10 = next(x for x in r10.material_rows if x["name"] == "인케이스")
    inc60 = next(x for x in r60.material_rows if x["name"] == "인케이스")
    assert inc10["base"] == inc60["base"]                 # 고정 수량은 봉수와 무관


def test_material_categories_split_out_and_loss_total():
    r = calculate(base())
    assert r.roll_cost == pytest.approx(25 * 10 * 1.03)
    assert r.incase_cost == pytest.approx(600 * 1.03)
    assert r.box_cost == pytest.approx(100 * 1.03)
    assert r.split_cost == pytest.approx(500)
    assert r.etc_cost == pytest.approx(5)
    assert r.material_loss_cost == pytest.approx(250 * .03 + 18 + 3)


def test_three_pl_in_direct_cost():
    a, b = calculate(base()), calculate(base(three_pl_cost=250))
    assert b.direct_cost - a.direct_cost == pytest.approx(250)
    assert b.three_pl_cost == 250


def test_offline_channel_rate_plus_fixed_logistics():
    q = base(channel_name="가상마트", channel_kind="offline", sga_rate=.05, margin_rate=.05,
             logistics_rate=.03, logistics_fixed=120)
    r = calculate(q)
    assert r.logistics == pytest.approx(r.price * .03 + 120)
    assert r.total_cost == pytest.approx(r.price)         # 역산 → 원가합계 == 납품가
    assert r.profit == pytest.approx(0, abs=1e-6)


def test_online_channel_all_costs_gross_up():
    q = base(channel_name="가상몰", channel_kind="online", sga_rate=.03, margin_rate=.05,
             fee_rate=.12, promo_rate=.02, event_rate=.01, event_fixed=30, parcel_cost=3000,
             three_pl_cost=500)
    r = calculate(q)
    assert r.fee == pytest.approx(r.price * .12) and r.promo == pytest.approx(r.price * .02)
    assert r.event == pytest.approx(r.price * .01 + 30) and r.parcel == 3000
    assert r.channel_cost == pytest.approx(r.logistics + r.fee + r.promo + r.event + r.parcel)
    assert r.total_cost == pytest.approx(r.price)
    assert r.effective_margin == pytest.approx(r.margin)   # 반올림 없음 → 추가 차익 0
    # 수수료가 있으면 같은 원가에서 납품가가 더 높아야 한다
    assert r.price > calculate(base(sga_rate=.03, margin_rate=.05, three_pl_cost=500)).price


def test_online_vat_basis():
    q = base(fee_rate=.10, online_vat=True)
    r = calculate(q)
    assert r.fee == pytest.approx(r.price * .10 * 1.1)


def test_rates_over_100_percent_rejected():
    with pytest.raises(ValueError):
        calculate(base(sga_rate=.5, fee_rate=.3, promo_rate=.2))


def test_no_channel_matches_old_behavior():
    """판매처를 안 쓰면 (물류비율만) 예전 계산과 같아야 한다."""
    q = base(sga_rate=.05, logistics_rate=.0275)
    r = calculate(q)
    assert r.channel_cost == pytest.approx(r.logistics)
    assert r.total_cost == pytest.approx(r.price)


def fx_q():
    return base(ingredients=[
        I("수입A", .5, 14000, .05, currency="USD", foreign_price=10.0, fx_rate=1400.0),
        I("국내B", .5, 8000, .0)],
        materials=[M("수입필름", "roll", 30, 1, 1, .03, per_bag=True, currency="VND", foreign_price=500.0, fx_rate=0.06),
                   M("국내박스", "box", 500, 1, 1, 0)],
        sga_rate=.05)


def test_fx_exposure_by_currency():
    q = fx_q()
    r = calculate(q)
    exp = fx_exposure(q)
    assert set(exp) == {"USD", "VND"}
    a = r.ingredient_rows[0]
    assert exp["USD"] == pytest.approx(a["cost"] + a["loss"])
    assert exp["VND"] == pytest.approx(r.material_rows[0]["total"])


def test_fx_sensitivity_matches_manual_recalc():
    q = fx_q()
    rows = fx_sensitivity(q, shocks=(0.10,))
    usd = next(r for r in rows if r["currency"] == "USD")
    # 직접 계산: 수입A 단가를 10% 올리면?
    q2 = fx_q()
    q2.ingredients[0].price_per_kg *= 1.10
    assert usd["delta_direct"] == pytest.approx(calculate(q2).direct_cost - calculate(q).direct_cost)
    assert usd["delta_price"] > 0 and 0 < usd["share"] < 1
    # 환율 하락 시 원가 감소
    down = next(r for r in fx_sensitivity(q, shocks=(-0.10,)) if r["currency"] == "USD")
    assert down["delta_direct"] < 0


def test_fx_sensitivity_ignores_krw_only_quote():
    assert fx_sensitivity(base()) == []


def test_fx_sensitivity_works_in_fixed_price_mode():
    q = fx_q(); q.fixed_price = 1000.0
    rows = fx_sensitivity(q, shocks=(0.05,))
    assert rows and q.fixed_price == 1000.0                # 원본은 건드리지 않음


def test_zero_margin_has_no_negative_zero_warning():
    """마진 0%일 때 부동소수점 오차로 '실질 마진이 마이너스(-0.0%)' 경고가 뜨던 버그."""
    for kw in (dict(), dict(sga_rate=.05), dict(sga_rate=.03, fee_rate=.12, promo_rate=.02, parcel_cost=3000)):
        r = calculate(base(rounding="none", **kw))
        assert r.effective_margin == 0.0 and r.profit == 0.0
        assert not any("마이너스" in w for w in r.warnings), kw
