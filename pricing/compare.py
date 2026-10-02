"""견적 2건 비교 (A=기준, B=비교 대상). 화면과 엑셀에서 공통으로 사용."""
from __future__ import annotations

from .engine import CATEGORIES, QuoteInput, QuoteResult, calc_mode

Quote = tuple[QuoteInput, QuoteResult, dict]

SUMMARY_FIELDS = [
    ("원물가", "materials_cost"), ("선별비", "sorting_cost"), ("로스", "loss_cost"),
    ("포장지", "pack_cost"), ("소분비", "split_cost"), ("박스비", "box_cost"),
    ("운송비", "shipping_cost"), ("직접원가", "direct_cost"), ("판관비", "sga"),
    ("마진", "margin"), ("센터도착가", "center_cost"), ("물류비", "logistics"),
    ("원가합계", "total_cost"), ("납품가", "price"), ("실질 마진", "effective_margin"),
]


def _diff(a: float, b: float) -> tuple[float, float | None]:
    d = b - a
    return d, (d / a if a else None)


def compare_quotes(a: Quote, b: Quote) -> dict:
    qa, ra, ma = a
    qb, rb, mb = b

    summary = []
    for label, attr in SUMMARY_FIELDS:
        va, vb = getattr(ra, attr), getattr(rb, attr)
        d, p = _diff(va, vb)
        summary.append({"항목": label, "A": va, "B": vb, "차이": d, "차이%": p})
    d, p = _diff(ra.effective_margin_rate, rb.effective_margin_rate)
    summary.append({"항목": "실질 마진율", "A": ra.effective_margin_rate, "B": rb.effective_margin_rate,
                    "차이": d, "차이%": None})

    # ---- 원료 (이름 기준) ----
    ia = {x["name"]: x for x in ra.ingredient_rows}
    ib = {x["name"]: x for x in rb.ingredient_rows}
    ingredients = []
    for name in list(ia) + [n for n in ib if n not in ia]:
        x, y = ia.get(name), ib.get(name)
        ca = (x["cost"] + x["loss"]) if x else 0.0
        cb = (y["cost"] + y["loss"]) if y else 0.0
        status = "추가" if x is None else "삭제" if y is None else None
        if status is None:
            same = (abs(x["price_per_kg"] - y["price_per_kg"]) < 1e-9 and abs(x["ratio"] - y["ratio"]) < 1e-9
                    and abs(x["loss_rate"] - y["loss_rate"]) < 1e-9 and abs(ca - cb) < 1e-6)
            status = "동일" if same else "변경"
        ingredients.append({
            "원료": name, "상태": status,
            "구성비 A": x["ratio"] if x else None, "구성비 B": y["ratio"] if y else None,
            "단가 A": x["price_per_kg"] if x else None, "단가 B": y["price_per_kg"] if y else None,
            "단가기준일 A": (x or {}).get("price_date", ""), "단가기준일 B": (y or {}).get("price_date", ""),
            "공급처 A": (x or {}).get("supplier", ""), "공급처 B": (y or {}).get("supplier", ""),
            "원물가+로스 A": ca, "원물가+로스 B": cb, "차이": cb - ca,
        })

    # ---- 부자재 (이름 기준) ----
    ma_ = {x["name"]: x for x in ra.material_rows}
    mb_ = {x["name"]: x for x in rb.material_rows}
    materials = []
    for name in list(ma_) + [n for n in mb_ if n not in ma_]:
        x, y = ma_.get(name), mb_.get(name)
        ta, tb = (x["total"] if x else 0.0), (y["total"] if y else 0.0)
        status = "추가" if x is None else "삭제" if y is None else ("동일" if abs(ta - tb) < 1e-6 else "변경")
        cat = CATEGORIES[(y or x)["category"]]
        materials.append({"부자재": name, "분류": cat, "상태": status, "A": ta, "B": tb, "차이": tb - ta})

    # ---- 적용 규칙 ----
    def pct(v):
        return f"{v * 100:.2f}%"
    rules_raw = [
        ("계산 방식", calc_mode(qa), calc_mode(qb)),
        ("봉수", f"{qa.bag_count:g}", f"{qb.bag_count:g}"),
        ("1봉 중량(g)", f"{qa.unit_weight_g:g}", f"{qb.unit_weight_g:g}"),
        ("선별단가(원/kg)", f"{qa.sorting_cost_per_kg:,.0f}", f"{qb.sorting_cost_per_kg:,.0f}"),
        ("운송비(원)", f"{qa.shipping_cost:,.0f}", f"{qb.shipping_cost:,.0f}"),
        ("판관비율", pct(qa.sga_rate), pct(qb.sga_rate)),
        ("마진율", pct(qa.margin_rate), pct(qb.margin_rate)),
        ("물류비율", pct(qa.logistics_rate), pct(qb.logistics_rate)),
        ("물류비 VAT 포함 기준", "예" if qa.logistics_vat else "아니오", "예" if qb.logistics_vat else "아니오"),
        ("반올림", qa.rounding, qb.rounding),
    ]
    rules = [{"항목": k, "A": x, "B": y, "다름": "●" if x != y else ""} for k, x, y in rules_raw]

    # ---- 직접원가 변동 요인 (영향 큰 순) ----
    drivers = []
    for r in ingredients:
        if abs(r["차이"]) >= 0.5:
            why = {"추가": "원료 추가", "삭제": "원료 삭제"}.get(r["상태"])
            if why is None:
                parts = []
                if r["단가 A"] is not None and abs(r["단가 A"] - r["단가 B"]) > 1e-9:
                    parts.append(f"단가 {r['단가 A']:,.0f}→{r['단가 B']:,.0f}")
                if abs((r["구성비 A"] or 0) - (r["구성비 B"] or 0)) > 1e-9:
                    parts.append(f"구성비 {r['구성비 A'] * 100:.1f}%→{r['구성비 B'] * 100:.1f}%")
                why = ", ".join(parts) or "봉수/중량/로스 변경"
            drivers.append((abs(r["차이"]), f"원료 {r['원료']} (원물가+로스) {r['차이']:+,.0f}원 — {why}"))
    for r in materials:
        if abs(r["차이"]) >= 0.5:
            drivers.append((abs(r["차이"]), f"부자재 {r['부자재']} {r['차이']:+,.0f}원 — {r['상태']}"))
    for label, x, y in (("선별비", ra.sorting_cost, rb.sorting_cost), ("운송비", ra.shipping_cost, rb.shipping_cost)):
        if abs(y - x) >= 0.5:
            drivers.append((abs(y - x), f"{label} {y - x:+,.0f}원"))
    rate_a = ra.sga + ra.margin + ra.logistics
    rate_b = rb.sga + rb.margin + rb.logistics
    if abs(rate_b - rate_a) >= 0.5:
        drivers.append((abs(rate_b - rate_a), f"판관비·마진·물류비 합계 {rate_b - rate_a:+,.0f}원 (납품가 기준 %)"))
    drivers = [t for _, t in sorted(drivers, key=lambda x: -x[0])]

    dprice, pprice = _diff(ra.price, rb.price)
    headline = (f"납품가 {ra.price:,.0f}원 → {rb.price:,.0f}원 ({dprice:+,.0f}원"
                + (f", {pprice * 100:+.1f}%" if pprice is not None else "") + ")")
    return {
        "headline": headline, "summary": summary, "ingredients": ingredients,
        "materials": materials, "rules": rules, "drivers": drivers,
        "same_product": qa.product_name == qb.product_name,
        "meta_a": ma, "meta_b": mb,
    }
