"""가격 추이 화면 (Streamlit): 기간 조회 · 그래프(선/막대) · 변동률 · 연도별 · 환율 영향 · 제품 원가 추이."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import db, trends
from .export import item_trend_xlsx, product_trend_xlsx, ranking_xlsx, yearly_xlsx
from .ui_common import line_chart, num, pct, signed_pct, won

KIND_LABEL = {"ingredient": "원료", "material": "부자재"}


def _range(key: str, days: int = 180):
    rng = st.date_input("조회 기간 (시작일 ~ 종료일)", value=(date.today() - timedelta(days=days), date.today()),
                        key=key)
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.info("종료일까지 선택하세요.")
        return None
    return rng[0].isoformat(), rng[1].isoformat()


def _names(kind: str) -> dict[int, str]:
    rows = db.list_ingredients() if kind == "ingredient" else db.list_materials()
    return {r["id"]: r["name"] for r in rows}


def _dated_df(rows: list[dict], date_key: str, cols: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame([{**{label: r[k] for label, k in cols.items()}, "_d": r[date_key]} for r in rows])
    df.index = pd.to_datetime(df.pop("_d"))
    return df


def _tab_item(pb) -> None:
    c = st.columns([1, 2])
    kind = c[0].radio("구분", list(KIND_LABEL), format_func=KIND_LABEL.get, horizontal=True, key="tr_kind1")
    names = _names(kind)
    if not names:
        st.info("등록된 품목이 없습니다.")
        return
    item_id = c[1].selectbox("품목", list(names), format_func=names.get, key="tr_item1")
    rng = _range("tr_rng1")
    if rng is None:
        return
    try:
        series = trends.daily_series(pb, kind, item_id, *rng)
    except ValueError as e:
        st.error(str(e))
        return
    if not series:
        st.info("이 기간에 해당하는 단가 기록이 없습니다. (최초 단가 적용일 이전이거나 기간에 단가가 없음)")
        return
    st_ = trends.period_stats(series)
    dec = trends.decompose(series)

    m = st.columns(4)
    m[0].metric("시작 단가", won(st_["start"]), help=st_["start_date"])
    m[1].metric("종료 단가", won(st_["end"]), help=st_["end_date"])
    m[2].metric("변동", f"{st_['delta']:+,.0f}원", signed_pct(st_["rate"]))
    m[3].metric("가격이 바뀐 날", f"{st_['change_days']}일", help="단가 변경 또는 환율 변동으로 원화 단가가 달라진 날")
    m2 = st.columns(3)
    m2[0].metric("최저", won(st_["min"]), help=st_["min_date"])
    m2[1].metric("최고", won(st_["max"]), help=st_["max_date"])
    m2[2].metric("평균", won(st_["avg"]))

    views = {"선 그래프 (일별)": "D", "막대 그래프 (주별 평균)": "W", "막대 그래프 (월별 평균)": "M"}
    view = st.radio("그래프", list(views), horizontal=True, key="tr_view1")
    freq = views[view]
    freq_label = {"D": "일별", "W": "주별", "M": "월별"}[freq]
    agg = trends.aggregate(series, freq)
    if freq == "D":
        df = _dated_df(series, "date", {"원화 단가(원)": "krw"})
        line_chart(df)
    else:
        df = pd.DataFrame({"평균 단가(원)": [a["avg"] for a in agg]}, index=[a["period"] for a in agg])
        st.bar_chart(df)

    if dec:
        st.markdown(f"#### 💱 변동 원인 분해 — {dec['currency']} 단가 × 환율")
        d = st.columns(3)
        d[0].metric("현지 단가 변동", signed_pct(dec["foreign_rate"]),
                    f"{dec['foreign_start']:,.2f} → {dec['foreign_end']:,.2f} {dec['currency']}")
        d[1].metric("환율 변동", signed_pct(dec["fx_rate"]), f"{dec['fx_start']:,.2f} → {dec['fx_end']:,.2f}원")
        d[2].metric("원화 단가 변동", signed_pct(dec["krw_rate"]), f"{dec['total']:+,.0f}원")
        st.caption(f"원화 단가 변동 {dec['total']:+,.0f}원 = 현지 단가 변동 효과 {dec['price_effect']:+,.0f}원 "
                   f"+ 환율 변동 효과 {dec['fx_effect']:+,.0f}원")
        idx = pd.DataFrame(dec["index"])
        idx.index = pd.to_datetime(idx.pop("date"))
        line_chart(idx)
        st.caption("시작일을 100으로 맞춘 지수입니다. 원화 단가(지수) = 현지 단가(지수) × 환율(지수) ÷ 100")
    elif series[-1]["currency"] != "KRW":
        st.caption("기간 중 통화가 바뀌었거나 환율 정보가 없어 현지가/환율 분해는 생략했습니다.")

    with st.expander("일별 데이터 표"):
        st.dataframe(pd.DataFrame([{
            "날짜": r["date"], "원화 단가": round(r["krw"], 2), "통화": r["currency"],
            "외화 단가": r["foreign"], "적용 환율": r["fx"], "환율 기준일": r["fx_date"],
            "단가 적용일": r["price_date"], "변동": "●" if r["changed"] else ""} for r in series]),
            hide_index=True, width="stretch")
    st.download_button("⬇ 이 조회 결과 엑셀 (일별 데이터 + 집계 + 엑셀 그래프)",
                       item_trend_xlsx(names[item_id], KIND_LABEL[kind], series, st_, dec, agg, freq_label),
                       f"가격추이_{names[item_id]}_{rng[0]}_{rng[1]}.xlsx")


def _tab_ranking(pb) -> None:
    kind = st.radio("구분", list(KIND_LABEL), format_func=KIND_LABEL.get, horizontal=True, key="tr_kind2")
    rng = _range("tr_rng2", 365)
    if rng is None:
        return
    names = _names(kind)
    try:
        rows = trends.ranking_table(pb, kind, names, *rng)
    except ValueError as e:
        st.error(str(e))
        return
    if not rows:
        st.info("이 기간에 단가 기록이 있는 품목이 없습니다.")
        return
    up = [r for r in rows if (r["rate"] or 0) > 0]
    down = [r for r in rows if (r["rate"] or 0) < 0]
    m = st.columns(3)
    m[0].metric("상승 품목", f"{len(up)}개")
    m[1].metric("하락 품목", f"{len(down)}개")
    m[2].metric("변동 없음", f"{len(rows) - len(up) - len(down)}개")
    st.markdown("**기간 변동률 (막대)**")
    st.bar_chart(pd.DataFrame({"변동률(%)": [(r["rate"] or 0) * 100 for r in rows]}, index=[r["name"] for r in rows]))
    st.dataframe(pd.DataFrame([{
        "품목": r["name"], "시작일": r["start_date"], "시작 단가": num(r["start"], 1), "종료 단가": num(r["end"], 1),
        "변동액": f"{r['delta']:+,.1f}", "변동률": signed_pct(r["rate"]), "최저": num(r["min"], 1),
        "최고": num(r["max"], 1), "평균": num(r["avg"], 1), "통화": r["currency"],
        "현지가 변동률": signed_pct(r["foreign_rate"]), "환율 변동률": signed_pct(r["fx_rate"]),
        "현지가 효과(원)": "" if r["price_effect"] is None else f"{r['price_effect']:+,.1f}",
        "환율 효과(원)": "" if r["fx_effect"] is None else f"{r['fx_effect']:+,.1f}"} for r in rows]),
        hide_index=True, width="stretch")
    st.download_button("⬇ 변동률 순위 엑셀", ranking_xlsx(rows, KIND_LABEL[kind], *rng),
                       f"변동률_{KIND_LABEL[kind]}_{rng[0]}_{rng[1]}.xlsx")


def _tab_yearly(pb) -> None:
    c = st.columns([1, 3])
    kind = c[0].radio("구분", list(KIND_LABEL), format_func=KIND_LABEL.get, horizontal=True, key="tr_kind3")
    this = date.today().year
    years = c[1].multiselect("연도", list(range(this - 9, this + 1)), default=list(range(max(this - 2, this - 9), this + 1)),
                             key="tr_years")
    if not years:
        return
    names = _names(kind)
    rows = trends.yearly_table(pb, kind, names, sorted(years))
    if not rows:
        st.info("선택한 연도에 해당하는 단가 기록이 없습니다.")
        return
    st.caption("각 연도의 변동률 = 전년 말 단가 대비 해당 연도 말 단가 (올해는 오늘까지). "
               "처음 등록한 해는 '최초 등록가' 기준입니다. 환율이 연동된 수입 품목은 환율 변동이 포함됩니다.")
    ys = sorted({r["year"] for r in rows})
    lookup = {(r["name"], r["year"]): r for r in rows}
    pivot = pd.DataFrame([{"품목": n, **{f"{y}년": signed_pct(lookup[(n, y)]["rate"]) if (n, y) in lookup else ""
                                         for y in ys}} for n in sorted({r["name"] for r in rows})])
    st.markdown("**연도별 변동률**")
    st.dataframe(pivot, hide_index=True, width="stretch")
    one = st.selectbox("연도별 막대그래프로 볼 품목", sorted({r["name"] for r in rows}), key="tr_year_item")
    one_rows = [r for r in rows if r["name"] == one]
    st.bar_chart(pd.DataFrame({"연말 단가(원)": [r["end"] for r in one_rows]}, index=[f"{r['year']}년" for r in one_rows]))
    st.bar_chart(pd.DataFrame({"변동률(%)": [(r["rate"] or 0) * 100 for r in one_rows]},
                              index=[f"{r['year']}년" for r in one_rows]))
    with st.expander("상세 표 (기준 단가·연말 단가·연평균·최저·최고)"):
        st.dataframe(pd.DataFrame([{
            "품목": r["name"], "연도": r["year"], "기준": r["base_label"], "기준 단가": num(r["base"], 1),
            "연말 단가": num(r["end"], 1), "변동액": f"{r['delta']:+,.1f}", "변동률": signed_pct(r["rate"]),
            "연평균": num(r["avg"], 1), "연중 최저": num(r["min"], 1), "연중 최고": num(r["max"], 1),
            "비고": "진행 중" if r["partial"] else ""} for r in rows]), hide_index=True, width="stretch")
    st.download_button("⬇ 연도별 변동 엑셀", yearly_xlsx(rows, KIND_LABEL[kind]), f"연도별변동_{KIND_LABEL[kind]}.xlsx")


def _tab_product(pb) -> None:
    products = db.list_products()
    if not products:
        st.info("등록된 제품이 없습니다.")
        return
    c = st.columns([2, 2, 1])
    pmap = {p["name"]: p["id"] for p in products}
    pname = c[0].selectbox("제품", list(pmap), key="tr_prod")
    chans = {"(기본 설정)": None, **{ch["name"]: ch["id"] for ch in db.list_channels()}}
    cname = c[1].selectbox("판매처", list(chans), key="tr_chan")
    step = c[2].radio("간격", ["일", "주", "월"], index=1, horizontal=True, key="tr_step")
    rng = _range("tr_rng4", 180)
    if rng is None:
        return
    try:
        rows = trends.product_series(db.assemble_quote, db.get_product_detail(pmap[pname]), db.get_settings(),
                                     db.get_channel(chans[cname]) if chans[cname] else None, pb, *rng,
                                     {"일": "D", "주": "W", "월": "M"}[step])
    except ValueError as e:
        st.error(str(e))
        return
    first, last = rows[0], rows[-1]
    d = last["price"] - first["price"]
    m = st.columns(3)
    m[0].metric("시작 납품가", won(first["price"]), help=first["date"])
    m[1].metric("종료 납품가", won(last["price"]), help=last["date"])
    m[2].metric("변동", f"{d:+,.0f}원", signed_pct(d / first["price"] if first["price"] else None))
    st.markdown("**납품가 · 직접원가 추이 (선)**")
    line_chart(_dated_df(rows, "date", {"납품가": "price", "직접원가": "direct_cost", "원가합계": "total_cost"}))
    st.markdown("**원가 구성 변화 (막대, 누적)**")
    st.bar_chart(_dated_df(rows, "date", {"원료(원물가+로스)": "ingredients", "로스팅·선별": "roasting_sorting",
                                          "부자재": "materials", "운송·3PL": "logistics_etc"}))
    st.caption("각 날짜의 단가·환율로 다시 계산한 값입니다 (저장된 견적 이력이 아니라 그 날짜 기준 재계산). "
               "제품 배합·부자재 수량은 현재 설정 그대로입니다.")
    notes = [r for r in rows if r["notes"]]
    if notes:
        st.warning(f"{len(notes)}개 시점에 경고가 있습니다 (예: 단가 기록 이전 날짜). 첫 경고: {notes[0]['date']} — {notes[0]['notes']}")
    with st.expander("표 보기"):
        st.dataframe(pd.DataFrame([{
            "날짜": r["date"], "납품가": num(r["price"]), "원가합계": num(r["total_cost"]), "직접원가": num(r["direct_cost"]),
            "원료": num(r["ingredients"]), "로스팅·선별": num(r["roasting_sorting"]), "부자재": num(r["materials"]),
            "운송·3PL": num(r["logistics_etc"]), "판매처 비용": num(r["channel_cost"]),
            "실질마진율": pct(r["margin_rate"])} for r in rows]), hide_index=True, width="stretch")
    st.download_button("⬇ 제품 원가 추이 엑셀", product_trend_xlsx(pname, rows), f"원가추이_{pname}_{rng[0]}_{rng[1]}.xlsx")


def page_trends() -> None:
    st.header("📈 가격 추이 · 변동률 · 환율 영향")
    st.caption("원료·부자재 가격이 기간 동안 어떻게 변했는지 일별로 보고, 몇 % 올랐는지, 환율 때문인지 현지 가격 때문인지 확인합니다. "
               "모든 화면의 결과는 엑셀로 내려받을 수 있습니다.")
    pb = db.load_pricebook()
    t1, t2, t3, t4 = st.tabs(["📅 품목별 일별 추이", "🏆 기간 변동률 순위", "🗓 연도별 변동", "🥜 제품 원가 추이"])
    with t1:
        _tab_item(pb)
    with t2:
        _tab_ranking(pb)
    with t3:
        _tab_yearly(pb)
    with t4:
        _tab_product(pb)
