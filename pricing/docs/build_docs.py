"""docs/*.html 을 A4 PDF 로 변환하고 쪽수를 검증한다.  실행: python pricing/docs/build_docs.py
(Playwright + Chromium 필요: pip install playwright)  설치 안내서는 반드시 1쪽이어야 한다."""
from __future__ import annotations

import glob
import sys
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
JOBS = {  # html -> (pdf 이름, 기대 쪽수 또는 None)
    "install_guide.html": ("설치_실행_안내서_A4.pdf", 1),
    "manual.html": ("사용설명서.pdf", None),
}


# 사용설명서에 넣을 화면 조각: 출력 이름 -> (원본, 위쪽 y, 아래쪽 y)  (원본 폭 1000px 기준)
CROPS = {
    "c01_quote": ("01_quote.png", 40, 1250),
    "c03_form": ("03_ingredient.png", 520, 1333),
    "c07a_trend": ("07_trend_item.png", 40, 940),
    "c07b_fx": ("07_trend_item.png", 975, 1520),
    "c08_rank": ("08_trend_rank.png", 40, 960),
    "c09_prod": ("09_trend_product.png", 40, 1260),
    "c10_bulk": ("10_bulk.png", 40, 1010),
    "c12_compare": ("12_compare.png", 40, 1260),
    "c06_channel": ("06_channel.png", 40, 1260),
}


def make_crops() -> None:
    out = HERE / "img" / "crops"
    out.mkdir(exist_ok=True)
    for name, (src, y0, y1) in CROPS.items():
        im = Image.open(HERE / "img" / src)
        im.crop((0, y0, im.size[0], min(y1, im.size[1]))).save(out / f"{name}.png", optimize=True)


def main() -> int:
    make_crops()
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome") or [None])[0]
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        for html, (pdf, want) in JOBS.items():
            src = HERE / html
            if not src.exists():
                continue
            page = browser.new_page()
            page.goto(src.as_uri())
            page.wait_for_load_state("networkidle")
            out = HERE / pdf
            page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
            n = len(PdfReader(str(out)).pages)
            flag = "" if want in (None, n) else f"  ← 기대 {want}쪽!"
            print(f"{pdf}: {n}쪽{flag}")
            ok &= want in (None, n)
            page.close()
        browser.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
