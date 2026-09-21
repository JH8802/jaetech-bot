"""블로그 초안 작성 — 실제로 쓸 때 이걸 실행하면 됨.
사용법: python blog_write.py

주제를 입력하면 관련 브레인스토밍 질문을 먼저 보여주고,
사실/의견을 입력받아 초안을 만든 뒤 자동 점검까지 돌려서
drafts/ 폴더에 파일로 저장한다. 저장된 파일을 열어서 다듬은 뒤
네이버/티스토리 에디터에 그대로 복사해서 붙여넣으면 됨.
"""
from blog_drafter import draft_post, suggest_questions
from blog_reviewer import scan_cliches, scan_structure, review_draft
from datetime import datetime
import os


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

    ai_labels = {
        "sentence_rhythm": "문장 길이 변주",
        "opinion": "저자 의견",
        "specificity": "사실 구체성",
    }
    total = 2 + len(ai_labels)  # 클리셰 + 구조 + AI 3개
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

    for key, label in ai_labels.items():
        val = (ai_result.get(key) or "").strip()
        if val and val != "없음":
            print(f"❌ {label}: {val}")
        else:
            print(f"✅ {label}: 문제 없음")
            passed += 1

    print(f"\n→ {passed}/{total} 항목 통과")
    print("(참고: 이건 'AI 티/가독성' 체크일 뿐, 네이버·티스토리 자체 검색 알고리즘 점수는 아니야.)")


if __name__ == "__main__":
    print("=== 블로그 초안 생성 === (주제는 뭐든 상관없음)")

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
    print("💡 [소제목]은 에디터에서 굵게/크게 처리, [사진/그래프/지도 제안]은 실제로")
    print("   삽입하면서 안내된 ALT 텍스트를 입력하고, 태그 자체는 지운 뒤 붙여넣어.")
