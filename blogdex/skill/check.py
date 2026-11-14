"""블덱스 초안 점검: PC 블덱스라이터와 같은 품질 점검(eval_style)을 원고 파일에 돌린다.

사용법: python scripts/check.py --kind food --keywords "키워드1,키워드2" --memo "메모" draft.txt
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_style  # noqa: E402
import postprocess  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--kind", choices=["food", "hotel"], default="food")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--memo", default="")
    a = ap.parse_args(argv)
    body = open(a.draft, encoding="utf-8").read().replace("\r\n", "\n")
    body = re.sub(r"\[\s*사진\s*(\d+)\s*\]", r"<사진\1>", body)  # [사진 1] 로 써도 사진 자리로 셈
    keywords = [k.strip() for k in a.keywords.split(",") if k.strip()]
    res = eval_style.evaluate(a.kind, body, keywords, memo=a.memo, ad_check=True)
    print(f"글자수: 공백 포함 {postprocess.count_chars_ws(body):,}자 · 공백 제외 {postprocess.count_chars(body):,}자")
    paras = postprocess.split_paragraphs(body)
    print("고지 문단(맨 위): " + ("있음" if paras and postprocess.is_disclosure_paragraph(paras[0]) else "없음 - 첫 문단에 내돈내산·협찬·제휴 고지를 넣을 것"))
    print(f"품질 점검 {res['ok_count']}/{res['total']} 통과\n")
    print("| 결과 | 항목 | 값 | 기준 |")
    print("|---|---|---|---|")
    for c in res["checks"]:
        print(f"| {'통과' if c['ok'] else '주의'} | {c['label']} | {c['value']} | {c['target']} |")
    if res["issues"]:
        print("\n고칠 점:")
        for i in res["issues"]:
            print(f"- {i}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
