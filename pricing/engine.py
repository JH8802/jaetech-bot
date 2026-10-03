"""원가/납품가 계산 엔진 (순수 계산 로직 - DB·화면과 무관).

기존 견적 엑셀(하루견과, 90칼로리 넛츠, 1 MONTH NUTS 등)의 계산 규칙을 그대로 옮기고,
로스팅비·3PL·판매처(마트/온라인) 비용을 확장한 것.

계산 흐름 (1세트 = 1개 제품 기준, 원)
  원물가     = 벌크단가(원/kg) x 단위중량(g) x 봉수 / 1000                 (원료별, 외화단가는 환율로 원화 환산된 값)
  로스팅비   = 로스팅단가(원/kg) x 원료중량(kg)                            (원료별)
  선별비     = 선별단가(원/kg) x 원료중량(kg)  (원료별) + 제품 공통 선별단가 x 총중량
  원재료로스 = 원물가 x 로스율                                             (원료별)
  부자재     = 단가 x 수량 / 나누는수(입수) x (1 + loss율)                  (롤포장지/포장지/인케이스/카톤박스/소분비/기타)
               수량이 '봉수 연동'이면 수량 x 봉수
  직접원가   = 원물가 + 로스팅비 + 선별비 + 원재료로스 + 부자재 + 운송비 + 3PL이용료
  센터도착가 = 직접원가 + 판관비 + 마진
  판매처비용 = 물류비(마트별) + 온라인수수료 + 홍보비 + 기획전비용 + 택배비
  원가합계   = 센터도착가 + 판매처비용
  판관비·마진·물류비율·수수료율·홍보비율·기획전비율은 '납품가 기준 %', 정액 항목(개당 원)은 직접 더함
  납품가 = (직접원가 + 정액 판매처비용) / (1 - 모든 % 합계)
"""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field, asdict

VAT = 1.1

# 부자재 분류. 순서가 화면/엑셀 표시 순서다.
CATEGORIES = {
    "roll": "롤포장지",
    "pack": "포장지",
    "incase": "인케이스",
    "box": "카톤박스",
    "split": "소분비",
    "etc": "기타",
}

# 계산 방식 (이력·엑셀 표시용)
MODE_AUTO = "자동 계산"
MODE_FIXED = "납품가 직접 지정"

# 납품가 반올림 방식
ROUNDING = {
    "round": "1원 단위 반올림",
    "ceil10": "10원 단위 올림",
    "none": "반올림 안 함",
}

CHANNEL_KINDS = {"offline": "오프라인(마트)", "online": "온라인"}


@dataclass
class IngredientLine:
    name: str
    ratio: float              # 구성비 (0.35 = 35%)
    price_per_kg: float       # 벌크단가 (원/kg). 외화 단가는 환율 적용 후의 원화 값
    loss_rate: float = 0.0    # 로스율 (0.05 = 5%)
    # --- 이력 추적용 (계산에는 쓰이지 않음) ---
    origin: str = ""          # 원산지
    supplier: str = ""        # 공급처
    price_date: str = ""      # 단가 기준일 (적용된 단가의 적용일)
    price_source: str = ""    # '마스터 단가' / '제품 직접입력'
    # --- 원가 항목 ---
    roasting_per_kg: float = 0.0   # 로스팅 단가 (원/kg)
    sorting_per_kg: float = 0.0    # 원료별 선별 단가 (원/kg)
    # --- 환율 정보 (환율 민감도 분석용) ---
    currency: str = "KRW"
    foreign_price: float | None = None   # 외화 단가 (/kg)
    fx_rate: float | None = None         # 적용 환율 (원 / 외화 1단위)
    fx_date: str = ""                    # 환율 기준일


@dataclass
class MaterialLine:
    name: str
    category: str             # CATEGORIES 의 키
    unit_price: float         # 단가 (원). 외화 단가는 환율 적용 후의 원화 값
    qty: float = 1.0          # 수량
    divisor: float = 1.0      # 나누는 수 (카톤박스 입수 등)
    loss_rate: float = 0.0    # loss율 (0.03 = 3%)
    per_bag: bool = False     # True면 수량 x 봉수 (소포장지·소분비·롤포장지 등)
    # --- 이력/환율 정보 ---
    price_date: str = ""
    currency: str = "KRW"
    foreign_price: float | None = None
    fx_rate: float | None = None
    fx_date: str = ""


@dataclass
class QuoteInput:
    product_name: str
    bag_count: float                  # 봉수 (30입이면 30)
    unit_weight_g: float              # 1봉 중량(g)
    ingredients: list[IngredientLine] = field(default_factory=list)
    materials: list[MaterialLine] = field(default_factory=list)
    sorting_cost_per_kg: float = 0.0  # 제품 공통 선별단가 (원/kg), 없으면 0
    shipping_cost: float = 0.0        # 운송비 (센터 입고, 원/개)
    three_pl_cost: float = 0.0        # 3PL 이용료 (원/개)
    sga_rate: float = 0.0             # 판관비율
    margin_rate: float = 0.0          # 마진율 (선택)
    logistics_rate: float = 0.0       # 물류비율 (선택)
    logistics_vat: bool = False       # 물류비 기준을 VAT 포함 납품가로 할지
    rounding: str = "round"
    fixed_price: float | None = None  # 값이 있으면 '납품가 지정 모드'
    # --- 판매처(채널) ---
    channel_name: str = ""            # '' = 판매처 미선택(기본 설정)
    channel_kind: str = ""            # offline / online
    logistics_fixed: float = 0.0      # 마트별 정액 물류비 (원/개)
    fee_rate: float = 0.0             # 온라인 업체 수수료율
    promo_rate: float = 0.0           # 온라인 업체 홍보비율
    event_rate: float = 0.0           # 온라인 업체 기획전 비용률
    event_fixed: float = 0.0          # 온라인 업체 기획전 비용 정액 (원/개)
    parcel_cost: float = 0.0          # 택배비 (원/개)
    online_vat: bool = False          # 수수료·홍보비·기획전 %를 VAT 포함 판매가 기준으로
    # --- 기타 ---
    as_of_date: str = ""              # 견적 기준일 (단가·환율을 이 날짜 기준으로 적용)
    input_notes: list[str] = field(default_factory=list)   # 입력 단계 경고(단가 없음 등)


@dataclass
class QuoteResult:
    ingredient_rows: list[dict]
    material_rows: list[dict]
    materials_cost: float       # 원물가 합계
    sorting_cost: float         # 선별비 합계 (제품 공통 + 원료별)
    loss_cost: float            # 원재료 로스 합계
    pack_cost: float            # 포장지
    split_cost: float           # 소분비
    box_cost: float             # 카톤박스
    shipping_cost: float
    direct_cost: float          # 판관비/마진/판매처비용 제외 직접원가
    exact_price: float          # 반올림 전 계산 납품가
    price: float                # 최종 납품가
    sga: float
    margin: float
    center_cost: float          # 센터도착가
    logistics: float            # 물류비 (% + 정액)
    total_cost: float           # 원가합계
    profit: float               # 납품가 - 원가합계 (반올림 차익 또는 적자)
    effective_margin: float     # 마진 + profit
    effective_margin_rate: float
    warnings: list[str]
    # ---- 확장 항목 (예전 이력에는 없으므로 기본값) ----
    roasting_cost: float = 0.0
    roll_cost: float = 0.0
    incase_cost: float = 0.0
    etc_cost: float = 0.0
    material_loss_cost: float = 0.0   # 부자재 loss 합계 (각 부자재 금액에 이미 포함됨, 참고용)
    three_pl_cost: float = 0.0
    fee: float = 0.0                  # 온라인 수수료
    promo: float = 0.0                # 홍보비
    event: float = 0.0                # 기획전 비용 (% + 정액)
    parcel: float = 0.0               # 택배비
    channel_cost: float = 0.0         # 판매처 비용 합계 (물류비+수수료+홍보비+기획전+택배비)

    def to_dict(self) -> dict:
        return asdict(self)


# 화면·엑셀·비교에서 공통으로 쓰는 원가 항목 (라벨, QuoteResult 속성, 항상 표시 여부)
COST_LINES = [
    ("원물가", "materials_cost", True), ("로스팅비", "roasting_cost", False),
    ("선별비", "sorting_cost", True), ("원재료 로스", "loss_cost", True),
    ("롤포장지", "roll_cost", False), ("포장지", "pack_cost", True),
    ("인케이스", "incase_cost", False), ("카톤박스", "box_cost", True),
    ("소분비", "split_cost", True), ("기타 부자재", "etc_cost", False),
    ("운송비", "shipping_cost", True), ("3PL 이용료", "three_pl_cost", False),
    ("직접원가", "direct_cost", True),
    ("판관비", "sga", True), ("마진", "margin", True), ("센터도착가", "center_cost", True),
    ("물류비", "logistics", True), ("온라인 수수료", "fee", False), ("홍보비", "promo", False),
    ("기획전 비용", "event", False), ("택배비", "parcel", False),
    ("원가합계", "total_cost", True), ("납품가", "price", True), ("실질 마진", "effective_margin", True),
]


def calc_mode(q: QuoteInput) -> str:
    return MODE_FIXED if q.fixed_price is not None else MODE_AUTO


def apply_rounding(value: float, mode: str) -> float:
    value = round(value, 6)
    if mode == "round":
        return float(math.floor(value + 0.5))
    if mode == "ceil10":
        return float(math.ceil(value / 10) * 10)
    if mode == "none":
        return value
    raise ValueError(f"알 수 없는 반올림 방식: {mode}")


def calculate(q: QuoteInput) -> QuoteResult:
    warnings: list[str] = list(q.input_notes)

    ratio_sum = sum(i.ratio for i in q.ingredients)
    if q.ingredients and abs(ratio_sum - 1.0) > 0.001:
        warnings.append(f"구성비 합계가 100%가 아닙니다 ({ratio_sum * 100:.1f}%)")
    for m in q.materials:
        if m.category not in CATEGORIES:
            raise ValueError(f"부자재 분류 오류: {m.name} / {m.category}")
        if m.divisor == 0:
            raise ValueError(f"'나누는 수'가 0입니다: {m.name}")

    # ---- 원료 ----
    ingredient_rows = []
    total_g = 0.0
    for i in q.ingredients:
        unit_g = q.unit_weight_g * i.ratio
        kg = unit_g * q.bag_count / 1000
        cost = i.price_per_kg * kg
        loss = cost * i.loss_rate
        total_g += unit_g * q.bag_count
        ingredient_rows.append({
            "name": i.name, "ratio": i.ratio, "unit_g": unit_g,
            "price_per_kg": i.price_per_kg, "cost": cost,
            "loss_rate": i.loss_rate, "loss": loss,
            "roasting": i.roasting_per_kg * kg, "sorting": i.sorting_per_kg * kg,
            "origin": i.origin, "supplier": i.supplier,
            "price_date": i.price_date, "price_source": i.price_source,
            "currency": i.currency, "foreign_price": i.foreign_price,
            "fx_rate": i.fx_rate, "fx_date": i.fx_date,
        })
    materials_cost = sum(r["cost"] for r in ingredient_rows)
    loss_cost = sum(r["loss"] for r in ingredient_rows)
    roasting_cost = sum(r["roasting"] for r in ingredient_rows)
    sorting_cost = (q.sorting_cost_per_kg * total_g / 1000
                    + sum(r["sorting"] for r in ingredient_rows))

    # ---- 부자재 ----
    material_rows = []
    by_cat = {k: 0.0 for k in CATEGORIES}
    material_loss = 0.0
    for m in q.materials:
        qty = m.qty * q.bag_count if m.per_bag else m.qty
        base = m.unit_price * qty / m.divisor
        loss = base * m.loss_rate
        total = base + loss
        by_cat[m.category] += total
        material_loss += loss
        material_rows.append({
            "name": m.name, "category": m.category, "qty": qty, "per_bag": m.per_bag,
            "base": base, "loss": loss, "total": total,
            "price_date": m.price_date, "currency": m.currency,
            "foreign_price": m.foreign_price, "fx_rate": m.fx_rate, "fx_date": m.fx_date,
        })

    direct = (materials_cost + roasting_cost + sorting_cost + loss_cost + sum(by_cat.values())
              + q.shipping_cost + q.three_pl_cost)

    # ---- 납품가 (납품가 기준 % 항목은 한 번에 역산) ----
    vat_on_log = VAT if q.logistics_vat else 1.0
    vat_on_online = VAT if q.online_vat else 1.0
    r_log = q.logistics_rate * vat_on_log
    r_fee = q.fee_rate * vat_on_online
    r_promo = q.promo_rate * vat_on_online
    r_event = q.event_rate * vat_on_online
    rate_sum = q.sga_rate + q.margin_rate + r_log + r_fee + r_promo + r_event
    fixed_channel = q.logistics_fixed + q.event_fixed + q.parcel_cost
    if rate_sum >= 1:
        raise ValueError("판관비·마진·물류비·수수료 등 비율 합계가 100% 이상입니다")
    exact_price = (direct + fixed_channel) / (1 - rate_sum)

    if q.fixed_price is not None:
        price = float(q.fixed_price)
    else:
        price = apply_rounding(exact_price, q.rounding)

    sga = price * q.sga_rate
    margin = price * q.margin_rate
    logistics = price * r_log + q.logistics_fixed
    fee = price * r_fee
    promo = price * r_promo
    event = price * r_event + q.event_fixed
    parcel = q.parcel_cost
    channel_cost = logistics + fee + promo + event + parcel
    center_cost = direct + sga + margin
    total_cost = center_cost + channel_cost
    profit = price - total_cost
    if abs(profit) < 1e-6:                   # 부동소수점 오차(-0.0)를 0으로
        profit = 0.0
    effective_margin = margin + profit
    if abs(effective_margin) < 1e-6:
        effective_margin = 0.0
    eff_rate = effective_margin / price if price else 0.0

    if q.fixed_price is not None and profit < -0.5:
        warnings.append(
            f"지정 납품가가 원가합계보다 {-profit:,.0f}원 낮습니다 (적자)")
    if price and effective_margin < -0.5:
        warnings.append(f"실질 마진이 마이너스입니다 ({eff_rate * 100:.1f}%)")

    return QuoteResult(
        ingredient_rows=ingredient_rows, material_rows=material_rows,
        materials_cost=materials_cost, sorting_cost=sorting_cost,
        loss_cost=loss_cost, pack_cost=by_cat["pack"],
        split_cost=by_cat["split"], box_cost=by_cat["box"],
        shipping_cost=q.shipping_cost, direct_cost=direct,
        exact_price=exact_price, price=price, sga=sga, margin=margin,
        center_cost=center_cost, logistics=logistics, total_cost=total_cost,
        profit=profit, effective_margin=effective_margin,
        effective_margin_rate=eff_rate, warnings=warnings,
        roasting_cost=roasting_cost, roll_cost=by_cat["roll"], incase_cost=by_cat["incase"],
        etc_cost=by_cat["etc"], material_loss_cost=material_loss, three_pl_cost=q.three_pl_cost,
        fee=fee, promo=promo, event=event, parcel=parcel, channel_cost=channel_cost,
    )


# =====================================================================
# 환율 민감도: "환율이 N% 변하면 원가·납품가가 얼마나 변하나"
# =====================================================================
def fx_exposure(q: QuoteInput) -> dict[str, float]:
    """통화별로 직접원가 중 해당 통화에 연동된 금액 (원물가+원재료로스, 부자재+부자재 loss)."""
    res = calculate(q)
    exp: dict[str, float] = {}
    for line, row in zip(q.ingredients, res.ingredient_rows):
        if line.currency != "KRW" and line.foreign_price is not None:
            exp[line.currency] = exp.get(line.currency, 0.0) + row["cost"] + row["loss"]
    for line, row in zip(q.materials, res.material_rows):
        if line.currency != "KRW" and line.foreign_price is not None:
            exp[line.currency] = exp.get(line.currency, 0.0) + row["total"]
    return exp


def fx_sensitivity(q: QuoteInput, shocks=(-0.10, -0.05, 0.05, 0.10)) -> list[dict]:
    """각 통화 환율이 shock(±%) 변할 때의 직접원가·납품가 변화.
    납품가 지정 모드면 지정가를 풀고 '자동 계산' 기준으로 비교한다."""
    base_q = deepcopy(q)
    base_q.fixed_price = None
    base = calculate(base_q)
    rows = []
    for cur, exposure in sorted(fx_exposure(base_q).items()):
        for s in shocks:
            sq = deepcopy(base_q)
            for line in sq.ingredients:
                if line.currency == cur and line.foreign_price is not None:
                    line.price_per_kg *= (1 + s)
            for line in sq.materials:
                if line.currency == cur and line.foreign_price is not None:
                    line.unit_price *= (1 + s)
            r = calculate(sq)
            rows.append({
                "currency": cur, "exposure": exposure,
                "share": exposure / base.direct_cost if base.direct_cost else 0.0,
                "shock": s, "delta_direct": r.direct_cost - base.direct_cost,
                "delta_price": r.price - base.price,
                "delta_price_rate": (r.price - base.price) / base.price if base.price else 0.0,
            })
    return rows
