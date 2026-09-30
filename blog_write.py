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
from blog_utils import parse_draft_metadata
from datetime import datetime
import os


PLATFORM_OPTIONS = {"1": "네이버 블로그", "2": "티스토리", "3": "워드프레스"}


def choose_platforms():
    print("\n어디에 발행할 거야? (여러 개면 쉼표로, 예: 1,2)")
    print("  1) 네이버 블로그")
    print("  2) 티스토리")
    print("  3) 워드프레스")
    raw = input("선택: ").strip()
    codes = [c.strip() for c in raw.split(",") if c.strip() in PLATFORM_OPTIONS]
    if not codes:
        codes = ["1"]
    return [PLATFORM_OPTIONS[c] for c in codes]


def print_metadata(meta):
    print("\n📝 발행 정보")
    print(f"  제목: {meta['title']}")
    print(f"  카테고리: {meta['category']}")
    print(f"  태그: {meta['tags']}")
    print(f"  메타설명: {meta['meta_description']}")


def print_platform_guide(platforms, meta):
    if "네이버 블로그" in platforms:
        print("\n[네이버 블로그]")
        print(f"  - 제목란에 위 제목 그대로")
        print(f"  - 카테고리: {meta['category']} 선택(또는 생성)")
        print(f"  - 에디터 하단 태그 입력란에: {meta['tags']}")
        print("  💡 본문 안 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.")
        print("     사진 삽입+ALT: [사진/그래프/지도 제안] 자리에서 사진 삽입 버튼으로 이미지")
        print("     넣기 → 삽입한 사진 클릭 → 뜨는 툴바에서 '대체 텍스트' 클릭 → 팝업에")
        print("     ALT 문구 입력 → '업데이트'.")

    if "티스토리" in platforms:
        print("\n[티스토리]")
        print(f"  - 제목란에 위 제목 그대로")
        print(f"  - 카테고리: {meta['category']} 선택(또는 생성)")
        print(f"  - 에디터 하단 태그 입력란에: {meta['tags']}")
        print("  💡 본문 안 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.")
        print("     사진 삽입+ALT: [사진/그래프/지도 제안] 자리에서 사진 첨부 → 삽입한 사진")
        print("     클릭 → 뜨는 도구모음에서 대체 텍스트 아이콘 클릭 → 팝업에 ALT 문구")
        print("     입력 → 확인.")

    if "워드프레스" in platforms:
        print("\n[워드프레스]")
        print(f"  - 제목란에 위 제목 그대로")
        print(f"  - 카테고리: {meta['category']}")
        print(f"  - 태그: {meta['tags']}")
        print(f"  - SEO 플러그인(Yoast 등)의 메타 설명 칸에: {meta['meta_description']}")
        print("  💡 본문 안 [소제목] 줄은 태그를 지우고 그 블록을 '제목(Heading, H2/H3)'으로 바꿔.")
        print("     사진 삽입+ALT: [사진/그래프/지도 제안] 자리에 이미지 블록 추가 → 사진")
        print("     업로드 → 화면 오른쪽 블록 설정 패널의 'Alt text(대체 텍스트)' 칸에")
        print("     ALT 문구 입력.")


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

    platforms = choose_platforms()

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
    meta = parse_draft_metadata(draft)

    print_metadata(meta)
    print("\n📄 본문")
    print("=" * 50)
    print(meta["body"])
    print("=" * 50)
    print(f"\n[본문 글자 수: {len(meta['body'])}자]")

    print_review(draft)

    os.makedirs("drafts", exist_ok=True)
    filename = f"drafts/{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"주제: {topic}\n\n{draft}")

    print(f"\n💾 저장됨: {filename}")
    print_platform_guide(platforms, meta)
