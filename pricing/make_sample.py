"""일괄 등록 모의 테스트용 예제 엑셀 생성 (모두 가짜 랜덤 데이터 — 실제 원가가 아닙니다).

실행:  python -m pricing.make_sample            → pricing/sample/일괄등록_예제_랜덤데이터.xlsx
같은 시드(기본 20261003)면 항상 같은 파일이 만들어집니다.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook

from . import importer

OUT = Path(__file__).resolve().parent / "sample" / "일괄등록_예제_랜덤데이터.xlsx"

START = date(2025, 10, 1)
END = date(2026, 10, 2)


def _fx_rows(rng: random.Random) -> list[list]:
    """미국/베트남/튀르키예 일별 환율 (랜덤 워크). 통화 | 기준일 | 환율(원) | 메모"""
    rows = []
    plan = {  # 통화: (시작값, 일 변동폭, 하한, 상한, 추세)
        "USD": (1385.0, 0.0045, 1250.0, 1550.0, 0.0001),     # 원 / 1달러
        "VND": (5.45, 0.0030, 5.0, 6.0, 0.0001),             # 원 / 100동
        "TRY": (33.0, 0.0060, 22.0, 36.0, -0.0004),          # 원 / 1리라 (리라 약세)
    }
    for cur, (v, vol, lo, hi, drift) in plan.items():
        d = START
        while d <= END:
            v = min(hi, max(lo, v * (1 + drift + rng.uniform(-vol, vol))))
            rows.append([cur, d.isoformat(), round(v, 2 if cur != "VND" else 3), "랜덤 예제"])
            d += timedelta(days=1)
    return rows


def _price_path(rng, start_value, n, step_range, first=START, span_days=330):
    """n개 시점의 단가 변동 경로 → [(날짜, 값)]"""
    dates = sorted({first + timedelta(days=rng.randint(0, span_days)) for _ in range(n - 1)} | {first})
    v, out = start_value, []
    for d in dates:
        out.append((d.isoformat(), round(v, 2)))
        v *= 1 + rng.uniform(*step_range)
    return out


def build(seed: int = 20261003) -> Workbook:
    rng = random.Random(seed)
    wb = load_workbook(__import__("io").BytesIO(importer.build_workbook()))   # 작성방법 시트 포함 양식

    # ------------------------------------------------ 원료 시트
    wi = wb["원료"]
    # 이름, 원산지, 공급처, loss(수분,소분,선별), 로스팅비, 선별비, (통화, 시작 외화단가 or 원화단가, 단가 변동 횟수, 변동폭)
    ingredients = [
        ("아몬드(미국산)",        "미국",     "랜덤상사 A", (2.5, 3.0, 0.54), 300, 0,   "USD", 7.2,    4, (-0.04, 0.09)),
        ("호두(미국산)",          "미국",     "랜덤상사 A", (0.0, 3.0, 0.50), 0,   0,   "USD", 6.1,    3, (-0.05, 0.08)),
        ("피칸(미국산)",          "미국",     "랜덤상사 B", (0.0, 3.0, 0.91), 0,   200, "USD", 12.4,   3, (-0.03, 0.10)),
        ("마카다미아(베트남산)",  "베트남",   "랜덤무역 C", (0.0, 3.0, 0.00), 0,   0,   "VND", 410000, 3, (-0.02, 0.07)),
        ("캐슈넛(베트남산)",      "베트남",   "랜덤무역 C", (2.5, 3.0, 0.82), 300, 200, "VND", 235000, 4, (-0.02, 0.06)),
        ("건무화과(튀르키예산)",  "튀르키예", "랜덤트레이딩 D", (1.0, 3.0, 0.60), 0, 0, "TRY", 190,    4, (0.00, 0.12)),
        ("건살구(튀르키예산)",    "튀르키예", "랜덤트레이딩 D", (1.0, 3.0, 0.70), 0, 0, "TRY", 165,    3, (0.00, 0.10)),
        ("건포도(미국산)",        "미국",     "랜덤상사 B", (1.5, 3.0, 0.40), 0,   0,   "USD", 3.9,    3, (-0.03, 0.06)),
        ("병아리콩(국산)",        "대한민국", "랜덤농산 E", (1.0, 3.0, 0.30), 0,   0,   "KRW", 5000,   3, (-0.04, 0.07)),
        ("해바라기씨(국산)",      "대한민국", "랜덤농산 E", (0.5, 3.0, 0.30), 0,   0,   "KRW", 7400,   2, (-0.03, 0.06)),
        ("땅콩(국산)",            "대한민국", "랜덤농산 F", (0.5, 3.0, 0.20), 150, 0,   "KRW", 5600,   3, (-0.05, 0.08)),
        ("크랜베리(미국산)",      "미국",     "랜덤상사 B", (1.0, 3.0, 0.50), 0,   0,   "USD", 5.4,    2, (-0.02, 0.05)),
    ]
    for name, origin, sup, (lm, ls, lso), roast, sortc, cur, start_v, n, step in ingredients:
        path = _price_path(rng, start_v, n, step)
        for i, (d, v) in enumerate(path):
            # 마스터 정보(원산지·loss·가공비)는 첫 줄에만, 이후 줄은 단가 이력만 (빈 칸 = 기존 값 유지)
            first = i == 0
            fixed_rate = None
            if cur != "KRW" and i == 1 and name.startswith("피칸"):
                fixed_rate = 1380.0           # 예시: 이 줄만 계약환율로 고정
            wi.append([
                name, origin if first else None, sup if first else None,
                lm if first else None, ls if first else None, lso if first else None,
                None if cur != "KRW" else v, d, "랜덤 예제 견적" if first else None,
                roast or None if first else None, sortc or None if first else None,
                None if cur == "KRW" else cur, None if cur == "KRW" else v, fixed_rate])

    # ------------------------------------------------ 부자재 시트
    wm = wb["부자재"]
    # 이름, 분류, loss, (통화, 시작단가, 변동 횟수, 변동폭)
    materials = [
        ("롤필름(OPP 수입)",   "롤포장지",  3.0, "USD", 0.052, 3, (-0.03, 0.08)),
        ("소포장지(20g용)",    "포장지",    3.0, "KRW", 17.0,  3, (0.00, 0.06)),
        ("소분 봉투(지퍼)",    "소분비",    0.0, "KRW", 65.0,  2, (0.00, 0.05)),
        ("인케이스(PET)",      "인케이스",  3.0, "KRW", 690.0, 3, (0.00, 0.07)),
        ("인케이스(트레이 수입)", "인케이스", 3.0, "VND", 9800.0, 2, (0.00, 0.05)),
        ("카톤박스(8입)",      "카톤박스",  3.0, "KRW", 700.0, 3, (0.00, 0.08)),
        ("카톤박스(12입)",     "카톤박스",  3.0, "KRW", 760.0, 2, (0.00, 0.06)),
        ("스티커 라벨",        "기타",      0.0, "KRW", 4.5,   2, (0.00, 0.10)),
        ("실링 필름(튀르키예산)", "롤포장지", 3.0, "TRY", 0.9,   3, (0.00, 0.10)),
        ("검수 스티커",        "기타",      0.0, "KRW", 2.0,   1, (0.00, 0.00)),
    ]
    for name, cat, loss, cur, start_v, n, step in materials:
        path = _price_path(rng, start_v, n, step)
        for i, (d, v) in enumerate(path):
            first = i == 0
            wm.append([name, cat if first else None, None if cur != "KRW" else v, loss if first else None,
                       "랜덤 예제" if first else None, d, None if cur == "KRW" else cur,
                       None if cur == "KRW" else v, None])

    # ------------------------------------------------ 환율 시트
    wf = wb["환율"]
    for row in _fx_rows(rng):
        wf.append(row)

    # 작성방법 시트 맨 아래에 예제 안내
    g = wb["작성방법"]
    g.append([])
    g.append(["■ 이 파일은 모의 테스트용 랜덤 예제입니다 (실제 가격이 아닙니다)."])
    g.append(["   - 원료 12종(원화·미국·베트남·튀르키예), 부자재 10종, 일별 환율(미국·베트남·튀르키예) 1년치가 들어 있습니다."])
    g.append(["   - 처음 올리면 새 품목은 '신규', 같은 품목의 이후 날짜 단가 줄은 '수정'(단가 이력 추가)으로 표시됩니다."])
    g.append(["     (값이 그대로인 줄은 '변경없음'). 같은 파일을 다시 올리면 전부 '변경없음'으로 나옵니다."])
    g.append(["   - 일부 줄은 일부러 변형했습니다: 피칸 2번째 단가 줄은 '고정환율'(계약환율) 예시입니다."])
    g.append(["   - 등록 후 '가격 추이' 메뉴에서 일별 그래프·변동률·환율 영향을 확인해 보세요."])
    return wb


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb = build(int(sys.argv[1]) if len(sys.argv) > 1 else 20261003)
    wb.save(OUT)
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
