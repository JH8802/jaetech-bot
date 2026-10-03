"""화면 공통 도우미 (Streamlit). 모듈 import 시점에는 st 를 호출하지 않는다."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from . import db
from .engine import CATEGORIES, ROUNDING, calc_mode, fx_sensitivity
from .export import _lines as cost_lines

CAT_LABEL = CATEGORIES                       # roll -> 롤포장지 ...
CAT_KEY = {v: k for k, v in CATEGORIES.items()}


def won(v: float) -> str:
    return f"{v:,.0f}원"


def pct(v: float | None, digits: int = 1) -> str:
    return "" if v is None else f"{v * 100:.{digits}f}%"


def signed_pct(v: float | None) -> str:
    return "" if v is None else f"{v * 100:+.1f}%"


def num(v: float | None, digits: int = 0) -> str:
    return "" if v is None else f"{v:,.{digits}f}"


def line_chart(df: pd.DataFrame, height: int = 340, step: bool = True) -> None:
    """선 그래프. Y축을 0부터가 아니라 데이터 범위에 맞춰 변동이 잘 보이게 한다.
    단가·환율은 값이 바뀌는 날에 계단식으로 바뀌므로 기본은 step 선."""
    d = df.copy()
    d.index.name = "날짜"
    long = d.reset_index().melt(id_vars="날짜", var_name="항목", value_name="값").dropna()
    chart = alt.Chart(long).mark_line(interpolate="step-after" if step else "linear", point=False).encode(
        x=alt.X("날짜:T", title=None),
        y=alt.Y("값:Q", title=None, scale=alt.Scale(zero=False)),
        color=alt.Color("항목:N", legend=alt.Legend(orient="bottom", title=None)) if df.shape[1] > 1 else alt.value("#1f77b4"),
        tooltip=[alt.Tooltip("날짜:T"), alt.Tooltip("항목:N"), alt.Tooltip("값:Q", format=",.2f")],
    ).properties(height=height)
    st.altair_chart(chart, width="stretch")


def currency_options(include_krw: bool = True) -> dict[str, str]:
    """{화면 라벨: 통화코드}. 미국·베트남·튀르키예 + (기타) 직접 추가한 통화."""
    return {db.currency_label(c): c["code"] for c in db.list_currencies(include_krw)}


def unit_note(code: str) -> str:
    """환율 입력 단위 안내. 예: 'VND → 100동당 원', 'USD → 1달러당 원'"""
    cur = next((c for c in db.list_currencies() if c["code"] == code), None)
    if cur is None:
        return ""
    unit = cur["quote_unit"]
    return f"외화 {unit:g}단위({code})당 원"


def show_fx_sensitivity(q) -> None:
    rows = fx_sensitivity(q)
    if not rows:
        st.caption("외화 단가가 연동된 원료·부자재가 없어 환율 영향은 없습니다 (모두 원화 단가).")
        return
    st.markdown("**환율이 변하면 원가·납품가가 얼마나 변하나** (해당 통화 환율만 변할 때, 단가 기준일의 값 기준)")
    exposure = {}
    for r in rows:
        exposure[r["currency"]] = (r["exposure"], r["share"])
    st.dataframe(pd.DataFrame([{"통화": c, "해당 통화 연동 원가(원)": num(v[0]), "직접원가 중 비중": pct(v[1])}
                               for c, v in exposure.items()]), hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame([{
        "통화": r["currency"], "환율 변동": f"{r['shock'] * 100:+.0f}%",
        "직접원가 변화(원)": f"{r['delta_direct']:+,.1f}", "납품가 변화(원)": f"{r['delta_price']:+,.1f}",
        "납품가 변화율": signed_pct(r["delta_price_rate"])} for r in rows]), hide_index=True, width="stretch")
    biggest = max(rows, key=lambda r: abs(r["delta_price"]) if r["shock"] > 0 else 0)
    st.caption(f"예) {biggest['currency']} 환율이 {biggest['shock'] * 100:+.0f}% 오르면 납품가가 "
               f"{biggest['delta_price']:+,.0f}원({signed_pct(biggest['delta_price_rate'])}) 변합니다.")


def show_result(q, r, fx: bool = True) -> None:
    ch = f" · 판매처: **{q.channel_name}**" if q.channel_name else ""
    asof = f" · 단가·환율 기준일: **{q.as_of_date}**" if q.as_of_date else ""
    st.markdown(f"계산 방식: **{calc_mode(q)}**"
                + (f" (지정 납품가 {won(q.fixed_price)})" if q.fixed_price is not None else "") + ch + asof)
    c = st.columns(4)
    c[0].metric("납품가", won(r.price))
    c[1].metric("원가합계", won(r.total_cost))
    c[2].metric("센터도착가", won(r.center_cost))
    c[3].metric("실질 마진", f"{won(r.effective_margin)} ({pct(r.effective_margin_rate)})")
    for w in r.warnings:
        st.warning(w)

    left, right = st.columns(2)
    with left:
        st.markdown("**원료 (원물가 · 로스 · 가공비 · 환율)**")
        st.dataframe(pd.DataFrame([{
            "원료": x["name"], "구성비": pct(x["ratio"]), "단위중량(g)": round(x["unit_g"], 2),
            "벌크단가(원/kg)": num(x["price_per_kg"]), "통화": x.get("currency", "KRW"),
            "외화단가": num(x.get("foreign_price"), 2), "적용환율": num(x.get("fx_rate"), 4),
            "원물가": num(x["cost"], 1), "로스율": pct(x["loss_rate"]), "로스": num(x["loss"], 1),
            "로스팅비": num(x.get("roasting", 0.0), 1), "선별비": num(x.get("sorting", 0.0), 1),
            "원산지": x.get("origin", ""), "공급처": x.get("supplier", ""),
            "단가기준일": x.get("price_date", ""), "환율기준일": x.get("fx_date", ""),
            "단가출처": x.get("price_source", "")} for x in r.ingredient_rows]),
            hide_index=True, width="stretch")
        st.markdown("**부자재**")
        st.dataframe(pd.DataFrame([{
            "부자재": x["name"], "분류": CAT_LABEL[x["category"]],
            "수량": f'{x.get("qty", 0):g}' + (" (봉수연동)" if x.get("per_bag") else ""),
            "기본": num(x["base"], 1), "loss": num(x["loss"], 1), "합계": num(x["total"], 1),
            "통화": x.get("currency", "KRW"), "외화단가": num(x.get("foreign_price"), 2),
            "적용환율": num(x.get("fx_rate"), 4), "단가기준일": x.get("price_date", "")}
            for x in r.material_rows]), hide_index=True, width="stretch")
    with right:
        st.markdown("**원가 구성**")
        lines = cost_lines(q, r)
        st.dataframe(pd.DataFrame([{"항목": label, "금액(원)": f"{val:,.1f}"} for label, val in lines]),
                     hide_index=True, width="stretch", height=38 + 35 * len(lines))
        st.caption(f"(참고) 위 부자재 금액에는 부자재 loss {r.material_loss_cost:,.1f}원이 포함되어 있습니다.")
        if q.fixed_price is None:
            st.caption(f"계산 납품가 {r.exact_price:,.2f}원 → {ROUNDING[q.rounding]} → {r.price:,.0f}원")
    if fx:
        with st.expander("💱 환율 변동이 원가에 미치는 영향 (민감도)"):
            show_fx_sensitivity(q)
