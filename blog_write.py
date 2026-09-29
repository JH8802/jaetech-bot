"""블로그 초안 작성 — 실제로 쓸 때 이걸 실행하면 됨.
사용법: python blog_write.py

주제를 입력하면 관련 브레인스토밍 질문을 먼저 보여주고,
사실/의견을 입력받아 초안을 만든 뒤 자동 점검까지 돌려서
drafts/ 폴더에 파일로 저장한다. 초안 자체는 네이버/티스토리/워드프레스
어디든 똑같이 쓸 수 있고, 발행할 곳을 고르면 붙여넣은 뒤 뭘 해야
하는지(제목 처리, ALT 입력 위치 등)만 그에 맞게 안내해준다.
"""
from blog_drafter import draft_post, suggest_questions
from blog_reviewer import scan_cliches, scan_structure, review_draft, AI_REVIEW_LABELS
from datetime import datetime
import os

PLATFORM_GUIDES = {
    "1": {
        "label": "네이버 블로그 / 티스토리",
        "guide": (
            "💡 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.\n"
            "   [사진/그래프/지도 제안] 자리에는 실제 이미지를 삽입하고,\n"
            "   ALT로 안내된 문구를 에디터의 대체텍스트 입력창에 그대로 넣어."
        ),
    },
    "2": {
        "label": "워드프레스",
        "guide": (
            "💡 [소제목] 줄은 태그를 지우고 그 블록을 '제목(Heading, H2/H3)'으로 바꿔.\n"
            "   [사진/그래프/지도 제안] 자리에는 이미지 블록을 넣고,\n"
            "   블록 설정의 '대체 텍스트(Alt text)' 칸에 ALT 문구를 그대로 넣어."
        ),
    },
}


def choose_platform():
    print("\n어디에 발행할 거야?")
    print("  1) 네이버 블로그 / 티스토리")
    print("  2) 워드프레스")
    print("  3) 둘 다 (같은 초안으로 각각 발행)")
    choice = input("선택: ").strip()
    return choice if choice in ("1", "2", "3") else "1"


def print_platform_guide(choice):
    if choice == "3":
        for key in ("1", "2"):
            print(f"\n[{PLATFORM_GUIDES[key]['label']}]")
            print(PLATFORM_GUIDES[key]["guide"])
    else:
        guide = PLATFORM_GUIDES.get(choice, PLATFORM_GUIDES["1"])
        print(guide["guide"])


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
    structure_issues = scan_structure(draft)
    ai_result = review_draft(draft)

    total = 2 + len(AI_REVIEW_LABELS)  # 클리셰 + 구조 + AI 5개
    passed = 0

    print("\n📋 점검 결과")

    if cliche_issues:
        print("❌ 클리셰/반복 표현")
        for issue in cliche_issues:
            print(f"   - {issue}")
    else:
        print("✅ 클리셰/반복 표현: 없음")
        passed += 1

    if structure_issues:
        print("❌ 글 구조(가독성/이미지)")
        for issue in structure_issues:
            print(f"   - {issue}")
    else:
        print("✅ 글 구조(가독성/이미지): 문제 없음")
        passed += 1

    for key, label in AI_REVIEW_LABELS.items():
        val = (ai_result.get(key) or "").strip()
        if val and val != "없음":
            print(f"❌ {label}: {val}")
        else:
            print(f"✅ {label}: 문제 없음")
            passed += 1

    print(f"\n→ {passed}/{total} 항목 통과")
    print("(참고: 이건 'AI 티/가독성' 체크일 뿐, 각 플랫폼 자체 검색 알고리즘 점수는 아니야.)")


if __name__ == "__main__":
    print("=== 블로그 초안 생성 === (주제는 뭐든 상관없음)")

    platform_choice = choose_platform()

    topic = input("\n주제: ").strip()

    print("\n💭 관련 질문 만드는 중...")
    questions = suggest_questions(topic)
    if questions:
        print("떠오르는 대로 적어봐 (전부 답할 필요 없음):")
        for q in questions:
            print(f"  - {q}")

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
    print_platform_guide(platform_choice)
