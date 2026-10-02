"""납품가 산출 프로그램 (Streamlit). 실행: run.bat  /  streamlit run pricing/app.py"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from pricing import db
from pricing.engine import CATEGORIES, ROUNDING, calculate
from pricing.export import quotes_to_xlsx

st.set_page_config(page_title="납품가 산출", page_icon="🥜", layout="wide")
db.init_db()

CAT_LABEL = CATEGORIES                       # pack -> 포장지
CAT_KEY = {v: k for k, v in CATEGORIES.items()}


# ---------- 공통 ----------
def check_password() -> bool:
    pw = os.environ.get("PRICING_APP_PASSWORD", "")
    if not pw or st.session_state.get("authed"):
        return True
    st.title("🔒 납품가 산출 프로그램")
    entered = st.text_input("비밀번호", type="password")
    if entered and entered == pw:
        st.session_state["authed"] = True
        st.rerun()
    elif entered:
        st.error("비밀번호가 틀렸습니다")
    return False


def won(v: float) -> str:
    return f"{v:,.0f}원"


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def show_result(q, r):
    c = st.columns(4)
    c[0].metric("납품가", won(r.price))
    c[1].metric("원가합계", won(r.total_cost))
    c[2].metric("센터도착가", won(r.center_cost))
    c[3].metric("실질 마진", f"{won(r.effective_margin)} ({pct(r.effective_margin_rate)})")
    for w in r.warnings:
        st.warning(w)

    left, right = st.columns(2)
    with left:
        st.markdown("**원료 (원물가 · 로스)**")
        st.dataframe(pd.DataFrame([{
            "원료": x["name"], "구성비": pct(x["ratio"]), "단위중량(g)": round(x["unit_g"], 2),
            "벌크단가": f'{x["price_per_kg"]:,.0f}', "원물가": f'{x["cost"]:,.1f}',
            "로스율": pct(x["loss_rate"]), "로스": f'{x["loss"]:,.1f}'} for x in r.ingredient_rows]),
            hide_index=True, width="stretch")
        st.markdown("**부자재**")
        st.dataframe(pd.DataFrame([{
            "부자재": x["name"], "분류": CAT_LABEL[x["category"]], "기본": f'{x["base"]:,.1f}',
            "loss": f'{x["loss"]:,.1f}', "합계": f'{x["total"]:,.1f}'} for x in r.material_rows]),
            hide_index=True, width="stretch")
    with right:
        st.markdown("**원가 구성**")
        rows = [("원물가", r.materials_cost), ("선별비", r.sorting_cost), ("로스", r.loss_cost),
                ("포장지", r.pack_cost), ("소분비", r.split_cost), ("박스비", r.box_cost),
                ("운송비", r.shipping_cost), ("직접원가", r.direct_cost),
                (f"판관비 ({pct(q.sga_rate)})", r.sga), (f"마진 ({pct(q.margin_rate)})", r.margin),
                ("센터도착가", r.center_cost),
                (f"물류비 ({pct(q.logistics_rate)}{' · VAT포함 기준' if q.logistics_vat else ''})", r.logistics),
                ("원가합계", r.total_cost), ("납품가", r.price)]
        st.dataframe(pd.DataFrame([{"항목": a, "금액(원)": f"{b:,.1f}"} for a, b in rows]),
                     hide_index=True, width="stretch")
        if q.fixed_price is None:
            st.caption(f"계산 납품가 {r.exact_price:,.2f}원 → {ROUNDING[q.rounding]} → {r.price:,.0f}원")


# ---------- 페이지: 견적 계산 ----------
def page_quote():
    st.header("견적 계산")
    products = db.list_products()
    if not products:
        st.info("먼저 '제품 관리'에서 제품을 등록하세요.")
        return
    names = {p["name"]: p["id"] for p in products}
    sel = st.selectbox("제품", list(names))
    mode = st.radio("계산 방식", ["납품가 자동 계산", "납품가 직접 지정 (손익 확인)"], horizontal=True)
    fixed = None
    if mode.startswith("납품가 직접"):
        fixed = st.number_input("지정 납품가(원)", min_value=0.0, step=10.0, format="%.0f")
    q, r = db.calculate_quote(names[sel], fixed_price=fixed)
    show_result(q, r)

    st.divider()
    c1, c2 = st.columns([1, 2])
    who = c1.text_input("작성자", key="who")
    memo = c2.text_input("메모 (예: 아몬드 단가 인상 반영)")
    b1, b2, b3 = st.columns(3)
    if b1.button("💾 견적 이력에 저장"):
        qid = db.save_quote(q, r, who, memo)
        st.success(f"견적 #{qid} 저장됨 (그 시점의 단가·규칙이 그대로 보존됩니다)")
    b2.download_button("⬇ 원가표 엑셀 (사내용)", quotes_to_xlsx([(q, r)], True),
                       f"원가표_{q.product_name}_{date.today()}.xlsx")
    b3.download_button("⬇ 납품가 엑셀 (거래처용)", quotes_to_xlsx([(q, r)], False),
                       f"납품가_{q.product_name}_{date.today()}.xlsx")

    with st.expander("전체 제품 한눈에 비교"):
        rows, items = [], []
        for p in products:
            qq, rr = db.calculate_quote(p["id"])
            items.append((qq, rr))
            rows.append({"제품": p["name"], "직접원가": round(rr.direct_cost), "원가합계": round(rr.total_cost),
                         "납품가": round(rr.price), "실질마진율": pct(rr.effective_margin_rate)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.download_button("⬇ 전체 제품 원가표 엑셀", quotes_to_xlsx(items, True),
                           f"원가표_전체_{date.today()}.xlsx")


# ---------- 페이지: 제품 관리 ----------
def page_products():
    st.header("제품 관리 (배합표 · 부자재)")
    ings, mats = db.list_ingredients(), db.list_materials()
    if not ings or not mats:
        st.info("먼저 '원료 단가'와 '부자재'를 등록하세요.")
        return
    products = db.list_products()
    pmap = {p["name"]: p["id"] for p in products}
    choice = st.selectbox("제품 선택", ["➕ 새 제품"] + list(pmap))
    pid = pmap.get(choice)
    detail = db.get_product_detail(pid) if pid else {
        "name": "", "bag_count": 1, "unit_weight_g": 20, "sorting_cost_per_kg": 0,
        "shipping_cost": 0, "memo": "", "ingredients": [], "materials": []}

    c = st.columns(5)
    name = c[0].text_input("제품명", detail["name"])
    bags = c[1].number_input("봉수 (30입=30)", min_value=1.0, value=float(detail["bag_count"]), step=1.0)
    uw = c[2].number_input("1봉 중량(g)", min_value=0.0, value=float(detail["unit_weight_g"]), step=1.0)
    sort_c = c[3].number_input("선별단가(원/kg)", min_value=0.0, value=float(detail["sorting_cost_per_kg"]), step=10.0)
    ship = c[4].number_input("운송비(원)", min_value=0.0, value=float(detail["shipping_cost"]), step=10.0)
    memo = st.text_input("메모", detail["memo"] or "")

    iname = {i["id"]: i["name"] for i in ings}
    iid = {v: k for k, v in iname.items()}
    st.markdown("**배합표** — 구성비는 % 로 입력 (합계 100). 로스율·단가를 비워 두면 원료 마스터 값을 씁니다.")
    ing_df = pd.DataFrame([{
        "원료": iname[r["ingredient_id"]], "구성비(%)": r["ratio"] * 100,
        "로스율(%)": None if r["loss_rate"] is None else r["loss_rate"] * 100,
        "단가 직접입력(원/kg)": r["price_override"]} for r in detail["ingredients"]],
        columns=["원료", "구성비(%)", "로스율(%)", "단가 직접입력(원/kg)"])
    ing_ed = st.data_editor(ing_df, num_rows="dynamic", width="stretch", key=f"ing_{pid}",
                            column_config={"원료": st.column_config.SelectboxColumn(options=list(iid), required=True)})

    mname = {m["id"]: m["name"] for m in mats}
    mid = {v: k for k, v in mname.items()}
    st.markdown("**부자재** — 수량(봉수 등), 나누는 수(카톤 입수 등). 금액 = 단가 × 수량 ÷ 나누는 수 × (1+loss)")
    mat_df = pd.DataFrame([{
        "부자재": mname[r["material_id"]], "수량": r["qty"], "나누는 수": r["divisor"],
        "loss(%)": None if r["loss_rate"] is None else r["loss_rate"] * 100} for r in detail["materials"]],
        columns=["부자재", "수량", "나누는 수", "loss(%)"])
    mat_ed = st.data_editor(mat_df, num_rows="dynamic", width="stretch", key=f"mat_{pid}",
                            column_config={"부자재": st.column_config.SelectboxColumn(options=list(mid), required=True)})

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
                     "divisor": 1.0 if pd.isna(r["나누는 수"]) or r["나누는 수"] == 0 else float(r["나누는 수"]),
                     "loss_rate": None if pd.isna(r["loss(%)"]) else float(r["loss(%)"]) / 100}
                    for _, r in mat_ed.dropna(subset=["부자재"]).iterrows()]
        try:
            db.save_product(name.strip(), bags, uw, sort_c, ship, memo, ing_rows, mat_rows, pid)
            st.success("저장되었습니다")
            st.rerun()
        except Exception as e:  # 제품명 중복 등
            st.error(f"저장 실패: {e}")
    if pid and b2.button("🗑 이 제품 삭제"):
        db.delete_product(pid)
        st.rerun()


# ---------- 페이지: 원료 단가 ----------
def page_ingredients():
    st.header("원료 단가 마스터")
    ings = db.list_ingredients()
    if ings:
        df = pd.DataFrame([{
            "원료": i["name"], "최신단가(원/kg)": i["price_per_kg"], "단가 기준일": i["price_date"],
            "원산지": i["origin"], "공급처": i["supplier"],
            "수분loss(%)": i["loss_moisture"] * 100, "소분loss(%)": i["loss_split"] * 100,
            "선별loss(%)": i["loss_sorting"] * 100,
            "loss합계(%)": (i["loss_moisture"] + i["loss_split"] + i["loss_sorting"]) * 100} for i in ings])
        st.dataframe(df, hide_index=True, width="stretch")

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
    lso = st.number_input("선별 loss(%)", 0.0, 100.0, (cur["loss_sorting"] * 100) if cur else 0.0, 0.01)
    b1, b2 = st.columns([1, 6])
    if b1.button("💾 원료 저장") and name.strip():
        db.upsert_ingredient(name.strip(), origin, supplier, lm / 100, ls / 100, lso / 100)
        st.rerun()
    if cur and b2.button("🗑 이 원료 삭제"):
        try:
            db.delete_ingredient(cur["id"])
            st.rerun()
        except Exception:
            st.error("제품 배합표에서 사용 중인 원료는 삭제할 수 없습니다")

    if cur:
        st.subheader(f"'{cur['name']}' 단가 추가 · 이력")
        c = st.columns(4)
        price = c[0].number_input("단가(원/kg)", 0.0, step=100.0, format="%.0f")
        d = c[1].date_input("적용일", date.today())
        pm = c[2].text_input("메모 (공급처 견적 등)")
        if c[3].button("단가 추가"):
            db.add_price(cur["id"], price, d.isoformat(), pm)
            st.rerun()
        hist = db.price_history(cur["id"])
        if hist:
            st.dataframe(pd.DataFrame(hist).rename(columns={
                "effective_date": "적용일", "price_per_kg": "단가(원/kg)", "memo": "메모"}),
                hide_index=True, width="stretch")


# ---------- 페이지: 부자재 ----------
def page_materials():
    st.header("부자재 마스터")
    mats = db.list_materials()
    if mats:
        st.dataframe(pd.DataFrame([{
            "부자재": m["name"], "분류": CAT_LABEL[m["category"]], "단가": m["unit_price"],
            "기본 loss(%)": m["loss_rate"] * 100, "메모": m["memo"]} for m in mats]),
            hide_index=True, width="stretch")
    names = [m["name"] for m in mats]
    pick = st.selectbox("수정할 부자재", ["➕ 새 부자재"] + names)
    cur = next((m for m in mats if m["name"] == pick), None)
    c = st.columns(4)
    name = c[0].text_input("부자재명", cur["name"] if cur else "")
    cats = list(CAT_KEY)
    cat = c[1].selectbox("분류 (원가표의 어느 컬럼에 들어가나)", cats,
                         index=cats.index(CAT_LABEL[cur["category"]]) if cur else 0)
    price = c[2].number_input("단가(원)", 0.0, value=float(cur["unit_price"]) if cur else 0.0, step=1.0)
    loss = c[3].number_input("기본 loss(%)", 0.0, 100.0, (cur["loss_rate"] * 100) if cur else 3.0, 0.1)
    memo = st.text_input("메모", cur["memo"] if cur else "")
    b1, b2 = st.columns([1, 6])
    if b1.button("💾 부자재 저장") and name.strip():
        db.upsert_material(name.strip(), CAT_KEY[cat], price, loss / 100, memo)
        st.rerun()
    if cur and b2.button("🗑 이 부자재 삭제"):
        try:
            db.delete_material(cur["id"])
            st.rerun()
        except Exception:
            st.error("제품에서 사용 중인 부자재는 삭제할 수 없습니다")


# ---------- 페이지: 견적 이력 ----------
def page_history():
    st.header("견적 이력")
    qs = db.list_quotes()
    if not qs:
        st.info("저장된 견적이 없습니다.")
        return
    df = pd.DataFrame(qs).rename(columns={"id": "번호", "created_at": "일시", "created_by": "작성자",
                                          "product_name": "제품", "price": "납품가", "memo": "메모"})
    st.dataframe(df, hide_index=True, width="stretch")
    qid = st.selectbox("상세 볼 견적 번호", [x["id"] for x in qs])
    q, r, row = db.load_quote(qid)
    st.caption(f"{row['created_at']} · {row['created_by']} · {row['memo']}")
    show_result(q, r)
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ 원가표 엑셀", quotes_to_xlsx([(q, r)], True), f"견적{qid}_원가표.xlsx")
    c2.download_button("⬇ 납품가 엑셀", quotes_to_xlsx([(q, r)], False), f"견적{qid}_납품가.xlsx")
    if c3.button("🗑 이 견적 삭제"):
        db.delete_quote(qid)
        st.rerun()


# ---------- 페이지: 설정 ----------
def page_settings():
    st.header("계산 규칙 설정")
    st.caption("판관비·물류비·마진은 모두 '납품가 기준 %' 입니다. 체크를 끄면 계산에서 빠집니다.")
    s = db.get_settings()
    c = st.columns(3)
    use_sga = c[0].checkbox("판관비 사용", s["use_sga"])
    sga = c[0].number_input("판관비율(%)", 0.0, 50.0, s["sga_rate"] * 100, 0.05)
    use_log = c[1].checkbox("물류비 사용", s["use_logistics"])
    log = c[1].number_input("물류비율(%)", 0.0, 50.0, s["logistics_rate"] * 100, 0.01)
    vat = c[1].checkbox("물류비를 VAT 포함 납품가(×1.1) 기준으로 계산", s["logistics_vat"])
    use_mar = c[2].checkbox("마진 사용", s["use_margin"])
    mar = c[2].number_input("마진율(%)", 0.0, 50.0, s["margin_rate"] * 100, 0.05)
    keys = list(ROUNDING)
    rnd = st.selectbox("납품가 반올림", keys, index=keys.index(s["rounding"]), format_func=ROUNDING.get)
    if st.button("💾 설정 저장", type="primary"):
        db.save_settings({"use_sga": use_sga, "sga_rate": sga / 100, "use_logistics": use_log,
                          "logistics_rate": log / 100, "logistics_vat": vat, "use_margin": use_mar,
                          "margin_rate": mar / 100, "rounding": rnd})
        st.success("저장되었습니다")
    st.info("납품가 = 직접원가 ÷ (1 − 판관비% − 마진% − 물류비%[×1.1])  — "
            "납품가를 기준으로 하는 % 항목이라 한 번에 역산합니다.")
    st.caption(f"DB 파일 위치: {db.DB_PATH}")


PAGES = {"견적 계산": page_quote, "제품 관리": page_products, "원료 단가": page_ingredients,
         "부자재": page_materials, "견적 이력": page_history, "설정": page_settings}

if check_password():
    st.sidebar.title("🥜 납품가 산출")
    page = st.sidebar.radio("메뉴", list(PAGES))
    PAGES[page]()
