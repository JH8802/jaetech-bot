"""견적 결과를 엑셀(.xlsx)로 내보내기."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .engine import CATEGORIES, QuoteInput, QuoteResult, calc_mode

HEAD = PatternFill("solid", fgColor="DDEBF7")
BOLD = Font(bold=True)
MONEY = '#,##0'
MONEY1 = '#,##0.0'
PCT = '0.0%'
PCT2 = '0.00%'


def _fit(ws, maxw=40):
    for col in ws.columns:
        w = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(10, w * 1.6), maxw)


def _head(ws, row=1):
    for c in ws[row]:
        c.font, c.fill = BOLD, HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _save(wb) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _norm_items(items):
    """(q, r) 또는 (q, r, meta) 를 (q, r, meta|None) 으로 통일."""
    return [(i[0], i[1], i[2] if len(i) > 2 else None) for i in items]


def _fmt_money_cols(ws, cols, fmt=MONEY1):
    for col in cols:
        ws.cell(ws.max_row, col).number_format = fmt


# =====================================================================
# 견적 1건(또는 여러 건) 원가표
# =====================================================================
def quotes_to_xlsx(items, internal: bool = True) -> bytes:
    """internal=True : 원가 내역 포함(사내용)
       internal=False: 제품명/납품가만 (거래처 제출용)"""
    items = _norm_items(items)
    wb = Workbook()
    if not internal:
        ws = wb.active
        ws.title = "납품가"
        ws.append(["제품명", "납품가(원, VAT 별도)"])
        _head(ws)
        for q, r, _m in items:
            ws.append([q.product_name, r.price])
            ws.cell(ws.max_row, 2).number_format = MONEY
        _fit(ws)
        return _save(wb)

    # ---- 요약 시트 ----
    ws = wb.active
    ws.title = "요약"
    heads = ["제품명", "계산방식", "원물가", "선별비", "로스", "포장지", "소분비", "박스비", "운송비",
             "직접원가", "판관비", "마진", "센터도착가", "물류비", "원가합계", "납품가",
             "실질마진", "실질마진율"]
    ws.append(heads)
    _head(ws)
    for q, r, _m in items:
        ws.append([q.product_name, calc_mode(q), r.materials_cost, r.sorting_cost, r.loss_cost, r.pack_cost,
                   r.split_cost, r.box_cost, r.shipping_cost, r.direct_cost, r.sga, r.margin,
                   r.center_cost, r.logistics, r.total_cost, r.price,
                   r.effective_margin, r.effective_margin_rate])
        _fmt_money_cols(ws, range(3, 18))
        ws.cell(ws.max_row, 18).number_format = PCT
    _fit(ws)

    # ---- 제품별 상세 시트 ----
    used = set()
    for q, r, meta in items:
        title = q.product_name[:28]
        for ch in '/\\*?[]:':
            title = title.replace(ch, "_")
        base, n = title, 2
        while title in used:
            title, n = f"{base[:25]}_{n}", n + 1
        used.add(title)
        d = wb.create_sheet(title)
        d.append(["제품명", q.product_name, "", "봉수", q.bag_count, "1봉 중량(g)", q.unit_weight_g])
        info = ["계산방식", calc_mode(q)]
        if meta:
            info += ["", "견적번호", meta.get("id"), "작성일시", meta.get("created_at"),
                     "작성자", meta.get("created_by"), "메모", meta.get("memo")]
        d.append(info)
        d.append([])
        d.append(["원료", "구성비", "단위중량(g)", "벌크단가(원/kg)", "원물가", "로스율", "로스",
                  "원산지", "공급처", "단가기준일", "단가출처"])
        _head(d, d.max_row)
        for x in r.ingredient_rows:
            d.append([x["name"], x["ratio"], x["unit_g"], x["price_per_kg"], x["cost"],
                      x["loss_rate"], x["loss"], x.get("origin", ""), x.get("supplier", ""),
                      x.get("price_date", ""), x.get("price_source", "")])
            d.cell(d.max_row, 2).number_format = PCT
            d.cell(d.max_row, 6).number_format = PCT
            _fmt_money_cols(d, (4, 5, 7))
        d.append([])
        d.append(["부자재", "분류", "기본금액", "loss", "합계"])
        _head(d, d.max_row)
        for x in r.material_rows:
            d.append([x["name"], CATEGORIES[x["category"]], x["base"], x["loss"], x["total"]])
            _fmt_money_cols(d, (3, 4, 5))
        d.append([])
        for label, val in [
            ("원물가 합계", r.materials_cost), ("선별비", r.sorting_cost), ("로스 합계", r.loss_cost),
            ("포장지", r.pack_cost), ("소분비", r.split_cost), ("박스비", r.box_cost),
            ("운송비", r.shipping_cost), ("직접원가", r.direct_cost),
            (f"판관비 ({q.sga_rate:.2%})", r.sga), (f"마진 ({q.margin_rate:.2%})", r.margin),
            ("센터도착가", r.center_cost),
            (f"물류비 ({q.logistics_rate:.2%}{' VAT포함기준' if q.logistics_vat else ''})", r.logistics),
            ("원가합계", r.total_cost), ("납품가", r.price),
            ("실질 마진(마진+반올림차익)", r.effective_margin),
        ]:
            d.append([label, val])
            d.cell(d.max_row, 1).font = BOLD
            d.cell(d.max_row, 2).number_format = MONEY1
        d.append(["납품가 반올림", q.rounding])
        for w in r.warnings:
            d.append(["⚠ " + w])
        _fit(d)
    return _save(wb)


# =====================================================================
# 견적 이력 목록 전체 (조건 검색 결과)
# =====================================================================
def quotes_list_to_xlsx(items) -> bytes:
    """items: db.search_quotes() 결과 [(q, r, meta), ...].  사내용(원가 포함)."""
    items = _norm_items(items)
    wb = Workbook()
    ws = wb.active
    ws.title = "견적목록"
    heads = ["견적번호", "일시", "작성자", "제품", "계산방식", "봉수", "1봉중량(g)",
             "원물가", "선별비", "로스", "포장지", "소분비", "박스비", "운송비", "직접원가",
             "판관비율", "판관비", "마진율", "마진", "센터도착가", "물류비율", "물류비 VAT기준", "물류비",
             "원가합계", "반올림", "납품가", "실질마진", "실질마진율", "경고", "메모"]
    ws.append(heads)
    _head(ws)
    wi = wb.create_sheet("원료상세")
    wi.append(["견적번호", "일시", "제품", "원료", "원산지", "공급처", "구성비", "벌크단가(원/kg)",
               "단가기준일", "단가출처", "원물가", "로스율", "로스"])
    _head(wi)
    wm = wb.create_sheet("부자재상세")
    wm.append(["견적번호", "일시", "제품", "부자재", "분류", "기본금액", "loss", "합계"])
    _head(wm)

    for q, r, m in items:
        m = m or {}
        ws.append([m.get("id"), m.get("created_at"), m.get("created_by"), q.product_name, calc_mode(q),
                   q.bag_count, q.unit_weight_g,
                   r.materials_cost, r.sorting_cost, r.loss_cost, r.pack_cost, r.split_cost, r.box_cost,
                   r.shipping_cost, r.direct_cost,
                   q.sga_rate, r.sga, q.margin_rate, r.margin, r.center_cost,
                   q.logistics_rate, "예" if q.logistics_vat else "아니오", r.logistics,
                   r.total_cost, q.rounding, r.price, r.effective_margin, r.effective_margin_rate,
                   " / ".join(r.warnings), m.get("memo")])
        row = ws.max_row
        for col in (8, 9, 10, 11, 12, 13, 14, 15, 17, 19, 20, 23, 24, 26, 27):
            ws.cell(row, col).number_format = MONEY1
        for col in (16, 18, 21):
            ws.cell(row, col).number_format = PCT2
        ws.cell(row, 28).number_format = PCT

        for x in r.ingredient_rows:
            wi.append([m.get("id"), m.get("created_at"), q.product_name, x["name"],
                       x.get("origin", ""), x.get("supplier", ""), x["ratio"], x["price_per_kg"],
                       x.get("price_date", ""), x.get("price_source", ""), x["cost"],
                       x["loss_rate"], x["loss"]])
            wi.cell(wi.max_row, 7).number_format = PCT
            wi.cell(wi.max_row, 12).number_format = PCT
            _fmt_money_cols(wi, (8, 11, 13))
        for x in r.material_rows:
            wm.append([m.get("id"), m.get("created_at"), q.product_name, x["name"],
                       CATEGORIES[x["category"]], x["base"], x["loss"], x["total"]])
            _fmt_money_cols(wm, (6, 7, 8))

    for sheet in (ws, wi, wm):
        sheet.freeze_panes = "A2"
        _fit(sheet, 30)
    ws.auto_filter.ref = ws.dimensions
    wi.auto_filter.ref = wi.dimensions
    wm.auto_filter.ref = wm.dimensions
    return _save(wb)


# =====================================================================
# 견적 2건 비교
# =====================================================================
def compare_to_xlsx(cmp: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "요약"
    ma, mb = cmp["meta_a"], cmp["meta_b"]
    ws.append([cmp["headline"]])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([f"A(기준): #{ma.get('id')} {ma.get('product_name')} {ma.get('created_at')} {ma.get('created_by')} [{ma.get('mode')}]"])
    ws.append([f"B(비교): #{mb.get('id')} {mb.get('product_name')} {mb.get('created_at')} {mb.get('created_by')} [{mb.get('mode')}]"])
    ws.append([])
    ws.append(["항목", "A", "B", "차이", "차이%"])
    _head(ws, ws.max_row)
    for r in cmp["summary"]:
        ws.append([r["항목"], r["A"], r["B"], r["차이"], r["차이%"]])
        is_rate = r["항목"] == "실질 마진율"
        for col in (2, 3, 4):
            ws.cell(ws.max_row, col).number_format = PCT if is_rate else MONEY1
        ws.cell(ws.max_row, 5).number_format = PCT
    _fit(ws, 60)

    def table(title, rows, money_cols=(), pct_cols=()):
        sh = wb.create_sheet(title)
        if not rows:
            sh.append(["(내용 없음)"])
            return
        keys = list(rows[0])
        sh.append(keys)
        _head(sh)
        for row in rows:
            sh.append([row[k] for k in keys])
            for i, k in enumerate(keys, 1):
                if k in money_cols:
                    sh.cell(sh.max_row, i).number_format = MONEY1
                if k in pct_cols:
                    sh.cell(sh.max_row, i).number_format = PCT
        _fit(sh)

    table("원료 비교", cmp["ingredients"],
          money_cols={"단가 A", "단가 B", "원물가+로스 A", "원물가+로스 B", "차이"},
          pct_cols={"구성비 A", "구성비 B"})
    table("부자재 비교", cmp["materials"], money_cols={"A", "B", "차이"})
    table("적용 규칙", cmp["rules"])
    table("변동 요인", [{"순위": i + 1, "내용": t} for i, t in enumerate(cmp["drivers"])])
    return _save(wb)
