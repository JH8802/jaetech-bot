"""마스터 화면: 제품 / 원료 단가 / 부자재 / 환율 / 판매처. (Streamlit)

화면의 (?) 아이콘에 마우스를 올리면 그 항목의 설명이 나옵니다.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import db, trends
from .engine import CHANNEL_KINDS
from .export import all_data_xlsx, fx_xlsx
from .ui_common import CAT_KEY, CAT_LABEL, line_chart, num, pct, unit_note

PER_BAG_LABEL, FIXED_LABEL = "봉수 연동", "고정"
NO_FX = "해당 없음 (원화 ₩)"
NEW_FX = "(기타) 새 통화 직접 입력"
MODE_FIXED_LABEL = "입력한 환율로 고정 (이 단가를 받은 당시 환율)"
MODE_AUTO_LABEL = "환율 메뉴의 일별 환율을 따라감 (자동)"

FX_ENTRY_HELP = (
    "수입 원료·부자재는 통화를 고르고 외화 단가와 환율을 입력하세요. 여기 입력하는 환율은 '이 단가를 받은 당시의 환율'로, "
    "단가마다 따로 기록됩니다. (왼쪽 '환율' 메뉴는 매일의 시세를 쌓아 두는 곳이라 목적이 다릅니다.) "
    "미국/베트남/튀르키예 외 나라는 '(기타) 새 통화 직접 입력'을 고르세요.")
FX_MASTER_VS_ENTRY = (
    "【환율 메뉴】 날짜별 시세 기록 — 환율 조회·그래프, 그리고 '자동' 방식 단가를 매일 원화로 환산할 때 사용합니다.\n"
    "【원료·부자재 입력의 환율】 그 단가를 받은 당시의 거래 환율 — 기본은 '고정'이라 나중에 시세가 바뀌어도 이 단가의 원화 값은 변하지 않습니다.")


def _md(text: str) -> str:
    """st.markdown/caption 은 $...$ 를 수식으로 해석하므로 통화 기호 $ 는 이스케이프한다."""
    return text.replace("$", "\\$")


def _excel_button(label: str, only: list[str], filename: str) -> None:
    st.download_button(label, all_data_xlsx(db.collect_all_data(include_quotes=False), only=only), filename,
                       help="화면에 보이는 마스터와 이력 데이터를 엑셀 파일로 저장합니다.")


def _flash(msg: str | None = None):
    """저장 후 화면이 새로고침되어도 성공 메시지가 보이도록 한 번 보관했다가 보여 준다."""
    if msg:
        st.session_state["_flash"] = msg
    elif "_flash" in st.session_state:
        st.success(st.session_state.pop("_flash"))


def _bump(name: str) -> int:
    st.session_state[name] = st.session_state.get(name, 0) + 1
    return st.session_state[name]


# ====================================================================== 제품
def page_products():
    st.header("제품 관리 (배합표 · 부자재)",
              help="제품 하나를 이루는 원료 배합과 부자재를 등록합니다. 여기서 만든 제품으로 '견적 계산'을 합니다.")
    _flash()
    ings, mats = db.list_ingredients(), db.list_materials()
    if not ings or not mats:
        st.info("먼저 '원료 단가'와 '부자재'를 등록하세요. (많으면 '엑셀 일괄 등록'이 편합니다)")
        return
    products = db.list_products()
    pmap = {p["name"]: p["id"] for p in products}
    choice = st.selectbox("제품 선택", ["➕ 새 제품"] + list(pmap), help="수정할 제품을 고르거나 '새 제품'을 선택해 새로 만듭니다.")
    pid = pmap.get(choice)
    detail = db.get_product_detail(pid) if pid else {
        "name": "", "bag_count": 1, "unit_weight_g": 20, "sorting_cost_per_kg": 0,
        "shipping_cost": 0, "three_pl_cost": 0, "memo": "", "ingredients": [], "materials": []}

    c = st.columns(6)
    name = c[0].text_input("제품명", detail["name"], help="견적서·이력에 표시되는 이름입니다. 제품마다 달라야 합니다.")
    bags = c[1].number_input("봉수 (30입=30)", min_value=1.0, value=float(detail["bag_count"]), step=1.0,
                             help="한 세트에 들어가는 낱개(봉) 수. '봉수 연동' 부자재(소포장지·소분비·롤포장지 등)의 수량이 이 값에 맞춰 자동 계산됩니다.")
    uw = c[2].number_input("1봉 중량(g)", min_value=0.0, value=float(detail["unit_weight_g"]), step=1.0,
                           help="낱개 1봉의 내용물 중량. 원료별 사용량 = 1봉 중량 × 구성비 × 봉수.")
    sort_c = c[3].number_input("공통 선별단가(원/kg)", min_value=0.0, value=float(detail["sorting_cost_per_kg"]),
                               step=10.0, help="제품 전체 중량에 한꺼번에 적용하는 선별 비용. 원료마다 다른 선별비는 '원료 단가' 메뉴에서 원료별로 입력합니다.")
    ship = c[4].number_input("운송비(원/개)", min_value=0.0, value=float(detail["shipping_cost"]), step=10.0,
                             help="제조사에서 물류센터까지 1세트당 운송 비용.")
    pl3 = c[5].number_input("3PL 이용료(원/개)", min_value=0.0, value=float(detail.get("three_pl_cost") or 0), step=10.0,
                            help="3PL(위탁 물류) 업체에 내는 보관·입출고 비용, 1세트당 금액.")
    memo = st.text_input("메모", detail["memo"] or "", help="자유 메모 (예: 규격, 거래처 요청 사항)")

    iname = {i["id"]: i["name"] for i in ings}
    iid = {v: k for k, v in iname.items()}
    st.markdown("**배합표**", help="구성비는 % 로 입력하고 합계가 100이 되게 하세요. 로스율·단가를 비워 두면 원료 마스터 값(최신 단가·환율 자동 적용)을 씁니다. "
                                "'단가 직접입력'을 쓰면 이 제품에서만 그 단가(원/kg)를 사용합니다.")
    ing_df = pd.DataFrame([{
        "원료": iname[r["ingredient_id"]], "구성비(%)": r["ratio"] * 100,
        "로스율(%)": None if r["loss_rate"] is None else r["loss_rate"] * 100,
        "단가 직접입력(원/kg)": r["price_override"]} for r in detail["ingredients"]],
        columns=["원료", "구성비(%)", "로스율(%)", "단가 직접입력(원/kg)"])
    ing_ed = st.data_editor(ing_df, num_rows="dynamic", width="stretch", key=f"ing_{pid}",
                            column_config={"원료": st.column_config.SelectboxColumn(options=list(iid), required=True),
                                           "구성비(%)": st.column_config.NumberColumn(help="이 원료가 차지하는 비율 (전체 합 100)"),
                                           "로스율(%)": st.column_config.NumberColumn(help="비우면 원료 마스터의 loss 합계 사용"),
                                           "단가 직접입력(원/kg)": st.column_config.NumberColumn(help="비우면 원료 마스터의 기준일 단가 사용")})

    mname = {m["id"]: m["name"] for m in mats}
    mid = {v: k for k, v in mname.items()}
    st.markdown("**부자재**", help="금액 = 단가 × 수량 ÷ 나누는 수 × (1+loss).\n"
                                "• 수량 기준 '봉수 연동' = 수량 × 봉수 (예: 소분비 1 → 30입이면 30개분)\n"
                                "• '고정' = 세트당 정해진 수량 (인케이스·카톤박스 등)\n"
                                "• 나누는 수 = 카톤박스 입수처럼 여러 세트가 함께 쓰는 경우 (8입 카톤이면 8)")
    mat_df = pd.DataFrame([{
        "부자재": mname[r["material_id"]], "수량": r["qty"],
        "수량 기준": PER_BAG_LABEL if r.get("qty_basis") == "bag" else FIXED_LABEL,
        "나누는 수": r["divisor"],
        "loss(%)": None if r["loss_rate"] is None else r["loss_rate"] * 100} for r in detail["materials"]],
        columns=["부자재", "수량", "수량 기준", "나누는 수", "loss(%)"])
    mat_ed = st.data_editor(mat_df, num_rows="dynamic", width="stretch", key=f"mat_{pid}",
                            column_config={
                                "부자재": st.column_config.SelectboxColumn(options=list(mid), required=True),
                                "수량": st.column_config.NumberColumn(help="'봉수 연동'이면 봉수 1개당 수량, '고정'이면 세트당 수량"),
                                "수량 기준": st.column_config.SelectboxColumn(
                                    options=[FIXED_LABEL, PER_BAG_LABEL], default=FIXED_LABEL,
                                    help="봉수 연동 = 수량×봉수 / 고정 = 세트당 고정 수량"),
                                "나누는 수": st.column_config.NumberColumn(help="카톤 입수 등. 1이면 나누지 않음"),
                                "loss(%)": st.column_config.NumberColumn(help="비우면 부자재 마스터의 기본 loss 사용")})

    b1, b2 = st.columns([1, 5])
    if b1.button("💾 저장", type="primary", help="제품·배합표·부자재를 저장합니다."):
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
    if pid and b2.button("🗑 이 제품 삭제", help="제품과 배합표를 삭제합니다. 이미 저장된 견적 이력은 그대로 남습니다."):
        db.delete_product(pid)
        st.rerun()

    if pid:
        with st.expander("📑 이 제품을 복사해서 새 제품 만들기 (예: 30입 → 60입)"):
            cc = st.columns(3)
            new_name = cc[0].text_input("새 제품명", f"{detail['name']} 복사", key="copy_name")
            new_bags = cc[1].number_input("새 봉수", min_value=1.0, value=float(detail["bag_count"]), step=1.0,
                                          key="copy_bags", help="봉수 연동 부자재는 이 봉수에 맞춰 수량이 자동으로 바뀝니다.")
            if cc[2].button("복사하기"):
                try:
                    db.copy_product(pid, new_name.strip(), new_bags)
                    st.success(f"'{new_name}' 생성 — 봉수 연동 부자재는 새 봉수로 자동 계산됩니다")
                except Exception as e:
                    st.error(f"복사 실패: {e}")
    _excel_button("⬇ 제품·배합표(BOM) 엑셀", ["제품", "제품 구성(BOM)"], f"제품_BOM_{date.today()}.xlsx")


# ====================================================================== 단가 입력 공통 (원료·부자재)
def _fx_options():
    curs = db.list_currencies(include_krw=False)
    opts = {NO_FX: "KRW"}
    opts.update({db.currency_label(c): c["code"] for c in curs})
    opts[NEW_FX] = "__NEW__"
    return opts, {c["code"]: c for c in curs}


def _initial_fx_label(cur: dict | None, opts: dict) -> str:
    code = cur["currency"] if cur and cur.get("price_date") and cur.get("foreign_price") is not None else "KRW"
    return next((l for l, c in opts.items() if c == code), NO_FX)


def _krw_input(col, prefix: str, label: str, cur: dict | None, price_key: str, step: float, opts: dict):
    """기본 단가(원) 입력칸. 외화를 선택하면 '외화 단가 × 환율'로 자동 계산되므로 입력이 잠긴다."""
    sel = st.session_state.get(f"{prefix}_fxsel", _initial_fx_label(cur, opts))
    if sel != NO_FX:
        col.text_input(label, "↓ 아래 외화 단가 × 환율로 자동 계산", disabled=True, key=f"{prefix}_krw_off",
                       help="외화(수입) 단가를 선택했기 때문에 원화 단가는 자동 계산됩니다. 원화로 직접 입력하려면 환율을 '해당 없음'으로 바꾸세요.")
        return None
    default = float(cur[price_key]) if cur and cur.get(price_key) is not None and cur.get("currency") == "KRW" else 0.0
    return col.number_input(label, 0.0, value=default, step=step, format="%.2f", key=f"{prefix}_krw",
                            help="원화로 받은 기본 단가입니다. 수입품이라면 이 칸 대신 아래에서 환율(통화)을 고르세요.")


def _fx_block(prefix: str, unit: str, cur: dict | None, price_key: str, opts: dict, curs: dict) -> dict:
    """적용일 · 환율(통화) 선택 · 외화 단가 · 환율 직접 입력. 입력값을 spec 으로 돌려준다."""
    c = st.columns([1, 2, 2])
    d = c[0].date_input("단가 적용일", date.today(), key=f"{prefix}_date",
                        help="이 단가가 유효해지는 날짜입니다. 가격 추이·변동률은 이 날짜로 기록되고, 미래 날짜면 그날부터 견적에 적용됩니다.")
    sel = c[1].selectbox("환율 (수입 시 통화 선택)", list(opts),
                         index=list(opts).index(_initial_fx_label(cur, opts)), key=f"{prefix}_fxsel", help=FX_ENTRY_HELP)
    code = opts[sel]
    spec = {"date": d.isoformat(), "currency": "KRW", "foreign": None, "mode": "auto", "fixed": None,
            "new_currency": None, "error": None, "krw_preview": None}
    if code == "KRW":
        c[2].caption("원화 단가를 그대로 사용합니다. 수입품이면 왼쪽 '환율'에서 통화를 고르세요.")
        return spec

    symbol, qunit = "", 1.0
    ksuf = "new" if code == "__NEW__" else code        # 통화 코드를 나중에 입력해도 이미 입력한 값이 사라지지 않게 고정 키
    if code == "__NEW__":
        n = st.columns(5)
        ncode = n[0].text_input("통화 코드 (영문 2~6자)", key=f"{prefix}_nc_code", placeholder="EUR",
                                help="국제 표준 통화 코드. 예: EUR(유로), CNY(위안), AUD(호주달러), JPY(엔)")
        nname = n[1].text_input("통화 이름", key=f"{prefix}_nc_name", placeholder="유로")
        ncountry = n[2].text_input("국가", key=f"{prefix}_nc_country", placeholder="유럽연합")
        symbol = n[3].text_input("통화 기호", key=f"{prefix}_nc_sym", placeholder="€", help="화면에 괄호로 표시됩니다. 비우면 통화 코드를 씁니다.")
        qunit = n[4].number_input("환율 표기 단위", 1.0, step=1.0, key=f"{prefix}_nc_unit",
                                  help="환율을 '외화 몇 단위당 원'으로 적을지. 보통 1, 베트남 동처럼 가치가 작으면 100.")
        code = (ncode or "").strip().upper()
        symbol = symbol.strip() or code or "¤"
        spec["new_currency"] = {"code": code, "name": nname, "country": ncountry, "unit": qunit, "symbol": symbol}
        if not code:
            spec["error"] = "(기타) 통화 코드를 입력하세요"
    else:
        info = curs[code]
        symbol, qunit = db.currency_symbol(info), info["quote_unit"]
    spec["currency"] = code or "__NEW__"

    m = st.columns([2, 2, 2])
    mode_labels = [MODE_FIXED_LABEL, MODE_AUTO_LABEL]
    cur_is_same = bool(cur and cur.get("currency") == code and cur.get("foreign_price") is not None)
    mode_idx = 1 if cur_is_same and cur.get("fx_mode") == "auto" else 0
    mode_label = m[0].radio("환율 적용 방식", mode_labels, index=mode_idx, key=f"{prefix}_mode",
                            help="• 고정(기본): 이 단가를 받은 당시 환율을 직접 입력합니다. 이후 시세가 바뀌어도 이 단가의 원화 값은 그대로입니다.\n"
                                 "• 자동: '환율' 메뉴에 쌓인 날짜별 환율을 따라가서, 환율이 바뀌면 원화 원가도 따라 바뀝니다.")
    foreign_default = float(cur["foreign_price"]) if cur_is_same else 0.0
    foreign = m[1].number_input(f"외화 단가 ({symbol}/{unit})", 0.0, value=foreign_default, step=0.1, format="%.4f",
                                key=f"{prefix}_for_{ksuf}", help=f"{'1kg' if unit == 'kg' else '1' + unit}당 외화 가격입니다. 예: 7.5{symbol}/{unit}")
    spec["foreign"] = foreign
    pb = db.load_pricebook()
    if mode_label == MODE_FIXED_LABEL:
        spec["mode"] = "fixed"
        found = pb.fx_asof(code, d.isoformat()) if code else None
        suggested = found[0] * qunit if found else 0.0
        default_rate = float(cur["fx_fixed_rate"]) if cur_is_same and cur.get("fx_fixed_rate") else suggested
        rate = m[2].number_input(f"환율 (원 / {qunit:g}{symbol})", 0.0, value=float(default_rate), step=1.0, format="%.4f",
                                 key=f"{prefix}_rate_{ksuf}",
                                 help=f"이 단가를 받은 당시의 환율을 직접 입력하세요. 외화 {qunit:g}{symbol}당 몇 원인지입니다. "
                                      f"'환율' 메뉴에 등록된 최근 값이 있으면 그 값이 자동으로 채워지며, 그대로 고쳐 쓸 수 있습니다.")
        spec["fixed"] = rate
        if rate > 0:
            spec["krw_preview"] = foreign * rate / qunit
            st.caption(_md(f"→ 원화 환산: 외화 단가 {foreign:,.4f}{symbol} × 환율 {rate:,.4f}원/{qunit:g}{symbol} ÷ {qunit:g} = "
                           f"**{spec['krw_preview']:,.2f}원/{unit}**"))
        else:
            st.warning("환율을 입력하세요 (0보다 커야 합니다)")
    else:
        found = pb.fx_asof(code, d.isoformat()) if code else None
        if found is None:
            st.warning(_md(f"{code or '(기타)'} 환율 이력이 {d} 이전에 없습니다. '환율' 메뉴에서 먼저 등록하거나 '고정' 방식을 선택하세요."))
        else:
            spec["krw_preview"] = foreign * found[0]
            m[2].metric("적용될 환율 (자동)", f"{found[0] * qunit:,.4f}", help=f"환율 메뉴의 {found[1]} 값 (원 / {qunit:g}{symbol})")
            st.caption(_md(f"→ 원화 환산 약 **{spec['krw_preview']:,.2f}원/{unit}** (이후 환율이 바뀌면 자동으로 따라 바뀝니다)"))
    return spec


def _price_changed(spec: dict, krw, cur: dict | None, price_key: str) -> bool:
    """폼 입력이 현재 적용 중인 단가와 다른지 (같으면 단가 이력을 새로 만들지 않는다)."""
    if cur is None or cur.get("price_date") is None:
        return True
    if spec["currency"] == "KRW":
        return not (cur["currency"] == "KRW" and cur.get("foreign_price") is None
                    and abs(cur[price_key] - (krw or 0.0)) < 1e-9)
    same = (cur["currency"] == spec["currency"] and cur.get("foreign_price") is not None
            and abs(cur["foreign_price"] - spec["foreign"]) < 1e-9 and (cur.get("fx_mode") or "auto") == spec["mode"])
    if same and spec["mode"] == "fixed":
        same = abs((cur.get("fx_fixed_rate") or 0.0) - spec["fixed"]) < 1e-9
    return not same


def _save_price(kind: str, item_id: int, spec: dict, krw, cur: dict | None, price_key: str, memo: str = "") -> str:
    """단가가 입력·변경됐으면 단가 이력에 추가. 결과 설명 문자열을 돌려준다."""
    if spec["currency"] == "KRW":
        if not krw:
            return "단가는 입력하지 않아 이력에 추가하지 않았습니다"
    else:
        if not spec["foreign"] or spec["foreign"] <= 0:
            raise ValueError("외화 단가를 입력하세요 (0보다 커야 합니다)")
        if spec["mode"] == "fixed" and (not spec["fixed"] or spec["fixed"] <= 0):
            raise ValueError("환율을 입력하세요 (0보다 커야 합니다)")
    if not _price_changed(spec, krw, cur, price_key):
        return "단가는 변경되지 않아 이력을 추가하지 않았습니다"
    add = db.add_price if kind == "ingredient" else db.add_material_price
    got = add(item_id, krw if spec["currency"] == "KRW" else None, spec["date"], memo,
              spec["currency"], spec["foreign"], spec["mode"], spec["fixed"])
    return f"단가 이력 추가 — {spec['date']} 기준 {got:,.2f}원"


def _price_history(kind: str, item_id: int, key: str) -> None:
    hist = db.price_history(item_id) if kind == "ingredient" else db.material_price_history(item_id)
    st.markdown("**단가 이력**", help="이 품목에 지금까지 입력한 단가를 날짜순으로 모두 보여줍니다. 가격 추이·변동률 조회의 원천 데이터입니다.\n"
                                  "• '입력 시 환산(원)' = 단가를 입력한 시점에 계산된 원화 값\n"
                                  "• '오늘 환율 기준(원)' = '자동' 방식은 오늘 환율로 다시 환산한 값, '고정'은 입력 환율 그대로")
    if not hist:
        st.info("단가 이력이 없습니다. 위에서 단가를 입력하고 저장하세요.")
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
            "입력 환율(고정)": h["fx_fixed_rate"], "입력 시 환산(원)": round(h[krw_key], 2),
            "오늘 환율 기준(원)": round(res["krw"], 2), "메모": h["memo"],
            "상태": "적용 예정" if h["effective_date"] > today else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    c = st.columns([2, 1, 1])
    del_id = c[0].selectbox("잘못 입력한 단가 삭제 (ID 선택)", [r["ID"] for r in rows], key=f"{key}_delid",
                            help="위 표의 ID를 고르세요. 삭제하면 그 날짜의 가격 기록이 사라져 추이 그래프도 바뀝니다(삭제 기록은 남습니다).")
    sure = c[1].checkbox("삭제 확인", key=f"{key}_delsure")
    if c[2].button("🗑 삭제", key=f"{key}_del", disabled=not sure):
        db.delete_price(del_id) if kind == "ingredient" else db.delete_material_price(del_id)
        db.log_audit("단가 이력 삭제", f"{'원료' if kind == 'ingredient' else '부자재'} 단가 ID {del_id}",
                     st.session_state.get("who", ""))
        st.rerun()


# ====================================================================== 원료
def page_ingredients():
    st.header("원료 단가 마스터", help="원료(견과 등)의 기본 정보와 날짜별 단가를 관리합니다. 수입 원료는 통화·환율과 함께 입력하세요.")
    _flash()
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

    st.subheader("원료 등록 / 수정", help="새 원료를 등록하거나 기존 원료를 고쳐 저장합니다. 단가를 바꿔 저장하면 '단가 적용일'로 단가 이력이 한 줄 추가됩니다.")
    pick = st.selectbox("수정할 원료 (새 원료는 '새 원료' 선택 후 아래에 이름 입력)", ["➕ 새 원료"] + [i["name"] for i in ings],
                        key="ing_pick", help="기존 원료를 고르면 현재 값이 채워집니다.")
    cur = next((i for i in ings if i["name"] == pick), None)
    ver = st.session_state.get("ing_ver", 0)
    prefix = f"ing_{cur['id'] if cur else 'new'}_{ver}"
    opts, curs = _fx_options()

    c = st.columns(5)
    name = c[0].text_input("원료명", cur["name"] if cur else "", key=f"{prefix}_name", help="견적·배합표에 표시되는 이름 (예: 아몬드)")
    origin = c[1].text_input("원산지", cur["origin"] if cur else "", key=f"{prefix}_origin", help="예: 미국, 베트남")
    supplier = c[2].text_input("공급처", cur["supplier"] if cur else "", key=f"{prefix}_supplier", help="구매 거래처")
    lm = c[3].number_input("수분 loss(%)", 0.0, 100.0, (cur["loss_moisture"] * 100) if cur else 0.0, 0.1,
                           key=f"{prefix}_lm", help="건조·수분 증발로 줄어드는 비율")
    ls = c[4].number_input("소분 loss(%)", 0.0, 100.0, (cur["loss_split"] * 100) if cur else 0.0, 0.1,
                           key=f"{prefix}_ls", help="낱개로 나눠 담는(소분) 과정에서 생기는 손실 비율")
    r2 = st.columns(4)
    lso = r2[0].number_input("선별 loss(%)", 0.0, 100.0, (cur["loss_sorting"] * 100) if cur else 0.0, 0.01,
                             key=f"{prefix}_lso", help="불량 제거(선별) 과정에서 버려지는 비율")
    krw = _krw_input(r2[1], prefix, "기본 원료 단가(원/kg)", cur, "price_per_kg", 100.0, opts)
    roast = r2[2].number_input("로스팅비(원/kg)", 0.0, value=float(cur["roasting_cost_per_kg"] or 0) if cur else 0.0,
                               step=10.0, key=f"{prefix}_roast", help="이 원료를 로스팅하는 비용. 기본 단가에 이미 포함돼 있으면 0")
    sortc = r2[3].number_input("선별비(원/kg)", 0.0, value=float(cur["sorting_cost_per_kg"] or 0) if cur else 0.0,
                               step=10.0, key=f"{prefix}_sortc", help="이 원료의 선별 비용. 기본 단가에 이미 포함돼 있으면 0")
    spec = _fx_block(prefix, "kg", cur, "price_per_kg", opts, curs)
    memo = st.text_input("단가 메모 (견적서·공급처 등)", key=f"{prefix}_pmemo", help="이번에 입력하는 단가 이력 줄에 같이 저장되는 메모입니다.")

    b1, b2 = st.columns([1, 6])
    if b1.button("💾 원료 저장", help="원료 정보를 저장하고, 단가를 입력·변경했으면 단가 이력에 추가합니다."):
        if not name.strip():
            st.error("원료명을 입력하세요")
        elif spec["error"]:
            st.error(spec["error"])
        else:
            try:
                if spec["new_currency"]:
                    n = spec["new_currency"]
                    if n["code"] not in curs:
                        db.add_currency(n["code"], n["name"] or n["code"], n["country"], n["unit"], n["symbol"])
                iid_ = db.upsert_ingredient(name.strip(), origin, supplier, lm / 100, ls / 100, lso / 100, roast, sortc)
                note = _save_price("ingredient", iid_, spec, krw, cur, "price_per_kg", memo)
                _flash(f"'{name.strip()}' 저장 완료 — {note}")
                _bump("ing_ver")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if cur and b2.button("🗑 이 원료 삭제", help="배합표에서 쓰이지 않는 원료만 삭제할 수 있습니다."):
        try:
            db.delete_ingredient(cur["id"])
            _bump("ing_ver")
            st.rerun()
        except Exception:
            st.error("제품 배합표에서 사용 중인 원료는 삭제할 수 없습니다")

    if cur:
        _price_history("ingredient", cur["id"], f"ing{cur['id']}")


# ====================================================================== 부자재
def page_materials():
    st.header("부자재 마스터", help="포장지·인케이스·카톤박스 등 부자재의 기본 정보와 날짜별 단가를 관리합니다. 수입 부자재는 통화·환율과 함께 입력하세요.")
    _flash()
    mats = db.list_materials()
    if mats:
        st.dataframe(pd.DataFrame([{
            "부자재": m["name"], "분류": CAT_LABEL[m["category"]], "현재단가(원)": num(m["unit_price"], 2),
            "통화": m["currency"], "외화단가": num(m["foreign_price"], 4), "적용환율": num(m["fx"], 4),
            "단가기준일": m["price_date"], "기본 loss": pct(m["loss_rate"], 2), "메모": m["memo"]} for m in mats]),
            hide_index=True, width="stretch")
        _excel_button("⬇ 부자재 마스터 + 단가 이력 엑셀 (전체)", ["부자재 마스터", "부자재 단가이력", "환율 이력"],
                      f"부자재_단가_{date.today()}.xlsx")
    st.subheader("부자재 등록 / 수정", help="새 부자재를 등록하거나 기존 부자재를 고쳐 저장합니다. 단가를 바꿔 저장하면 '단가 적용일'로 단가 이력이 추가됩니다.")
    pick = st.selectbox("수정할 부자재", ["➕ 새 부자재"] + [m["name"] for m in mats], key="mat_pick",
                        help="기존 부자재를 고르면 현재 값이 채워집니다.")
    cur = next((m for m in mats if m["name"] == pick), None)
    ver = st.session_state.get("mat_ver", 0)
    prefix = f"mat_{cur['id'] if cur else 'new'}_{ver}"
    opts, curs = _fx_options()

    c = st.columns(3)
    name = c[0].text_input("부자재명", cur["name"] if cur else "", key=f"{prefix}_name", help="예: 롤필름, 인케이스, 카톤박스")
    cats = list(CAT_KEY)
    cat = c[1].selectbox("분류 (원가표의 어느 항목에 들어가나)", cats, key=f"{prefix}_cat",
                         index=cats.index(CAT_LABEL[cur["category"]]) if cur else 0,
                         help="원가 구성표에서 이 부자재가 합산되는 항목입니다: 롤포장지 / 포장지 / 인케이스 / 카톤박스 / 소분비 / 기타")
    loss = c[2].number_input("기본 loss(%)", 0.0, 100.0, (cur["loss_rate"] * 100) if cur else 3.0, 0.1, key=f"{prefix}_loss",
                             help="부자재 사용 중 버려지는 비율. 제품의 부자재 표에서 개별로 바꿀 수도 있습니다.")
    r2 = st.columns(3)
    krw = _krw_input(r2[0], prefix, "기본 부자재 단가(원)", cur, "unit_price", 1.0, opts)
    memo = r2[1].text_input("메모", cur["memo"] if cur else "", key=f"{prefix}_memo", help="부자재 자체에 대한 메모 (규격 등)")
    pmemo = r2[2].text_input("단가 메모 (견적서·공급처 등)", key=f"{prefix}_pmemo", help="이번에 입력하는 단가 이력 줄에 같이 저장되는 메모입니다.")
    spec = _fx_block(prefix, "개", cur, "unit_price", opts, curs)

    b1, b2 = st.columns([1, 6])
    if b1.button("💾 부자재 저장", help="부자재 정보를 저장하고, 단가를 입력·변경했으면 단가 이력에 추가합니다."):
        if not name.strip():
            st.error("부자재명을 입력하세요")
        elif spec["error"]:
            st.error(spec["error"])
        else:
            try:
                if spec["new_currency"]:
                    n = spec["new_currency"]
                    if n["code"] not in curs:
                        db.add_currency(n["code"], n["name"] or n["code"], n["country"], n["unit"], n["symbol"])
                mid_ = db.upsert_material(name.strip(), CAT_KEY[cat], None, loss / 100, memo)
                note = _save_price("material", mid_, spec, krw, cur, "unit_price", pmemo)
                _flash(f"'{name.strip()}' 저장 완료 — {note}")
                _bump("mat_ver")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if cur and b2.button("🗑 이 부자재 삭제", help="제품에서 쓰이지 않는 부자재만 삭제할 수 있습니다."):
        try:
            db.delete_material(cur["id"])
            _bump("mat_ver")
            st.rerun()
        except Exception:
            st.error("제품에서 사용 중인 부자재는 삭제할 수 없습니다")

    if cur:
        _price_history("material", cur["id"], f"mat{cur['id']}")


# ====================================================================== 환율
def page_fx():
    st.header("환율 관리 (미국 · 베트남 · 튀르키예 · 기타)",
              help=FX_MASTER_VS_ENTRY)
    st.caption("이 메뉴는 **날짜별 환율 시세 기록**입니다. 환율 조회·그래프, 그리고 '자동' 방식 단가의 환산에 쓰입니다. "
               "원료·부자재 단가를 받은 '당시의 환율'은 각 단가 입력 화면에서 따로 입력합니다.")
    curs = db.list_currencies(include_krw=False)
    rows = []
    for cur in curs:
        hist = db.list_fx_rates(cur["code"])
        last, prev = (hist[0] if hist else None), (hist[1] if len(hist) > 1 else None)
        rows.append({
            "통화": db.currency_label(cur), "코드": cur["code"],
            "표기 단위": f"외화 {cur['quote_unit']:g}{db.currency_symbol(cur)}당 원",
            "최근 환율(원)": num(last["rate"], 4) if last else "", "기준일": last["rate_date"] if last else "",
            "직전 대비": (f"{(last['rate'] / prev['rate'] - 1) * 100:+.2f}%" if last and prev else ""),
            "등록 건수": len(hist)})
    st.markdown("**등록된 통화와 최근 환율**", help="미국($)·베트남(₫)·튀르키예(₺)가 기본이며, 그 외 나라는 아래 '(기타) 통화 추가'로 늘릴 수 있습니다. "
                                          "'직전 대비'는 가장 최근 두 번 입력한 값의 변동률입니다.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("환율 입력", help="오늘(또는 원하는 날짜)의 환율을 한 건씩 저장합니다. 같은 통화·같은 날짜에 다시 저장하면 덮어씁니다. 여러 날짜는 '엑셀 일괄 등록'의 '환율' 시트로 한 번에 올리세요.")
    opts = {db.currency_label(c): c["code"] for c in curs}
    c = st.columns(4)
    code = opts[c[0].selectbox("통화", list(opts), key="fx_cur", help="미국($) / 베트남(₫) / 튀르키예(₺) / (기타) 추가한 통화")]
    d = c[1].date_input("기준일", date.today(), key="fx_date", help="이 환율이 적용되는 날짜")
    rate = c[2].number_input(f"환율 ({unit_note(code)})", 0.0, step=1.0, format="%.4f", key="fx_rate",
                             help="외화 1단위(베트남은 100동)가 몇 원인지 입력합니다. 은행 매매기준율 등 회사 기준 값을 쓰세요.")
    memo = c[3].text_input("메모", key="fx_memo", help="예: 하나은행 매매기준율")
    if st.button("💾 환율 저장 (같은 날짜는 덮어씀)"):
        try:
            db.add_fx_rate(code, rate, d.isoformat(), memo)
            st.success("저장되었습니다")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    with st.expander("➕ (기타) 통화 추가 — 미국·베트남·튀르키예 외 다른 나라 (예: EUR 유로, CNY 위안, AUD 호주달러)"):
        e = st.columns(5)
        ncode = e[0].text_input("통화 코드 (영문 2~6자)", key="nc_code", placeholder="EUR",
                                help="국제 표준 통화 코드입니다. 예: EUR, CNY, AUD, JPY")
        nname = e[1].text_input("통화 이름", key="nc_name", placeholder="유로")
        ncountry = e[2].text_input("국가", key="nc_country", placeholder="유럽연합")
        nsym = e[3].text_input("통화 기호", key="nc_sym", placeholder="€", help="화면에 괄호로 표시됩니다. 예: 유럽연합 (€)")
        nunit = e[4].number_input("환율 표기 단위", 1.0, step=1.0, key="nc_unit",
                                  help="보통 1. 베트남 동처럼 가치가 작은 통화는 100(100동당 원)")
        if st.button("통화 추가"):
            try:
                db.add_currency(ncode, nname, ncountry, nunit, nsym)
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

    st.subheader("환율 이력 조회", help=(
        "📌 이 조회의 데이터는 어디서 오나요?\n"
        "• 위 '환율 입력'으로 직접 저장한 값\n"
        "• '엑셀 일괄 등록'의 '환율' 시트로 올린 값\n"
        "이 두 가지만 사용합니다. 인터넷에서 자동으로 가져오지 않습니다 (회사 PC 안에서만 동작).\n\n"
        "📈 그래프는 어떻게 그려지나요?\n"
        "값을 입력하지 않은 날짜는 '직전에 입력한 환율'이 그대로 이어진 것으로 보고 일별로 그립니다 (계단 모양). "
        "그래서 환율을 자주 입력할수록 정확한 일별 추이가 나옵니다."))
    st.caption("출처: 이 화면에서 직접 입력했거나 엑셀로 올린 환율입니다 (인터넷 자동 수집 아님). 입력하지 않은 날은 직전 값이 이어집니다.")
    f = st.columns(3)
    sel = f[0].multiselect("통화", list(opts), default=list(opts)[:1], key="fxq_cur", help="여러 통화를 함께 골라 비교할 수 있습니다.")
    rng = f[1].date_input("기간", value=(date.today() - timedelta(days=365), date.today()), key="fxq_rng",
                          help="조회할 시작일과 종료일을 차례로 선택하세요.")
    if not sel or not isinstance(rng, (tuple, list)) or len(rng) != 2:
        return
    d_from, d_to = rng[0].isoformat(), rng[1].isoformat()
    pb = db.load_pricebook()
    per_cur, names = {}, {}
    for label in sel:
        code = opts[label]
        try:
            per_cur[code] = trends.fx_daily(pb, code, d_from, d_to)
        except ValueError as err:
            st.error(str(err))
            return
        names[code] = label
    if any(len(s_) for s_ in per_cur.values()):
        df = pd.DataFrame({code: pd.Series({r["date"]: r["rate"] for r in s_}) for code, s_ in per_cur.items()})
        df.index = pd.to_datetime(df.index)
        line_chart(df)
        if len(per_cur) > 1:
            st.markdown("**기간 시작=100 지수 (통화 간 변동 비교)**",
                        help="통화마다 단위가 달라 한 그래프에 그리면 비교가 어렵습니다. 시작일 값을 100으로 맞춰 '얼마나 올랐나'만 비교합니다.")
            idx = df / df.apply(lambda s_: s_.dropna().iloc[0] if s_.dropna().size else 1) * 100
            line_chart(idx)
        stats = []
        for code, s_ in per_cur.items():
            if s_:
                st_ = trends.period_stats([{"date": r["date"], "krw": r["rate"], "changed": r["changed"]} for r in s_])
                stats.append({"통화": code, "시작": num(st_["start"], 4), "종료": num(st_["end"], 4),
                              "변동률": f"{st_['rate'] * 100:+.2f}%", "최저": f"{st_['min']:,.4f} ({st_['min_date']})",
                              "최고": f"{st_['max']:,.4f} ({st_['max_date']})", "평균": num(st_["avg"], 4)})
        st.dataframe(pd.DataFrame(stats), hide_index=True, width="stretch")
        st.download_button("⬇ 환율 일별 데이터 엑셀 (그래프 포함)", fx_xlsx(per_cur, names),
                           f"환율_{d_from}_{d_to}.xlsx", help="조회 기간의 일별 환율(입력 없는 날은 직전 값)과 엑셀 그래프를 저장합니다.")
    else:
        st.info("해당 기간에 환율 데이터가 없습니다.")

    raw = [r for label in sel for r in db.list_fx_rates(opts[label], d_from, d_to)]
    if raw:
        st.markdown("**등록된 환율 (직접 입력한 날짜만)**", help="일별 그래프의 원본입니다. 이 표의 날짜에서만 값이 바뀌고, 사이 날짜는 직전 값으로 채워집니다.")
        st.dataframe(pd.DataFrame([{"ID": r["id"], "통화": r["currency"], "기준일": r["rate_date"],
                                    "환율(원)": r["rate"], "메모": r["memo"]} for r in raw]),
                     hide_index=True, width="stretch")
        dd = st.columns([2, 1, 1])
        did = dd[0].selectbox("삭제할 환율 (ID)", [r["id"] for r in raw], key="fx_delid",
                              help="잘못 입력한 환율을 지웁니다. '자동' 방식 단가의 원화 값과 과거 추이가 바뀔 수 있습니다.")
        sure = dd[1].checkbox("삭제 확인", key="fx_delsure")
        if dd[2].button("🗑 환율 삭제", disabled=not sure):
            db.delete_fx_rate(did)
            db.log_audit("환율 삭제", f"환율 ID {did}", st.session_state.get("who", ""))
            st.rerun()
    _excel_button("⬇ 환율 이력 전체 엑셀", ["환율 이력", "통화"], f"환율이력_전체_{date.today()}.xlsx")


# ====================================================================== 판매처
def page_channels():
    st.header("판매처 관리 (마트 · 온라인 업체)",
              help="판매처를 고르면 견적에 마트별 물류비, 온라인 업체별 수수료·홍보비·기획전 비용·택배비가 반영됩니다. "
                   "모든 % 항목은 납품가 기준이고, '원/개' 항목은 개당 정액입니다.")
    st.caption("값을 비워 둔 판관비·마진은 '설정'의 기본값을 따릅니다.")
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

    pick = st.selectbox("수정할 판매처", ["➕ 새 판매처"] + [c["name"] for c in chans], help="기존 판매처를 고르면 현재 값이 채워집니다.")
    cur = next((c for c in chans if c["name"] == pick), None)
    g = lambda k, d=0.0: (cur[k] if cur and cur[k] is not None else d)
    kinds = list(CHANNEL_KINDS)
    c = st.columns(3)
    name = c[0].text_input("판매처명 (예: ○○마트, △△몰)", cur["name"] if cur else "", help="견적 화면의 판매처 목록에 표시됩니다.")
    kind = c[1].selectbox("유형", kinds, index=kinds.index(cur["kind"]) if cur else 0, format_func=CHANNEL_KINDS.get,
                          help="오프라인(마트)은 물류비, 온라인은 수수료·홍보비·기획전·택배비를 입력합니다.")
    memo = c[2].text_input("메모", cur["memo"] if cur else "")

    st.markdown("**물류비 (마트별)**", help="마트(유통사)에 납품할 때 물류센터 이용 등으로 내는 비용입니다.")
    l = st.columns(3)
    log_rate = l[0].number_input("물류비율(%)", 0.0, 50.0, g("logistics_rate") * 100, 0.05,
                                 help="납품가에 대한 % (예: 3 → 납품가의 3%)")
    log_fixed = l[1].number_input("정액 물류비(원/개)", 0.0, value=float(g("logistics_fixed")), step=10.0,
                                  help="% 와 별도로 개당 붙는 정액 물류비")
    log_vat = l[2].checkbox("물류비율을 VAT 포함(×1.1) 납품가 기준으로", bool(g("logistics_vat", 0)),
                            help="물류비율을 부가세 포함 금액에 곱해 계산하는 계약일 때 체크")

    fee_rate = promo = event = 0.0
    event_fixed = parcel = 0.0
    online_vat = False
    if kind == "online":
        st.markdown("**온라인 업체 비용**", help="온라인 쇼핑몰(업체)에 판매할 때 업체가 가져가거나 부담시키는 비용입니다.")
        o = st.columns(3)
        fee_rate = o[0].number_input("업체 수수료율(%)", 0.0, 60.0, g("fee_rate") * 100, 0.1, help="판매 금액에서 업체가 떼어가는 수수료 %")
        promo = o[1].number_input("업체 홍보비율(%)", 0.0, 50.0, g("promo_rate") * 100, 0.1, help="업체 광고·노출에 쓰는 홍보비 %")
        event = o[2].number_input("기획전 비용률(%)", 0.0, 50.0, g("event_rate") * 100, 0.1, help="기획전(할인 행사) 참여 비용 %")
        o2 = st.columns(3)
        event_fixed = o2[0].number_input("기획전 정액 비용(원/개)", 0.0, value=float(g("event_fixed")), step=10.0,
                                         help="% 와 별도로 개당 붙는 정액 기획전 비용")
        parcel = o2[1].number_input("택배비(원/개)", 0.0, value=float(g("parcel_cost")), step=100.0, help="개별 배송 택배 비용(1세트당)")
        online_vat = o2[2].checkbox("수수료·홍보비·기획전 %를 VAT 포함(×1.1) 기준으로", bool(g("online_vat", 0)),
                                    help="업체가 부가세 포함 판매가에 % 를 적용하는 계약일 때 체크")
    else:
        st.caption("온라인 업체 비용(수수료·홍보비·기획전·택배비)은 유형을 '온라인'으로 바꾸면 입력할 수 있어요.")

    st.markdown("**이 판매처만 다른 판관비·마진을 쓸 때**", help="체크하지 않으면 '설정' 메뉴의 기본 판관비율·마진율을 씁니다.")
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
