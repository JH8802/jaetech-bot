"""납품가 산출 프로그램 (Streamlit). 실행: run.bat  /  streamlit run pricing/app.py"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from pricing import db, importer
from pricing.compare import compare_quotes
from pricing.engine import CHANNEL_KINDS, MODE_AUTO, MODE_FIXED, ROUNDING, calc_mode, calculate
from pricing.export import (all_data_xlsx, compare_to_xlsx, quotes_list_to_xlsx, quotes_to_xlsx)
from pricing.ui_common import pct, show_result, won
from pricing.ui_masters import (page_channels, page_fx, page_ingredients, page_materials,
                                page_products)
from pricing.ui_trends import page_trends

st.set_page_config(page_title="납품가 산출", page_icon="🥜", layout="wide")
db.init_db()

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


# ---------- 페이지: 견적 계산 ----------
def page_quote():
    st.header("견적 계산")
    products = db.list_products()
    if not products:
        st.info("먼저 '제품 관리'에서 제품을 등록하세요.")
        return
    names = {p["name"]: p["id"] for p in products}
    c = st.columns([2, 2, 2])
    sel = c[0].selectbox("제품", list(names))
    chans = {"(기본 설정 · 판매처 미선택)": None,
             **{f"{CHANNEL_KINDS[ch['kind']]} · {ch['name']}": ch["id"] for ch in db.list_channels()}}
    ch_label = c[1].selectbox("판매처", list(chans),
                              help="마트는 물류비, 온라인 업체는 수수료·홍보비·기획전·택배비가 반영됩니다 ('판매처' 메뉴에서 등록)")
    as_of = c[2].date_input("단가·환율 기준일", date.today(),
                            help="이 날짜에 유효한 원료·부자재 단가와 환율로 계산합니다. 과거 날짜를 고르면 그때의 원가를 재현합니다.")
    mode = st.radio("계산 방식", ["납품가 자동 계산", "납품가 직접 지정 (손익 확인)"], horizontal=True)
    fixed = None
    if mode.startswith("납품가 직접"):
        fixed = st.number_input("지정 납품가(원)", min_value=0.0, step=10.0, format="%.0f")
    cid, as_of_s = chans[ch_label], as_of.isoformat()
    q, r = db.calculate_quote(names[sel], fixed_price=fixed, channel_id=cid, as_of=as_of_s)
    show_result(q, r)

    st.divider()
    who = st.session_state.get("who", "").strip()
    memo = st.text_input("메모 (예: 아몬드 단가 인상 반영)")
    b1, b2, b3 = st.columns(3)
    if b1.button("💾 견적 이력에 저장"):
        if not who:
            st.error("왼쪽 사이드바에 '작성자(내 이름)'를 먼저 입력하세요 (누가 만든 견적인지 이력에 남깁니다)")
        else:
            qid = db.save_quote(q, r, who, memo)
            st.success(f"견적 #{qid} 저장됨 — 작성자 {who} · {calc_mode(q)} · 기준일 {as_of_s} "
                       "(그 시점의 단가·환율·규칙이 그대로 보존됩니다)")
    b2.download_button("⬇ 원가표 엑셀 (사내용)", quotes_to_xlsx([(q, r)], True),
                       f"원가표_{q.product_name}_{date.today()}.xlsx")
    b3.download_button("⬇ 납품가 엑셀 (거래처용)", quotes_to_xlsx([(q, r)], False),
                       f"납품가_{q.product_name}_{date.today()}.xlsx")

    with st.expander("전체 제품 한눈에 비교 (같은 판매처·기준일)"):
        rows, items = [], []
        pb = db.load_pricebook()
        settings = db.get_settings()
        channel = db.get_channel(cid) if cid else None
        for p in products:
            qq = db.assemble_quote(db.get_product_detail(p["id"]), settings, channel, pb, as_of_s)
            rr = calculate(qq)
            items.append((qq, rr))
            rows.append({"제품": p["name"], "직접원가": round(rr.direct_cost), "원가합계": round(rr.total_cost),
                         "납품가": round(rr.price), "실질마진율": pct(rr.effective_margin_rate)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.download_button("⬇ 전체 제품 원가표 엑셀", quotes_to_xlsx(items, True),
                           f"원가표_전체_{date.today()}.xlsx")


# ---------- 페이지: 견적 이력 ----------
def _quote_label(item) -> str:
    q, r, m = item
    return f"#{m['id']} · {m['created_at']} · {q.product_name} · {r.price:,.0f}원 · {m['created_by'] or '-'} · {m['mode']}"


def _fmt_num(v, rate=False):
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return f"{v * 100:.1f}%" if rate else f"{v:,.1f}"


def _show_compare(a, b):
    c = compare_quotes(a, b)
    if not c["same_product"]:
        st.warning("서로 다른 제품의 견적입니다. 제품이 같을 때 비교가 가장 의미 있어요.")
    st.subheader(c["headline"])
    st.caption(f"A(기준) #{c['meta_a']['id']} {c['meta_a']['created_at']} [{c['meta_a']['mode']}]  →  "
               f"B(비교) #{c['meta_b']['id']} {c['meta_b']['created_at']} [{c['meta_b']['mode']}]")
    if c["drivers"]:
        st.markdown("**직접원가 변동 요인 (영향 큰 순)**")
        for i, t in enumerate(c["drivers"][:8], 1):
            st.markdown(f"{i}. {t}")
    else:
        st.info("원가 구성에 차이가 없습니다.")

    st.markdown("**항목별 비교**")
    rows = []
    for r in c["summary"]:
        rate = r["항목"] == "실질 마진율"
        rows.append({"항목": r["항목"], "A": _fmt_num(r["A"], rate), "B": _fmt_num(r["B"], rate),
                     "차이": (f"{r['차이'] * 100:+.1f}%p" if rate else f"{r['차이']:+,.1f}"),
                     "차이%": "" if r["차이%"] is None else f"{r['차이%'] * 100:+.1f}%"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.markdown("**원료별 비교**")
    ing = pd.DataFrame(c["ingredients"])
    if len(ing):
        view = pd.DataFrame({
            "원료": ing["원료"], "상태": ing["상태"],
            "구성비 A": ing["구성비 A"].map(lambda v: _fmt_num(v, True)),
            "구성비 B": ing["구성비 B"].map(lambda v: _fmt_num(v, True)),
            "단가 A": ing["단가 A"].map(_fmt_num), "단가 B": ing["단가 B"].map(_fmt_num),
            "단가기준일 A": ing["단가기준일 A"], "단가기준일 B": ing["단가기준일 B"],
            "통화 A": ing["통화 A"], "외화단가 A": ing["외화단가 A"].map(lambda v: _fmt_num(v)),
            "환율 A": ing["환율 A"].map(lambda v: "" if v is None or pd.isna(v) else f"{v:,.2f}"),
            "통화 B": ing["통화 B"], "외화단가 B": ing["외화단가 B"].map(lambda v: _fmt_num(v)),
            "환율 B": ing["환율 B"].map(lambda v: "" if v is None or pd.isna(v) else f"{v:,.2f}"),
            "원료비 A": ing["원료비 A"].map(_fmt_num), "원료비 B": ing["원료비 B"].map(_fmt_num),
            "차이": ing["차이"].map(lambda v: f"{v:+,.1f}")})
        st.dataframe(view, hide_index=True, width="stretch")
    st.markdown("**부자재별 비교**")
    mat = pd.DataFrame(c["materials"])
    if len(mat):
        st.dataframe(pd.DataFrame({"부자재": mat["부자재"], "분류": mat["분류"], "상태": mat["상태"],
                                   "A": mat["A"].map(_fmt_num), "B": mat["B"].map(_fmt_num),
                                   "차이": mat["차이"].map(lambda v: f"{v:+,.1f}")}),
                     hide_index=True, width="stretch")
    st.markdown("**적용 규칙 비교** (● = 서로 다름)")
    st.dataframe(pd.DataFrame(c["rules"]), hide_index=True, width="stretch")
    st.download_button("⬇ 비교 결과 엑셀", compare_to_xlsx(c),
                       f"견적비교_{c['meta_a']['id']}_vs_{c['meta_b']['id']}.xlsx")


def page_history():
    st.header("견적 이력")
    opts = db.quote_filter_options()
    if not opts["products"]:
        st.info("저장된 견적이 없습니다. '견적 계산' 화면에서 '견적 이력에 저장'을 누르면 쌓입니다.")
        return
    tab_list, tab_cmp, tab_log = st.tabs(["📋 목록 · 상세", "⚖ 두 견적 비교", "🗂 삭제·권한 기록"])
    who = st.session_state.get("who", "").strip()

    with tab_list:
        today = date.today()
        f = st.columns([2, 2, 2, 2])
        rng = f[0].date_input("기간", value=(today - timedelta(days=90), today))
        sel_prod = f[1].multiselect("제품", opts["products"])
        sel_user = f[2].multiselect("작성자", opts["users"])
        sel_mode = f[3].multiselect("계산 방식", [MODE_AUTO, MODE_FIXED])
        d_from = d_to = None
        if isinstance(rng, (tuple, list)):
            d_from = rng[0].isoformat() if len(rng) > 0 else None
            d_to = rng[1].isoformat() if len(rng) > 1 else None
        items = db.search_quotes(d_from, d_to, sel_prod or None, sel_user or None, sel_mode or None)
        if not items:
            st.info("조건에 맞는 견적이 없습니다. 기간을 넓혀 보세요.")
        else:
            st.dataframe(pd.DataFrame([{
                "번호": m["id"], "일시": m["created_at"], "작성자": m["created_by"], "제품": q.product_name,
                "계산방식": m["mode"], "원가합계": round(r.total_cost), "납품가": round(r.price),
                "실질마진율": pct(r.effective_margin_rate), "경고": "⚠" if r.warnings else "",
                "메모": m["memo"]} for q, r, m in items]), hide_index=True, width="stretch")
            st.download_button(f"⬇ 이력 목록 전체 엑셀 ({len(items)}건 · 원료/부자재 상세 포함)",
                               quotes_list_to_xlsx(items), f"견적이력_{today}.xlsx")

            st.divider()
            item = st.selectbox("상세 볼 견적", items, format_func=_quote_label)
            q, r, m = item
            st.caption(f"견적 #{m['id']} · {m['created_at']} · 작성자 {m['created_by'] or '-'} · 메모: {m['memo'] or '-'}")
            show_result(q, r)
            c1, c2, c3 = st.columns(3)
            c1.download_button("⬇ 원가표 엑셀 (사내용)", quotes_to_xlsx([(q, r, m)], True), f"견적{m['id']}_원가표.xlsx")
            c2.download_button("⬇ 납품가 엑셀 (거래처용)", quotes_to_xlsx([(q, r, m)], False), f"견적{m['id']}_납품가.xlsx")
            with c3:
                if not db.get_settings()["allow_quote_delete"]:
                    st.button("🔒 삭제 잠금 상태", disabled=True,
                              help="설정 메뉴의 '견적 이력 보호'에서 허용해야 삭제할 수 있습니다")
                else:
                    sure = st.checkbox("정말 삭제합니다", key=f"sure_{m['id']}")
                    if st.button("🗑 이 견적 삭제", disabled=not sure):
                        if not who:
                            st.error("사이드바에 작성자(내 이름)를 입력하세요 (삭제 기록에 남습니다)")
                        else:
                            db.delete_quote(m["id"], user=who)
                            st.rerun()

    with tab_cmp:
        allq = db.search_quotes(limit=300)
        if len(allq) < 2:
            st.info("비교하려면 저장된 견적이 2건 이상 필요합니다.")
        else:
            st.caption("A = 기준(예: 지난달 견적), B = 비교 대상(예: 이번 달 견적). 같은 제품끼리 비교하면 가장 유용합니다.")
            ca, cb = st.columns(2)
            a = ca.selectbox("A (기준)", allq, index=1, format_func=_quote_label, key="cmp_a")
            b = cb.selectbox("B (비교 대상)", allq, index=0, format_func=_quote_label, key="cmp_b")
            if a[2]["id"] == b[2]["id"]:
                st.warning("서로 다른 견적을 선택하세요.")
            else:
                _show_compare(a, b)

    with tab_log:
        st.caption("견적 삭제와 '삭제 허용' 설정 변경 기록입니다. (삭제된 견적의 제품·납품가·작성자가 남습니다)")
        log = db.list_audit()
        if log:
            st.dataframe(pd.DataFrame(log).rename(columns={"at": "일시", "user": "실행자", "action": "작업",
                                                           "detail": "내용"}), hide_index=True, width="stretch")
        else:
            st.info("기록이 없습니다.")


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

    st.divider()
    st.subheader("견적 이력 보호")
    st.caption("기본은 '삭제 잠금'입니다. 잠겨 있으면 견적 이력을 지울 수 없고, 허용 후 삭제하면 삭제 기록이 남습니다.")
    allow = st.checkbox("견적 이력 삭제 허용", s["allow_quote_delete"])
    admin_env = os.environ.get("PRICING_ADMIN_PASSWORD", "")
    admin_in = st.text_input("관리자 비밀번호", type="password") if admin_env else ""
    if st.button("🔐 보호 설정 저장"):
        if allow == s["allow_quote_delete"]:
            st.info("변경된 내용이 없습니다")
        elif admin_env and admin_in != admin_env:
            st.error("관리자 비밀번호가 틀렸습니다")
        else:
            db.save_settings({"allow_quote_delete": allow})
            db.log_audit("삭제 허용 설정 변경", "허용" if allow else "잠금", st.session_state.get("who", ""))
            st.success("저장되었습니다")
    if not admin_env:
        st.caption("⚠ 관리자 비밀번호(PRICING_ADMIN_PASSWORD)가 설정되어 있지 않아 누구나 이 잠금을 풀 수 있습니다. "
                   "여러 명이 쓸 때는 run_shared.bat 실행 시 관리자 비밀번호를 입력하세요.")
    st.divider()
    st.subheader("전체 데이터 엑셀 내보내기 (백업 · 외부 분석)")
    st.caption("원료·부자재 마스터와 단가 이력, 환율 이력, 판매처, 제품 구성(BOM), 견적 이력 요약을 한 파일로 내려받습니다.")
    if st.button("📦 전체 데이터 엑셀 만들기"):
        st.session_state["all_xlsx"] = all_data_xlsx(db.collect_all_data())
    if "all_xlsx" in st.session_state:
        st.download_button("⬇ 전체 데이터 엑셀 받기", st.session_state["all_xlsx"], f"전체데이터_{date.today()}.xlsx")
    st.caption(f"DB 파일 위치: {db.DB_PATH} (이 파일 하나를 복사해 두면 모든 데이터가 백업됩니다)")


# ---------- 페이지: 엑셀 일괄 등록 ----------
def page_bulk():
    st.header("엑셀 일괄 등록 (원료 · 부자재 · 환율)")
    st.caption("회사에서 쓰는 원료 단가표 · 부자재 목록 · 일별 환율을 엑셀로 한 번에 올립니다. "
               "이름이 같으면 수정, 없으면 신규 등록이고, 빈 칸은 기존 값을 유지합니다. "
               "수입 품목은 통화와 외화 단가로 올리면 환율로 자동 환산됩니다.")

    c1, c2 = st.columns(2)
    c1.download_button("⬇ 빈 양식 받기 (.xlsx)", importer.build_workbook(), "원료_부자재_등록양식.xlsx",
                       help="원료 / 부자재 / 환율 시트가 있는 양식입니다. 작성방법 시트를 참고하세요.")
    c2.download_button("⬇ 현재 등록된 마스터 내보내기", importer.build_workbook(
        db.list_ingredients(), db.list_materials(), sorted(db.list_fx_rates(), key=lambda r: (r["currency"], r["rate_date"]))),
        f"마스터_{date.today()}.xlsx",
        help="내보낸 파일을 엑셀에서 고쳐서 다시 올리면 일괄 수정할 수 있습니다.")

    up = st.file_uploader("엑셀 파일 선택 (.xlsx / .xls / .csv)", type=["xlsx", "xls", "csv"])
    if up is None:
        st.info("양식에 맞춰 작성한 파일을 올리면 '미리보기'가 나오고, 확인 후 등록할 수 있습니다. "
                "기존에 쓰던 단가표도 헤더가 '원료명, 단가(원/kg)…'처럼 비슷하면 그대로 읽습니다.")
        return

    parsed = importer.parse_file(up.getvalue(), up.name)
    for n in parsed.notes:
        st.caption("• " + n)

    if parsed.errors:
        st.error(f"오류 {len(parsed.errors)}건 — 아래를 고친 뒤 다시 올려주세요. (오류가 있으면 아무것도 등록되지 않습니다)")
        st.dataframe(pd.DataFrame({"오류 내용": parsed.errors}), hide_index=True, width="stretch")
        return
    for w in parsed.warnings:
        st.warning(w)

    results = db.bulk_apply(parsed.ingredients, parsed.materials, parsed.fx_rates, dry_run=True)   # 미리보기 (DB 변경 없음)
    df = pd.DataFrame(results)
    errs = df[df["status"] == "오류"]
    cnt = df["status"].value_counts()
    m = st.columns(4)
    m[0].metric("신규", int(cnt.get("신규", 0)))
    m[1].metric("수정", int(cnt.get("수정", 0)))
    m[2].metric("변경없음", int(cnt.get("변경없음", 0)))
    m[3].metric("오류", int(cnt.get("오류", 0)))

    show = st.multiselect("보기 필터", ["신규", "수정", "변경없음", "오류"], default=["신규", "수정", "오류"])
    view = df[df["status"].isin(show)][["kind", "name", "status", "detail", "src"]].rename(columns={
        "kind": "구분", "name": "이름", "status": "상태", "detail": "내용", "src": "파일 위치"})
    st.dataframe(view, hide_index=True, width="stretch")

    if len(errs):
        st.error("등록할 수 없는 행이 있습니다. 파일을 고쳐서 다시 올려주세요.")
        return
    if cnt.get("신규", 0) + cnt.get("수정", 0) == 0:
        st.info("바뀌는 내용이 없습니다 (이미 모두 등록되어 있어요).")
        return
    if st.button("✅ 이 내용으로 등록 실행", type="primary"):
        done = db.bulk_apply(parsed.ingredients, parsed.materials, parsed.fx_rates)
        if any(r["status"] == "오류" for r in done):
            st.error("등록 중 오류가 발생해 전체 취소되었습니다.")
        else:
            st.success(f"등록 완료 — 신규 {sum(r['status'] == '신규' for r in done)}건, "
                       f"수정 {sum(r['status'] == '수정' for r in done)}건. "
                       "다음은 '제품 관리'에서 배합표를 만들거나 '가격 추이'에서 변동을 확인하세요.")
            st.balloons()


PAGES = {"견적 계산": page_quote, "제품 관리": page_products, "원료 단가": page_ingredients,
         "부자재": page_materials, "환율": page_fx, "판매처": page_channels, "가격 추이": page_trends,
         "엑셀 일괄 등록": page_bulk, "견적 이력": page_history, "설정": page_settings}

if check_password():
    st.sidebar.title("🥜 납품가 산출")
    st.sidebar.text_input("작성자 (내 이름)", key="who", help="견적 저장·삭제 기록에 남는 이름입니다")
    page = st.sidebar.radio("메뉴", list(PAGES))
    PAGES[page]()
