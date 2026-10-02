"""견적 결과를 엑셀(.xlsx)로 내보내기."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .engine import CATEGORIES, QuoteInput, QuoteResult

HEAD = PatternFill("solid", fgColor="DDEBF7")
BOLD = Font(bold=True)
MONEY = '#,##0'
MONEY1 = '#,##0.0'
PCT = '0.0%'


def _fit(ws):
    for col in ws.columns:
        w = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(10, w * 1.6), 40)


def quotes_to_xlsx(items: list[tuple[QuoteInput, QuoteResult]], internal: bool = True) -> bytes:
    """internal=True : 원가 내역 포함(사내용)
       internal=False: 제품명/납품가만 (거래처 제출용)"""
    wb = Workbook()
    if not internal:
        ws = wb.active
        ws.title = "납품가"
        ws.append(["제품명", "납품가(원, VAT 별도)"])
        for c in ws[1]:
            c.font, c.fill = BOLD, HEAD
        for q, r in items:
            ws.append([q.product_name, r.price])
            ws.cell(ws.max_row, 2).number_format = MONEY
        _fit(ws)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # 요약 시트
    ws = wb.active
    ws.title = "요약"
    heads = ["제품명", "원물가", "선별비", "로스", "포장지", "소분비", "박스비", "운송비",
             "직접원가", "판관비", "마진", "센터도착가", "물류비", "원가합계", "납품가",
             "실질마진", "실질마진율"]
    ws.append(heads)
    for c in ws[1]:
        c.font, c.fill = BOLD, HEAD
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for q, r in items:
        ws.append([q.product_name, r.materials_cost, r.sorting_cost, r.loss_cost, r.pack_cost,
                   r.split_cost, r.box_cost, r.shipping_cost, r.direct_cost, r.sga, r.margin,
                   r.center_cost, r.logistics, r.total_cost, r.price,
                   r.effective_margin, r.effective_margin_rate])
        for col in range(2, 17):
            ws.cell(ws.max_row, col).number_format = MONEY1
        ws.cell(ws.max_row, 17).number_format = PCT
    _fit(ws)

    # 제품별 상세 시트
    used = set()
    for q, r in items:
        title = q.product_name[:28].replace("/", "_").replace("\\", "_").replace("*", "").replace("?", "")
        base, n = title, 2
        while title in used:
            title, n = f"{base[:25]}_{n}", n + 1
        used.add(title)
        d = wb.create_sheet(title)
        d.append(["제품명", q.product_name, "", "봉수", q.bag_count, "1봉 중량(g)", q.unit_weight_g])
        d.append([])
        d.append(["원료", "구성비", "단위중량(g)", "벌크단가(원/kg)", "원물가", "로스율", "로스"])
        for c in d[3]:
            c.font, c.fill = BOLD, HEAD
        for x in r.ingredient_rows:
            d.append([x["name"], x["ratio"], x["unit_g"], x["price_per_kg"], x["cost"],
                      x["loss_rate"], x["loss"]])
            d.cell(d.max_row, 2).number_format = PCT
            d.cell(d.max_row, 6).number_format = PCT
            for col in (4, 5, 7):
                d.cell(d.max_row, col).number_format = MONEY1
        d.append([])
        d.append(["부자재", "분류", "기본금액", "loss", "합계"])
        for c in d[d.max_row]:
            c.font, c.fill = BOLD, HEAD
        for x in r.material_rows:
            d.append([x["name"], CATEGORIES[x["category"]], x["base"], x["loss"], x["total"]])
            for col in (3, 4, 5):
                d.cell(d.max_row, col).number_format = MONEY1
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
        for w in r.warnings:
            d.append(["⚠ " + w])
        _fit(d)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
