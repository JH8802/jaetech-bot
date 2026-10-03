"""다른 PC 모의 테스트용 배포 ZIP 만들기 (pricing 프로그램만 담음).

실행:  python -m pricing.make_package        → dist/납품가산출_모의테스트_배포용.zip
 - 포함: pricing 폴더(프로그램·예제 엑셀), 설치 안내서(A4)·사용설명서 PDF, 먼저_읽어주세요.txt
 - 제외: .venv(PC마다 새로 생성), data(내 데이터), 테스트, 문서 원본(html/이미지), 캐시, 개인 키/DB 파일
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent            # .../pricing
ROOT = HERE.parent
OUT = ROOT / "dist" / "납품가산출_모의테스트_배포용.zip"
PDFS = ["설치_실행_안내서_A4.pdf", "사용설명서.pdf"]

SKIP_DIRS = {".venv", "data", "__pycache__", ".pytest_cache", "tests", "docs", ".git"}
SKIP_SUFFIX = {".pyc", ".db", ".db-wal", ".db-shm", ".session"}
SKIP_NAMES = {".env", "make_package.py"}

README = """\
[ 납품가 산출 프로그램 — 모의 테스트용 ]

1) 이 ZIP 을 우클릭 → '모두 압축 풀기' → 위치를 C:\\pricing_app 로 지정하세요.
   (바탕화면 / OneDrive / [안전폴더] 에는 풀지 마세요 — 실행이 막힙니다)
2) 풀린 폴더 안의  pricing\\run.bat  을 더블클릭하면 실행됩니다.
   처음에는 필요한 부품 설치로 3~5분 걸립니다 (인터넷 연결 필요, Python 3.11 이상 필요).
3) 자세한 방법은  설치_실행_안내서_A4.pdf (A4 1장)  를 보세요.
4) 사용법은  사용설명서.pdf  를, 의견은 그 맨 뒤 '의견 기록 양식'에 적어 전달해 주세요.

※ 테스트에는 실제 원가를 넣지 말고, pricing\\sample 폴더의 예제(가짜) 엑셀만 사용하세요.
"""


def build() -> Path:
    OUT.parent.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(HERE.rglob("*")):
            rel = f.relative_to(HERE)
            if f.is_dir() or set(rel.parts[:-1]) & SKIP_DIRS or f.suffix in SKIP_SUFFIX or f.name in SKIP_NAMES:
                continue
            z.write(f, Path("pricing") / rel)
            count += 1
        for name in PDFS:
            src = HERE / "docs" / name
            if not src.exists():
                raise SystemExit(f"문서가 없습니다: {src} (python pricing/docs/build_docs.py 로 먼저 생성)")
            z.write(src, name)
        z.writestr("먼저_읽어주세요.txt", "\ufeff" + README.replace("\n", "\r\n"))
    print(f"{OUT}  ({OUT.stat().st_size / 1e6:.1f} MB, 프로그램 파일 {count}개 + 문서 {len(PDFS)}개)")
    return OUT


if __name__ == "__main__":
    build()
    sys.exit(0)
