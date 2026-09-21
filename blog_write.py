"""블로그 초안 작성 — 실제로 쓸 때 이걸 실행하면 됨.
사용법: python blog_write.py

주제/사실/의견을 입력하면 초안을 만들고, 자동 점검까지 돌린 뒤
drafts/ 폴더에 파일로 저장한다. 저장된 파일을 열어서 다듬은 뒤
네이버/티스토리 에디터에 그대로 복사해서 붙여넣으면 됨.
"""
from blog_drafter import draft_post
from blog_reviewer import scan_cliches, review_draft
from datetime import datetime
import os

GUIDE_QUESTIONS = {
    "1": {
        "label": "식품 QA / 품질관리",
        "questions": [
            "최근 검수·감사에서 실제로 걸렸던 사례가 있어? (제품명은 가려도 됨)",
            "관련된 기준이 있어? (식약처 고시, 건강기능식품법, EFSA 등)",
            "숫자로 표현할 수 있는 게 있어? (불량률, 클레임 건수, 기준치 등)",
            "소비자가 오해하기 쉬운 포인트는?",
            "경쟁 채널은 이 부분을 다르게 하고 있어?",
        ],
    },
    "2": {
        "label": "투자 / 재테크",
        "questions": [
            "최근에 직접 겪은 투자 판단이나 실수/성공 사례가 있어?",
            "관련 수치가 있어? (금리, 수익률, 거래량 등)",
            "시장 컨센서스랑 본인 생각이 다른 지점이 있어?",
            "몇 년 전이랑 비교해서 달라진 게 있어?",
            "사람들이 이 주제에서 자주 놓치는 리스크는?",
        ],
    },
    "3": {
        "label": "기타 주제 (범용)",
        "questions": [
            "왜 지금 이 얘기를 하고 싶어?",
            "직접 겪은 일이나 관련 경험이 있어?",
            "구체적인 숫자나 사실이 있어? (없어도 됨)",
            "이 주제에서 남들과 다른 본인만의 시각이 있어?",
            "이 글 읽고 나서 독자가 뭘 얻어가면 좋겠어?",
        ],
    },
}


def show_guide_questions():
    print("\n주제는 뭐든 상관없어. 분야를 고르면 기억 떠올리는 데 도움 되는 질문을 보여줄게.")
    print("  1) 식품 QA / 품질관리")
    print("  2) 투자 / 재테크")
    print("  3) 기타 주제 (범용 질문)")
    print("  4) 질문 없이 바로 입력할래")
    choice = input("선택: ").strip()
    guide = GUIDE_QUESTIONS.get(choice)
    if guide:
        print(f"\n[{guide['label']}] 떠오르는 대로 적어봐 (전부 답할 필요 없음):")
        for q in guide["questions"]:
            print(f"  - {q}")


def get_key_points():
    print("\n실제 경험/숫자/사례를 한 줄씩 입력해 (다 넣었으면 빈 줄에서 엔터):")
    points = []
    while True:
        line = input(f"  [{len(points) + 1}] ").strip()
        if not line:
            break
        points.append(line)
    return points


def print_review(draft):
    print("\n🔍 자동 점검 중...")
    cliche_issues = scan_cliches(draft)
    ai_result = review_draft(draft)

    ai_labels = {
        "sentence_rhythm": "문장 길이 변주",
        "opinion": "저자 의견",
        "specificity": "사실 구체성",
    }
    total = 1 + len(ai_labels)
    passed = 0 if cliche_issues else 1

    print("\n📋 점검 결과")
    if cliche_issues:
        print("❌ 클리셰/반복 표현")
        for issue in cliche_issues:
            print(f"   - {issue}")
    else:
        print("✅ 클리셰/반복 표현: 없음")

    for key, label in ai_labels.items():
        val = (ai_result.get(key) or "").strip()
        if val and val != "없음":
            print(f"❌ {label}: {val}")
        else:
            print(f"✅ {label}: 문제 없음")
            passed += 1

    print(f"\n→ {passed}/{total} 항목 통과")


if __name__ == "__main__":
    print("=== 블로그 초안 생성 ===")

    show_guide_questions()

    topic = input("\n주제: ").strip()
    key_points = get_key_points()

    if not key_points:
        print("\n❌ 사실/경험을 최소 1개는 입력해야 해. 다시 실행해줘.")
        raise SystemExit(1)

    personal_take = input("\n본인 의견/입장 (없으면 그냥 엔터): ").strip()

    print("\n⏳ 초안 생성 중...\n")
    draft = draft_post(topic, key_points, personal_take)

    print("=" * 50)
    print(draft)
    print("=" * 50)
    print(f"\n[글자 수: {len(draft)}자]")

    print_review(draft)

    os.makedirs("drafts", exist_ok=True)
    filename = f"drafts/{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"주제: {topic}\n\n{draft}")

    print(f"\n💾 저장됨: {filename}")
    print("💡 [소제목] 표시된 줄은 에디터에서 굵게/크게 처리하고, 태그는 지운 뒤 붙여넣어.")
    print("이 파일 열어서 다듬은 다음, 네이버/티스토리 에디터에 복사해서 붙여넣으면 돼.")
