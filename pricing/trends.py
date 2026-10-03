"""가격 추이 분석: 일별 가격 시리즈, 기간 변동률, 현지가/환율 분해, 연도별 변동, 제품 원가 추이.

DB와 무관한 순수 로직. PriceBook(날짜 기준 단가·환율 해석기)을 받아 계산한다.
  kind = 'ingredient'(원료) | 'material'(부자재)
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

from .engine import calculate
from .prices import KRW, PriceBook

MAX_POINTS = 800


def _d(s: str) -> date:
    return date.fromisoformat(s)


def daterange(d_from: str, d_to: str):
    a, b = _d(d_from), _d(d_to)
    if b < a:
        raise ValueError("종료일이 시작일보다 빠릅니다")
    if (b - a).days + 1 > 3700:
        raise ValueError("조회 기간이 너무 깁니다 (최대 약 10년)")
    d = a
    while d <= b:
        yield d.isoformat()
        d += timedelta(days=1)


def _resolve(pb: PriceBook, kind: str, item_id: int, day: str):
    return pb.ingredient(item_id, day) if kind == "ingredient" else pb.material(item_id, day)


# =====================================================================
# 품목 하나의 일별 시리즈
# =====================================================================
def daily_series(pb: PriceBook, kind: str, item_id: int, d_from: str, d_to: str) -> list[dict]:
    """기간 내 일별 원화 단가. 최초 단가 기록 이전 날짜는 제외한다.
    외화(자동 환율) 단가는 환율이 바뀌는 날마다 원화 값이 달라진다."""
    out = []
    prev_key = None
    for day in daterange(d_from, d_to):
        res = _resolve(pb, kind, item_id, day)
        if res is None or res["before_first"]:
            continue
        key = (round(res["krw"], 6), res["currency"], res["foreign"], res["fx"])
        out.append({
            "date": day, "krw": res["krw"], "currency": res["currency"], "foreign": res["foreign"],
            "fx": res["fx"], "fx_date": res["fx_date"], "price_date": res["price_date"],
            "changed": prev_key is not None and key != prev_key,
        })
        prev_key = key
    return out


def period_stats(series: list[dict]) -> dict | None:
    if not series:
        return None
    first, last = series[0], series[-1]
    vals = [r["krw"] for r in series]
    lo = min(series, key=lambda r: r["krw"])
    hi = max(series, key=lambda r: r["krw"])
    delta = last["krw"] - first["krw"]
    return {
        "start_date": first["date"], "end_date": last["date"],
        "start": first["krw"], "end": last["krw"],
        "delta": delta, "rate": delta / first["krw"] if first["krw"] else None,
        "min": lo["krw"], "min_date": lo["date"], "max": hi["krw"], "max_date": hi["date"],
        "avg": mean(vals), "days": len(series), "change_days": sum(1 for r in series if r["changed"]),
    }


def decompose(series: list[dict]) -> dict | None:
    """원화 단가 변동 = 현지가(외화 단가) 변동 효과 + 환율 변동 효과.
       KRW = 외화단가 x 환율  →  효과합 = 전체 변동 (순차 분해: 현지가는 기초 환율로, 환율은 기말 현지가로)."""
    if len(series) < 2:
        return None
    first, last = series[0], series[-1]
    cur = first["currency"]
    if cur == KRW or any(r["currency"] != cur or r["foreign"] is None or r["fx"] is None for r in series):
        return None
    f0, f1, x0, x1 = first["foreign"], last["foreign"], first["fx"], last["fx"]
    price_effect = (f1 - f0) * x0
    fx_effect = f1 * (x1 - x0)
    k0, k1 = first["krw"], last["krw"]
    return {
        "currency": cur,
        "foreign_start": f0, "foreign_end": f1, "fx_start": x0, "fx_end": x1,
        "foreign_rate": (f1 / f0 - 1) if f0 else None,
        "fx_rate": (x1 / x0 - 1) if x0 else None,
        "krw_rate": (k1 / k0 - 1) if k0 else None,
        "price_effect": price_effect, "fx_effect": fx_effect, "total": k1 - k0,
        "index": [{"date": r["date"],
                   "원화 단가": r["krw"] / k0 * 100 if k0 else None,
                   "현지 단가": r["foreign"] / f0 * 100 if f0 else None,
                   "환율": r["fx"] / x0 * 100 if x0 else None} for r in series],
    }


def aggregate(series: list[dict], freq: str) -> list[dict]:
    """freq: 'D' 일별 그대로, 'W' 주별(월요일 시작), 'M' 월별. 평균/최저/최고/기말."""
    if freq == "D":
        return [{"period": r["date"], "avg": r["krw"], "min": r["krw"], "max": r["krw"], "last": r["krw"]}
                for r in series]
    groups: dict[str, list[float]] = {}
    for r in series:
        d = _d(r["date"])
        key = (d - timedelta(days=d.weekday())).isoformat() if freq == "W" else r["date"][:7]
        groups.setdefault(key, []).append(r["krw"])
    return [{"period": k, "avg": mean(v), "min": min(v), "max": max(v), "last": v[-1]}
            for k, v in sorted(groups.items())]


# =====================================================================
# 전 품목 비교
# =====================================================================
def ranking_table(pb: PriceBook, kind: str, names: dict[int, str], d_from: str, d_to: str) -> list[dict]:
    """모든 품목의 기간 변동 (변동률 큰 순). 외화 품목은 현지가/환율 변동률도 함께."""
    rows = []
    for item_id, name in names.items():
        s = daily_series(pb, kind, item_id, d_from, d_to)
        st = period_stats(s)
        if st is None:
            continue
        dec = decompose(s)
        rows.append({
            "id": item_id, "name": name, "start_date": st["start_date"], "end_date": st["end_date"],
            "start": st["start"], "end": st["end"], "delta": st["delta"], "rate": st["rate"],
            "min": st["min"], "max": st["max"], "avg": st["avg"], "change_days": st["change_days"],
            "currency": dec["currency"] if dec else (s[-1]["currency"] if s else KRW),
            "foreign_rate": dec["foreign_rate"] if dec else None,
            "fx_rate": dec["fx_rate"] if dec else None,
            "price_effect": dec["price_effect"] if dec else None,
            "fx_effect": dec["fx_effect"] if dec else None,
        })
    rows.sort(key=lambda r: (-(r["rate"] if r["rate"] is not None else -9e9), r["name"]))
    return rows


def yearly_table(pb: PriceBook, kind: str, names: dict[int, str], years: list[int],
                 today: str | None = None) -> list[dict]:
    """품목 x 연도: 전년 말 가격 → 해당 연도 말 가격 변동률, 연평균/최저/최고.
       처음 등록된 해는 첫 단가를 기준으로 한다. 올해는 오늘까지."""
    today = today or date.today().isoformat()
    rows = []
    for item_id, name in names.items():
        recs = pb.rows(kind, item_id)
        if not recs:
            continue
        first_date = recs[0]["effective_date"]
        for y in years:
            y_start, y_end = f"{y}-01-01", min(f"{y}-12-31", today)
            if y_end < first_date or y_start > today:
                continue
            end_res = _resolve(pb, kind, item_id, y_end)
            prev_end = f"{y - 1}-12-31"
            prev_res = _resolve(pb, kind, item_id, prev_end) if prev_end >= first_date else None
            if prev_res is not None and not prev_res["before_first"]:
                base, base_label = prev_res["krw"], f"{y - 1}년 말"
            else:
                first_in_year = _resolve(pb, kind, item_id, max(y_start, first_date))
                base, base_label = first_in_year["krw"], "최초 등록가"
            s = daily_series(pb, kind, item_id, max(y_start, first_date), y_end)
            st = period_stats(s)
            end_krw = end_res["krw"]
            rows.append({
                "name": name, "year": y, "base_label": base_label, "base": base, "end": end_krw,
                "delta": end_krw - base, "rate": (end_krw / base - 1) if base else None,
                "avg": st["avg"] if st else None, "min": st["min"] if st else None,
                "max": st["max"] if st else None, "partial": y_end < f"{y}-12-31",
            })
    return rows


# =====================================================================
# 환율
# =====================================================================
def fx_daily(pb: PriceBook, currency: str, d_from: str, d_to: str) -> list[dict]:
    """일별 환율 (환율 표기 단위 기준: VND는 100동당 원). 이력이 없는 날은 직전 값."""
    unit = pb.unit.get(currency, 1.0)
    out, prev = [], None
    for day in daterange(d_from, d_to):
        found = pb.fx_asof(currency, day)
        if found is None:
            continue
        rate = found[0] * unit
        out.append({"date": day, "rate": rate, "rate_date": found[1],
                    "changed": prev is not None and abs(rate - prev) > 1e-12})
        prev = rate
    return out


# =====================================================================
# 제품 원가 추이
# =====================================================================
def sample_dates(d_from: str, d_to: str, step: str) -> list[str]:
    """step: 'D' 매일, 'W' 매주, 'M' 매월 말 (시작일·종료일 포함). 최대 MAX_POINTS 개."""
    days = list(daterange(d_from, d_to))
    if step == "D":
        pts = days
    elif step == "W":
        pts = days[::7]
    elif step == "M":
        pts = [d for i, d in enumerate(days)
               if i == 0 or (_d(d) + timedelta(days=1)).day == 1]
    else:
        raise ValueError("step 은 D/W/M 중 하나")
    if days[-1] not in pts:
        pts = pts + [days[-1]]
    if len(pts) > MAX_POINTS:
        raise ValueError(f"조회 점이 {len(pts)}개로 너무 많습니다. 주별/월별로 바꾸세요")
    return pts


def product_series(assemble, detail: dict, settings: dict, channel: dict | None, pb: PriceBook,
                   d_from: str, d_to: str, step: str = "W", fixed_price: float | None = None) -> list[dict]:
    """제품의 납품가·원가 구성이 날짜에 따라 어떻게 변했는지 (그 날짜의 단가·환율 기준).
       assemble 은 db.assemble_quote (순환 import 방지를 위해 주입)."""
    out = []
    for day in sample_dates(d_from, d_to, step):
        q = assemble(detail, settings, channel, pb, day, fixed_price)
        r = calculate(q)
        packaging = (r.roll_cost + r.pack_cost + r.incase_cost + r.box_cost + r.split_cost + r.etc_cost)
        out.append({
            "date": day, "price": r.price, "total_cost": r.total_cost, "direct_cost": r.direct_cost,
            "ingredients": r.materials_cost + r.loss_cost, "roasting_sorting": r.roasting_cost + r.sorting_cost,
            "materials": packaging, "logistics_etc": r.shipping_cost + r.three_pl_cost,
            "channel_cost": r.channel_cost, "effective_margin": r.effective_margin,
            "margin_rate": r.effective_margin_rate,
            "notes": " / ".join(r.warnings),
        })
    return out
