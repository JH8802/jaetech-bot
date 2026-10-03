"""마스터 화면: 제품 / 원료 단가 / 부자재 / 환율 / 판매처. (Streamlit)"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import db, trends
from .engine import CHANNEL_KINDS
from .export import all_data_xlsx, fx_xlsx
from .ui_common import CAT_KEY, CAT_LABEL, currency_options, line_chart, num, pct, unit_note

PER_BAG_LABEL, FIXED_LABEL = "봉수 연동", "고정"


def _excel_button(label: str, only: list[str], filename: str) -> None:
    st.download_button(label, all_data_xlsx(db.collect_all_data(include_quotes=False), only=only), filename)


# ====================================================================== 제품
def page_products():
    st.header("제품 관리 (배합표 · 부자재)")
    ings, mats = db.list_ingredients(), db.list_materials()
    if not ings or not mats:
        st.info("먼저 '원료 단가'와 '부자재'를 등록하세요. (많으면 '엑셀 일괄 등록'이 편합니다)")
        return
    products = db.list_products()
    pmap = {p["name"]: p["id"] for p in products}
    choice = st.selectbox("제품 선택", ["➕ 새 제품"] + list(pmap))
    pid = pmap.get(choice)
    detail = db.get_product_detail(pid) if pid else {
        "name": "", "bag_count": 1, "unit_weight_g": 20, "sorting_cost_per_kg": 0,
        "shipping_cost": 0, "three_pl_cost": 0, "memo": "", "ingredients": [], "materials": []}

    c = st.columns(6)
    name = c[0].text_input("제품명", detail["name"])
    bags = c[1].number_input("봉수 (30입=30)", min_value=1.0, value=float(detail["bag_count"]), step=1.0,
                             help="봉수 연동 부자재(소포장지·소분비·롤포장지 등)의 수량이 이 값에 맞춰 자동 계산됩니다")
    uw = c[2].number_input("1봉 중량(g)", min_value=0.0, value=float(detail["unit_weight_g"]), step=1.0)
    sort_c = c[3].number_input("공통 선별단가(원/kg)", min_value=0.0, value=float(detail["sorting_cost_per_kg"]),
                               step=10.0, help="제품 전체 중량에 적용. 원료별 선별비는 원료 마스터에서 따로 설정")
    ship = c[4].number_input("운송비(원/개)", min_value=0.0, value=float(detail["shipping_cost"]), step=10.0)
    pl3 = c[5].number_input("3PL 이용료(원/개)", min_value=0.0, value=float(detail.get("three_pl_cost") or 0), step=10.0)
    memo = st.text_input("메모", detail["memo"] or "")

    iname = {i["id"]: i["name"] for i in ings}
    iid = {v: k for k, v in iname.items()}
    st.markdown("**배합표** — 구성비는 % 로 입력 (합계 100). 로스율·단가를 비워 두면 원료 마스터 값(최신 단가·환율 자동 적용)을 씁니다.")
    ing_df = pd.DataFrame([{
        "원료": iname[r["ingredient_id"]], "구성비(%)": r["ratio"] * 100,
        "로스율(%)": None if r["loss_rate"] is None else r["loss_rate"] * 100,
        "단가 직접입력(원/kg)": r["price_override"]} for r in detail["ingredients"]],
        columns=["원료", "구성비(%)", "로스율(%)", "단가 직접입력(원/kg)"])
    ing_ed = st.data_editor(ing_df, num_rows="dynamic", width="stretch", key=f"ing_{pid}",
                            column_config={"원료": st.column_config.SelectboxColumn(options=list(iid), required=True)})

    mname = {m["id"]: m["name"] for m in mats}
    mid = {v: k for k, v in mname.items()}
    st.markdown("**부자재** — 금액 = 단가 × 수량 ÷ 나누는 수 × (1+loss). "
                "**수량 기준**이 '봉수 연동'이면 수량 × 봉수로 계산됩니다 (예: 소분비 1 → 30입이면 30개분). "
                "인케이스·카톤박스처럼 세트당 고정이면 '고정'.")
    mat_df = pd.DataFrame([{
        "부자재": mname[r["material_id"]], "수량": r["qty"],
        "수량 기준": PER_BAG_LABEL if r.get("qty_basis") == "bag" else FIXED_LABEL,
        "나누는 수": r["divisor"],
        "loss(%)": None if r["loss_rate"] is None else r["loss_rate"] * 100} for r in detail["materials"]],
        columns=["부자재", "수량", "수량 기준", "나누는 수", "loss(%)"])
    mat_ed = st.data_editor(mat_df, num_rows="dynamic", width="stretch", key=f"mat_{pid}",
                            column_config={
                                "부자재": st.column_config.SelectboxColumn(options=list(mid), required=True),
                                "수량 기준": st.column_config.SelectboxColumn(options=[FIXED_LABEL, PER_BAG_LABEL],
                                                                           default=FIXED_LABEL)})

    b1, b2 = st.columns([1, 5])
    if b1.button("💾 저장", type="primary"):
        if not name.strip():
            st.error("제품명을 입력하세요")
            return
        ing_rows = [{"ingredient_id": iid[r["원료"]], "ratio": float(r["구성비(%)"]) / 100,
                     "loss_rate": None if pd.isna(r["로스율(%)"]) else float(r["로스율(%)"]) / 100,
                     "price_override": None if pd.isna(r["단가 직접입력(원/kg)"]) else float(r["단가 직접입력(원/kg)"])}
                    for _, r in ing_ed.dropna(subset=["원료", "구성비(%)"]).iterrows()]
        mat_rows = [{"material_id": mid[r["부자재"]],
                     "qty": 1.0 if pd.isna(r["수량"]) else float(r["수량"]),
                     "per_bag": r["수량 기준"] == PER_BAG_LABEL,
                     "divisor": 1.0 if pd.isna(r["나누는 수"]) or r["나누는 수"] == 0 else float(r["나누는 수"]),
                     "loss_rate": None if pd.isna(r["loss(%)"]) else float(r["loss(%)"]) / 100}
                    for _, r in mat_ed.dropna(subset=["부자재"]).iterrows()]
        try:
            db.save_product(name.strip(), bags, uw, sort_c, ship, memo, ing_rows, mat_rows, pid, pl3)
            st.success("저장되었습니다")
            st.rerun()
        except Exception as e:  # 제품명 중복 등
            st.error(f"저장 실패: {e}")
    if pid and b2.button("🗑 이 제품 삭제"):
        db.delete_product(pid)
        st.rerun()

    if pid:
        with st.expander("📑 이 제품을 복사해서 새 제품 만들기 (예: 30입 → 60입)"):
            cc = st.columns(3)
            new_name = cc[0].text_input("새 제품명", f"{detail['name']} 복사", key="copy_name")
            new_bags = cc[1].number_input("새 봉수", min_value=1.0, value=float(detail["bag_count"]), step=1.0,
                                          key="copy_bags")
            if cc[2].button("복사하기"):
                try:
                    db.copy_product(pid, new_name.strip(), new_bags)
                    st.success(f"'{new_name}' 생성 — 봉수 연동 부자재는 새 봉수로 자동 계산됩니다")
                except Exception as e:
                    st.error(f"복사 실패: {e}")
    _excel_button("⬇ 제품·배합표(BOM) 엑셀", ["제품", "제품 구성(BOM)"], f"제품_BOM_{date.today()}.xlsx")


# ====================================================================== 단가 입력 공통
def _price_form(kind: str, item_id: int, unit_label: str, key: str) -> None:
    opts = currency_options(True)
    c = st.columns(4)
    code = opts[c[0].selectbox("통화", list(opts), key=f"{key}_cur")]
    d = c[1].date_input("적용일", date.today(), key=f"{key}_date")
    foreign, mode, fixed, price = None, "auto", None, None
    if code == "KRW":
        price = c[2].number_input(f"단가(원/{unit_label})", 0.0, step=10.0, format="%.2f", key=f"{key}_krw")
    else:
        foreign = c[2].number_input(f"외화 단가 ({code}/{unit_label})", 0.0, step=0.1, format="%.4f", key=f"{key}_for")
        mode_label = c[3].radio("환율 적용", ["자동 (그날의 환율 이력)", "고정환율 직접입력"], key=f"{key}_mode")
        if mode_label.startswith("고정"):
            mode = "fixed"
            fixed = st.number_input(f"고정환율 ({unit_note(code)})", 0.0, step=0.1, format="%.4f", key=f"{key}_fx")
        else:
            found = db.load_pricebook().fx_asof(code, d.isoformat())
            if found is None:
                st.warning(f"{code} 환율 이력이 {d} 이전에 없습니다. '환율' 메뉴에서 먼저 환율을 등록하세요.")
            else:
                st.caption(f"적용될 환율: 1 {code} = {found[0]:,.4f}원 (환율 기준일 {found[1]}) → "
                           f"약 {foreign * found[0]:,.2f}원/{unit_label}. 이후 환율이 바뀌면 원화 단가도 자동으로 따라 바뀝니다.")
    memo = st.text_input("메모 (견적서·공급처 등)", key=f"{key}_memo")
    if st.button("➕ 단가 추가", key=f"{key}_add"):
        try:
            if kind == "ingredient":
                krw = db.add_price(item_id, price, d.isoformat(), memo, code, foreign, mode, fixed)
            else:
                krw = db.add_material_price(item_id, price, d.isoformat(), memo, code, foreign, mode, fixed)
            st.success(f"추가되었습니다 (입력 시점 환산 {krw:,.2f}원)")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def _price_history(kind: str, item_id: int, key: str) -> None:
    hist = db.price_history(item_id) if kind == "ingredient" else db.material_price_history(item_id)
    if not hist:
        st.info("단가 이력이 없습니다.")
        return
    krw_key = "price_per_kg" if kind == "ingredient" else "unit_price"
    pb, today = db.load_pricebook(), date.today().isoformat()
    rows = []
    for h in hist:
        res = pb.resolve({**h, "krw": h[krw_key]}, today)
        foreign = h["foreign_price"] is not None and (h["currency"] or "KRW") != "KRW"
        rows.append({
            "ID": h["id"], "적용일": h["effective_date"], "통화": h["currency"] or "KRW",
            "외화단가": h["foreign_price"] if foreign else None,
            "환율방식": ("고정" if h["fx_mode"] == "fixed" else "자동") if foreign else "",
            "고정환율": h["fx_fixed_rate"], "입력 시 환산(원)": round(h[krw_key], 2),
            "오늘 환율 기준(원)": round(res["krw"], 2), "메모": h["memo"],
            "상태": "적용 예정" if h["effective_date"] > today else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    c = st.columns([2, 1, 1])
    del_id = c[0].selectbox("잘못 입력한 단가 삭제 (ID 선택)", [r["ID"] for r in rows], key=f"{key}_delid")
    sure = c[1].checkbox("삭제 확인", key=f"{key}_delsure")
    if c[2].button("🗑 삭제", key=f"{key}_del", disabled=not sure):
        db.delete_price(del_id) if kind == "ingredient" else db.delete_material_price(del_id)
        db.log_audit("단가 이력 삭제", f"{'원료' if kind == 'ingredient' else '부자재'} 단가 ID {del_id}",
                     st.session_state.get("who", ""))
        st.rerun()


# ====================================================================== 원료
def page_ingredients():
    st.header("원료 단가 마스터")
    ings = db.list_ingredients()
    if ings:
        st.dataframe(pd.DataFrame([{
            "원료": i["name"], "현재단가(원/kg)": num(i["price_per_kg"], 1), "통화": i["currency"],
            "외화단가": num(i["foreign_price"], 2), "적용환율": num(i["fx"], 4), "단가기준일": i["price_date"],
            "로스팅비(원/kg)": num(i["roasting_cost_per_kg"]), "선별비(원/kg)": num(i["sorting_cost_per_kg"]),
            "원산지": i["origin"], "공급처": i["supplier"],
            "loss합계": pct(i["loss_moisture"] + i["loss_split"] + i["loss_sorting"], 2)} for i in ings]),
            hide_index=True, width="stretch")
        _excel_button("⬇ 원료 마스터 + 단가 이력 엑셀 (전체)", ["원료 마스터", "원료 단가이력", "환율 이력"],
                      f"원료_단가_{date.today()}.xlsx")

    st.subheader("원료 등록 / 수정")
    names = [i["name"] for i in ings]
    pick = st.selectbox("수정할 원료 (새 원료는 아래에 이름 입력)", ["➕ 새 원료"] + names)
    cur = next((i for i in ings if i["name"] == pick), None)
    c = st.columns(5)
    name = c[0].text_input("원료명", cur["name"] if cur else "")
    origin = c[1].text_input("원산지", cur["origin"] if cur else "")
    supplier = c[2].text_input("공급처", cur["supplier"] if cur else "")
    lm = c[3].number_input("수분 loss(%)", 0.0, 100.0, (cur["loss_moisture"] * 100) if cur else 0.0, 0.1)
    ls = c[4].number_input("소분 loss(%)", 0.0, 100.0, (cur["loss_split"] * 100) if cur else 0.0, 0.1)
    c2 = st.columns(3)
    lso = c2[0].number_input("선별 loss(%)", 0.0, 100.0, (cur["loss_sorting"] * 100) if cur else 0.0, 0.01)
    roast = c2[1].number_input("로스팅비(원/kg)", 0.0, value=float(cur["roasting_cost_per_kg"] or 0) if cur else 0.0,
                               step=10.0, help="이 원료를 로스팅하는 비용. 벌크단가에 이미 포함돼 있으면 0")
    sortc = c2[2].number_input("선별비(원/kg)", 0.0, value=float(cur["sorting_cost_per_kg"] or 0) if cur else 0.0,
                               step=10.0, help="이 원료의 선별 비용. 벌크단가에 이미 포함돼 있으면 0")
    b1, b2 = st.columns([1, 6])
    if b1.button("💾 원료 저장") and name.strip():
        db.upsert_ingredient(name.strip(), origin, supplier, lm / 100, ls / 100, lso / 100, roast, sortc)
        st.rerun()
    if cur and b2.button("🗑 이 원료 삭제"):
        try:
            db.delete_ingredient(cur["id"])
            st.rerun()
        except Exception:
            st.error("제품 배합표에서 사용 중인 원료는 삭제할 수 없습니다")

    if cur:
        st.subheader(f"'{cur['name']}' 단가 추가 · 이력")
        st.caption("원화로 입력하거나, 수입 원료는 통화(미국/베트남/튀르키예/기타)와 외화 단가로 입력하세요. "
                   "적용일이 미래이면 그 날짜부터 적용됩니다.")
        _price_form("ingredient", cur["id"], "kg", f"ing{cur['id']}")
        _price_history("ingredient", cur["id"], f"ing{cur['id']}")


# ====================================================================== 부자재
def page_materials():
    st.header("부자재 마스터")
    mats = db.list_materials()
    if mats:
        st.dataframe(pd.DataFrame([{
            "부자재": m["name"], "분류": CAT_LABEL[m["category"]], "현재단가(원)": num(m["unit_price"], 2),
            "통화": m["currency"], "외화단가": num(m["foreign_price"], 4), "적용환율": num(m["fx"], 4),
            "단가기준일": m["price_date"], "기본 loss": pct(m["loss_rate"], 2), "메모": m["memo"]} for m in mats]),
            hide_index=True, width="stretch")
        _excel_button("⬇ 부자재 마스터 + 단가 이력 엑셀 (전체)", ["부자재 마스터", "부자재 단가이력", "환율 이력"],
                      f"부자재_단가_{date.today()}.xlsx")
    names = [m["name"] for m in mats]
    pick = st.selectbox("수정할 부자재", ["➕ 새 부자재"] + names)
    cur = next((m for m in mats if m["name"] == pick), None)
    c = st.columns(3)
    name = c[0].text_input("부자재명", cur["name"] if cur else "")
    cats = list(CAT_KEY)
    cat = c[1].selectbox("분류 (원가표의 어느 항목에 들어가나)", cats,
                         index=cats.index(CAT_LABEL[cur["category"]]) if cur else 0)
    loss = c[2].number_input("기본 loss(%)", 0.0, 100.0, (cur["loss_rate"] * 100) if cur else 3.0, 0.1)
    price = None
    if cur is None:
        price = st.number_input("처음 등록할 단가(원) — 외화 단가는 등록 후 아래에서 추가", 0.0, step=1.0)
    memo = st.text_input("메모", cur["memo"] if cur else "")
    b1, b2 = st.columns([1, 6])
    if b1.button("💾 부자재 저장") and name.strip():
        db.upsert_material(name.strip(), CAT_KEY[cat], price if price else None, loss / 100, memo)
        st.rerun()
    if cur and b2.button("🗑 이 부자재 삭제"):
        try:
            db.delete_material(cur["id"])
            st.rerun()
        except Exception:
            st.error("제품에서 사용 중인 부자재는 삭제할 수 없습니다")

    if cur:
        st.subheader(f"'{cur['name']}' 단가 추가 · 이력")
        _price_form("material", cur["id"], "개", f"mat{cur['id']}")
        _price_history("material", cur["id"], f"mat{cur['id']}")


# ====================================================================== 환율
def page_fx():
    st.header("환율 관리 (미국 · 베트남 · 튀르키예 · 기타)")
    st.caption("수입 원료·부자재의 외화 단가를 원화로 환산할 때 쓰는 환율입니다. '자동' 환율 방식의 단가는 "
               "날짜별 환율이 바뀔 때마다 원화 원가가 따라 바뀌어, 환율이 원가에 미친 영향을 볼 수 있습니다.")
    curs = db.list_currencies(include_krw=False)
    pb = db.load_pricebook()
    rows = []
    for cur in curs:
        hist = db.list_fx_rates(cur["code"])
        last, prev = (hist[0] if hist else None), (hist[1] if len(hist) > 1 else None)
        rows.append({
            "통화": db.currency_label(cur), "표기 단위": f"외화 {cur['quote_unit']:g}단위당 원",
            "최근 환율(원)": num(last["rate"], 4) if last else "", "기준일": last["rate_date"] if last else "",
            "직전 대비": (f"{(last['rate'] / prev['rate'] - 1) * 100:+.2f}%" if last and prev else ""),
            "등록 건수": len(hist)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("환율 입력")
    opts = {db.currency_label(c): c["code"] for c in curs}
    c = st.columns(4)
    code = opts[c[0].selectbox("통화", list(opts), key="fx_cur")]
    d = c[1].date_input("기준일", date.today(), key="fx_date")
    rate = c[2].number_input(f"환율 ({unit_note(code)})", 0.0, step=1.0, format="%.4f", key="fx_rate")
    memo = c[3].text_input("메모", key="fx_memo")
    if st.button("💾 환율 저장 (같은 날짜는 덮어씀)"):
        try:
            db.add_fx_rate(code, rate, d.isoformat(), memo)
            st.success("저장되었습니다")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    st.caption("많은 날짜의 환율은 '엑셀 일괄 등록'의 '환율' 시트로 한 번에 올리는 게 편합니다.")

    with st.expander("➕ (기타) 통화 추가 — 미국·베트남·튀르키예 외 다른 나라 (예: EUR 유로, CNY 위안, AUD 호주달러)"):
        e = st.columns(4)
        ncode = e[0].text_input("통화 코드 (영문 2~6자)", key="nc_code", placeholder="EUR")
        nname = e[1].text_input("통화 이름", key="nc_name", placeholder="유로")
        ncountry = e[2].text_input("국가", key="nc_country", placeholder="유럽연합")
        nunit = e[3].number_input("환율 표기 단위", 1.0, step=1.0, key="nc_unit",
                                  help="보통 1. 베트남 동처럼 가치가 작은 통화는 100(100동당 원)")
        if st.button("통화 추가"):
            try:
                db.add_currency(ncode, nname, ncountry, nunit)
                st.success(f"{ncode.upper()} 통화가 추가되었습니다. 위에서 환율을 입력하세요.")
                st.rerun()
            except ValueError as err:
                st.error(str(err))
        custom = [c_ for c_ in curs if not c_["builtin"]]
        if custom:
            dc = st.selectbox("삭제할 (기타) 통화", [c_["code"] for c_ in custom], key="nc_del")
            if st.button("🗑 (기타) 통화 삭제"):
                try:
                    db.delete_currency(dc)
                    st.rerun()
                except ValueError as err:
                    st.error(str(err))

    st.subheader("환율 이력 조회")
    f = st.columns(3)
    sel = f[0].multiselect("통화", list(opts), default=list(opts)[:1], key="fxq_cur")
    rng = f[1].date_input("기간", value=(date.today() - timedelta(days=365), date.today()), key="fxq_rng")
    if not sel or not isinstance(rng, (tuple, list)) or len(rng) != 2:
        return
    d_from, d_to = rng[0].isoformat(), rng[1].isoformat()
    per_cur, names = {}, {}
    for label in sel:
        code = opts[label]
        try:
            per_cur[code] = trends.fx_daily(pb, code, d_from, d_to)
        except ValueError as err:
            st.error(str(err))
            return
        names[code] = label
    chart = {}
    for code, s in per_cur.items():
        chart[code] = pd.Series({r["date"]: r["rate"] for r in s})
    if any(len(s) for s in per_cur.values()):
        df = pd.DataFrame(chart)
        df.index = pd.to_datetime(df.index)
        if len(per_cur) > 1:
            st.caption("통화마다 단위가 달라 선이 겹쳐 보일 수 있어요. 아래 '기간 시작=100 지수'를 함께 보세요.")
        line_chart(df)
        idx = df / df.apply(lambda s_: s_.dropna().iloc[0] if s_.dropna().size else 1) * 100
        if len(per_cur) > 1:
            st.markdown("**기간 시작=100 지수 (통화 간 변동 비교)**")
            line_chart(idx)
        stats = []
        for code, s in per_cur.items():
            if s:
                st_ = trends.period_stats([{"date": r["date"], "krw": r["rate"], "changed": r["changed"]} for r in s])
                stats.append({"통화": code, "시작": num(st_["start"], 4), "종료": num(st_["end"], 4),
                              "변동률": f"{st_['rate'] * 100:+.2f}%", "최저": f"{st_['min']:,.4f} ({st_['min_date']})",
                              "최고": f"{st_['max']:,.4f} ({st_['max_date']})", "평균": num(st_["avg"], 4)})
        st.dataframe(pd.DataFrame(stats), hide_index=True, width="stretch")
        st.download_button("⬇ 환율 일별 데이터 엑셀 (그래프 포함)", fx_xlsx(per_cur, names),
                           f"환율_{d_from}_{d_to}.xlsx")
    else:
        st.info("해당 기간에 환율 데이터가 없습니다.")

    raw = [r for label in sel for r in db.list_fx_rates(opts[label], d_from, d_to)]
    if raw:
        st.markdown("**등록된 환율 (입력한 날짜만)**")
        st.dataframe(pd.DataFrame([{"ID": r["id"], "통화": r["currency"], "기준일": r["rate_date"],
                                    "환율(원)": r["rate"], "메모": r["memo"]} for r in raw]),
                     hide_index=True, width="stretch")
        dd = st.columns([2, 1, 1])
        did = dd[0].selectbox("삭제할 환율 (ID)", [r["id"] for r in raw], key="fx_delid")
        sure = dd[1].checkbox("삭제 확인", key="fx_delsure")
        if dd[2].button("🗑 환율 삭제", disabled=not sure):
            db.delete_fx_rate(did)
            db.log_audit("환율 삭제", f"환율 ID {did}", st.session_state.get("who", ""))
            st.rerun()
    _excel_button("⬇ 환율 이력 전체 엑셀", ["환율 이력", "통화"], f"환율이력_전체_{date.today()}.xlsx")


# ====================================================================== 판매처
def page_channels():
    st.header("판매처 관리 (마트 · 온라인 업체)")
    st.caption("판매처를 고르면 견적에 마트별 물류비, 온라인 업체별 수수료·홍보비·기획전 비용·택배비가 반영됩니다. "
               "모든 % 항목은 납품가 기준이고, '원/개' 항목은 개당 정액입니다. 값을 비워 둔 판관비·마진은 기본 설정을 따릅니다.")
    chans = db.list_channels()
    if chans:
        st.dataframe(pd.DataFrame([{
            "판매처": c["name"], "유형": CHANNEL_KINDS[c["kind"]], "물류비율": pct(c["logistics_rate"], 2),
            "정액 물류비": num(c["logistics_fixed"]), "수수료율": pct(c["fee_rate"], 2),
            "홍보비율": pct(c["promo_rate"], 2), "기획전비율": pct(c["event_rate"], 2),
            "기획전 정액": num(c["event_fixed"]), "택배비": num(c["parcel_cost"]),
            "판관비율": pct(c["sga_rate"], 2) if c["sga_rate"] is not None else "(기본)",
            "마진율": pct(c["margin_rate"], 2) if c["margin_rate"] is not None else "(기본)",
            "메모": c["memo"]} for c in chans]), hide_index=True, width="stretch")
        _excel_button("⬇ 판매처 엑셀", ["판매처"], f"판매처_{date.today()}.xlsx")

    pick = st.selectbox("수정할 판매처", ["➕ 새 판매처"] + [c["name"] for c in chans])
    cur = next((c for c in chans if c["name"] == pick), None)
    g = lambda k, d=0.0: (cur[k] if cur and cur[k] is not None else d)
    kinds = list(CHANNEL_KINDS)
    c = st.columns(3)
    name = c[0].text_input("판매처명 (예: ○○마트, △△몰)", cur["name"] if cur else "")
    kind = c[1].selectbox("유형", kinds, index=kinds.index(cur["kind"]) if cur else 0,
                          format_func=CHANNEL_KINDS.get)
    memo = c[2].text_input("메모", cur["memo"] if cur else "")

    st.markdown("**물류비 (마트별)**")
    l = st.columns(3)
    log_rate = l[0].number_input("물류비율(%)", 0.0, 50.0, g("logistics_rate") * 100, 0.05)
    log_fixed = l[1].number_input("정액 물류비(원/개)", 0.0, value=float(g("logistics_fixed")), step=10.0)
    log_vat = l[2].checkbox("물류비율을 VAT 포함(×1.1) 납품가 기준으로", bool(g("logistics_vat", 0)))

    fee_rate = promo = event = 0.0
    event_fixed = parcel = 0.0
    online_vat = False
    if kind == "online":
        st.markdown("**온라인 업체 비용**")
        o = st.columns(3)
        fee_rate = o[0].number_input("업체 수수료율(%)", 0.0, 60.0, g("fee_rate") * 100, 0.1)
        promo = o[1].number_input("업체 홍보비율(%)", 0.0, 50.0, g("promo_rate") * 100, 0.1)
        event = o[2].number_input("기획전 비용률(%)", 0.0, 50.0, g("event_rate") * 100, 0.1)
        o2 = st.columns(3)
        event_fixed = o2[0].number_input("기획전 정액 비용(원/개)", 0.0, value=float(g("event_fixed")), step=10.0)
        parcel = o2[1].number_input("택배비(원/개)", 0.0, value=float(g("parcel_cost")), step=100.0)
        online_vat = o2[2].checkbox("수수료·홍보비·기획전 %를 VAT 포함(×1.1) 기준으로", bool(g("online_vat", 0)))
    else:
        st.caption("온라인 업체 비용(수수료·홍보비·기획전·택배비)은 유형을 '온라인'으로 바꾸면 입력할 수 있어요.")

    st.markdown("**이 판매처만 다른 판관비·마진을 쓸 때** (체크하지 않으면 '설정'의 기본값)")
    s = st.columns(2)
    use_sga = s[0].checkbox("판관비율 직접 지정", cur is not None and cur["sga_rate"] is not None)
    sga = s[0].number_input("판관비율(%)", 0.0, 50.0, g("sga_rate") * 100, 0.05, disabled=not use_sga)
    use_mar = s[1].checkbox("마진율 직접 지정", cur is not None and cur["margin_rate"] is not None)
    mar = s[1].number_input("마진율(%)", 0.0, 50.0, g("margin_rate") * 100, 0.05, disabled=not use_mar)

    b1, b2 = st.columns([1, 6])
    if b1.button("💾 판매처 저장", type="primary"):
        try:
            db.upsert_channel({
                "name": name, "kind": kind, "logistics_rate": log_rate / 100, "logistics_fixed": log_fixed,
                "logistics_vat": log_vat, "fee_rate": fee_rate / 100, "promo_rate": promo / 100,
                "event_rate": event / 100, "event_fixed": event_fixed, "parcel_cost": parcel,
                "online_vat": online_vat, "sga_rate": sga / 100 if use_sga else None,
                "margin_rate": mar / 100 if use_mar else None, "memo": memo}, cur["id"] if cur else None)
            st.success("저장되었습니다 (이미 저장된 견적 이력은 그 시점 값 그대로 유지됩니다)")
            st.rerun()
        except Exception as e:
            st.error(f"저장 실패: {e}")
    if cur and b2.button("🗑 이 판매처 삭제"):
        db.delete_channel(cur["id"])
        st.rerun()
