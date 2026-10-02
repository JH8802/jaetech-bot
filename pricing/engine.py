"""원가/납품가 계산 엔진 (순수 계산 로직 - DB·화면과 무관).

기존 견적 엑셀(하루견과, 90칼로리 넛츠, 1 MONTH NUTS 등)의 계산 규칙을 그대로 옮긴 것.

계산 흐름
  원물가   = 벌크단가(원/kg) x 단위중량(g) x 봉수 / 1000        (원료별)
  선별비   = 선별단가(원/kg) x 총중량(kg)                        (선택)
  로스     = 원물가 x 로스율                                     (원료별)
  부자재   = 단가 x 수량 / 나누는수(입수) x (1 + loss율)          (포장지/소분비/박스비로 분류)
  직접원가 = 원물가 + 선별비 + 로스 + 부자재 + 운송비
  센터도착가 = 직접원가 + 판관비 + 마진
  원가합계 = 센터도착가 + 물류비
  판관비/마진/물류비는 '납품가 기준 %' 이므로
  납품가 = 직접원가 / (1 - 판관비% - 마진% - 물류비% x (VAT 포함이면 1.1))
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

VAT = 1.1

# 부자재 분류 (기존 엑셀의 컬럼과 동일)
CATEGORIES = {"pack": "포장지", "split": "소분비", "box": "박스비"}

# 계산 방식 (이력·엑셀 표시용)
MODE_AUTO = "자동 계산"
MODE_FIXED = "납품가 직접 지정"

# 납품가 반올림 방식
ROUNDING = {
    "round": "1원 단위 반올림",
    "ceil10": "10원 단위 올림",
    "none": "반올림 안 함",
}


@dataclass
class IngredientLine:
    name: str
    ratio: float              # 구성비 (0.35 = 35%)
    price_per_kg: float       # 벌크단가 (원/kg)
    loss_rate: float = 0.0    # 로스율 (0.05 = 5%)
    # --- 이력 추적용 (계산에는 쓰이지 않음) ---
    origin: str = ""          # 원산지
    supplier: str = ""        # 공급처
    price_date: str = ""      # 단가 기준일 (원료 마스터 최신 단가의 적용일)
    price_source: str = ""    # '마스터 최신단가' / '제품 직접입력'


@dataclass
class MaterialLine:
    name: str
    category: str             # 'pack' | 'split' | 'box'
    unit_price: float         # 단가
    qty: float = 1.0          # 수량 (봉수 등)
    divisor: float = 1.0      # 나누는 수 (카톤박스 입수 등)
    loss_rate: float = 0.0    # loss율 (0.03 = 3%)


@dataclass
class QuoteInput:
    product_name: str
    bag_count: float                  # 봉수 (30입이면 30)
    unit_weight_g: float              # 1봉 중량(g)
    ingredients: list[IngredientLine] = field(default_factory=list)
    materials: list[MaterialLine] = field(default_factory=list)
    sorting_cost_per_kg: float = 0.0  # 선별단가 (원/kg), 없으면 0
    shipping_cost: float = 0.0        # 운송비 (3PL 포함, 원)
    sga_rate: float = 0.0             # 판관비율
    margin_rate: float = 0.0          # 마진율 (선택)
    logistics_rate: float = 0.0       # 물류비율 (선택)
    logistics_vat: bool = False       # 물류비 기준을 VAT 포함 납품가로 할지
    rounding: str = "round"
    fixed_price: float | None = None  # 값이 있으면 '납품가 지정 모드'


@dataclass
class QuoteResult:
    ingredient_rows: list[dict]
    material_rows: list[dict]
    materials_cost: float       # 원물가 합계
    sorting_cost: float
    loss_cost: float
    pack_cost: float
    split_cost: float
    box_cost: float
    shipping_cost: float
    direct_cost: float          # 판관비/마진/물류비 제외 직접원가
    exact_price: float          # 반올림 전 계산 납품가
    price: float                # 최종 납품가
    sga: float
    margin: float
    center_cost: float          # 센터도착가
    logistics: float
    total_cost: float           # 원가합계
    profit: float               # 납품가 - 원가합계 (반올림 차익 또는 적자)
    effective_margin: float     # 마진 + profit
    effective_margin_rate: float
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


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
    warnings: list[str] = []

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
        cost = i.price_per_kg * unit_g * q.bag_count / 1000
        loss = cost * i.loss_rate
        total_g += unit_g * q.bag_count
        ingredient_rows.append({
            "name": i.name, "ratio": i.ratio, "unit_g": unit_g,
            "price_per_kg": i.price_per_kg, "cost": cost,
            "loss_rate": i.loss_rate, "loss": loss,
            "origin": i.origin, "supplier": i.supplier,
            "price_date": i.price_date, "price_source": i.price_source,
        })
    materials_cost = sum(r["cost"] for r in ingredient_rows)
    loss_cost = sum(r["loss"] for r in ingredient_rows)
    sorting_cost = q.sorting_cost_per_kg * total_g / 1000

    # ---- 부자재 ----
    material_rows = []
    by_cat = {"pack": 0.0, "split": 0.0, "box": 0.0}
    for m in q.materials:
        base = m.unit_price * m.qty / m.divisor
        loss = base * m.loss_rate
        total = base + loss
        by_cat[m.category] += total
        material_rows.append({
            "name": m.name, "category": m.category, "base": base,
            "loss": loss, "total": total,
        })

    direct = (materials_cost + sorting_cost + loss_cost + sum(by_cat.values())
              + q.shipping_cost)

    # ---- 납품가 ----
    logistics_eff = q.logistics_rate * (VAT if q.logistics_vat else 1.0)
    rate_sum = q.sga_rate + q.margin_rate + logistics_eff
    if rate_sum >= 1:
        raise ValueError("판관비+마진+물류비 비율 합계가 100% 이상입니다")
    exact_price = direct / (1 - rate_sum)

    if q.fixed_price is not None:
        price = float(q.fixed_price)
    else:
        price = apply_rounding(exact_price, q.rounding)

    sga = price * q.sga_rate
    margin = price * q.margin_rate
    logistics = price * logistics_eff
    center_cost = direct + sga + margin
    total_cost = center_cost + logistics
    profit = price - total_cost
    effective_margin = margin + profit
    eff_rate = effective_margin / price if price else 0.0

    if q.fixed_price is not None and profit < -0.5:
        warnings.append(
            f"지정 납품가가 원가합계보다 {-profit:,.0f}원 낮습니다 (적자)")
    if price and effective_margin < 0:
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
    )
