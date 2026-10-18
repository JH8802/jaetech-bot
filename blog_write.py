"""블로그 초안 작성 — 실제로 쓸 때 이걸 실행하면 됨.
사용법: python blog_write.py

주제를 입력하면 관련 브레인스토밍 질문을 먼저 보여주고,
사실/의견을 입력받아 선택한 플랫폼마다 따로 초안을 만든 뒤(네이버/
티스토리/워드프레스는 문체·소제목 밀도·사진 개수가 실제로 다르게 나옴)
자동 점검까지 돌려서 drafts/ 폴더에 파일로 저장한다.
"""
from blog_drafter import draft_post, suggest_questions
from blog_reviewer import (scan_cliches, scan_structure, scan_seo, scan_health_claims,
                           review_draft, AI_REVIEW_LABELS)
from blog_utils import parse_draft_metadata, load_past_titles, find_keyword_overlap, body_to_html
from datetime import datetime
import os


PLATFORM_OPTIONS = {"1": "네이버 블로그", "2": "티스토리", "3": "워드프레스"}


def choose_platforms():
    print("\n어디에 발행할 거야? (여러 개면 쉼표로, 예: 1,2)")
    print("  1) 네이버 블로그")
    print("  2) 티스토리")
    print("  3) 워드프레스")
    raw = input("선택 (그냥 엔터 = 티스토리): ").strip()
    codes = [c.strip() for c in raw.split(",") if c.strip() in PLATFORM_OPTIONS]
    if not codes:
        codes = ["2"]
    return [PLATFORM_OPTIONS[c] for c in codes]


def print_metadata(meta):
    print("\n📝 발행 정보")
    print(f"  제목: {meta['title']}")
    print(f"  카테고리: {meta['category']}")
    print(f"  태그: {meta['tags']}")
    print(f"  메타설명: {meta['meta_description']}")


def print_platform_guide(platform, meta):
    if platform == "네이버 블로그":
        print(f"  - 제목란에 위 제목 그대로")
        print(f"  - 카테고리: {meta['category']} 선택(또는 생성)")
        print(f"  - 에디터 하단 태그 입력란에: {meta['tags']}")
        print("  💡 본문 안 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.")
        print("     사진 삽입+ALT: [사진/그래프/지도 제안] 자리에서 사진 삽입 버튼으로 이미지")
        print("     넣기 → 삽입한 사진 클릭 → 뜨는 툴바에서 '대체 텍스트' 클릭 → 팝업에")
        print("     ALT 문구 입력 → '업데이트'.")

    elif platform == "티스토리":
        print(f"  - 제목란에 위 제목 그대로")
        print(f"  - 카테고리: {meta['category']} 선택(또는 생성)")
        print(f"  - 에디터 하단 태그 입력란에: {meta['tags']}")
        print(f"  - 구글 검색결과 설명용 메타설명: {meta['meta_description']}")
        print("    (티스토리에 입력 칸이 있으면 거기에, 없으면 첫 문단에 핵심 키워드가 들어갔는지 확인)")
        print("  💡 본문 안 [소제목] 줄은 태그를 지우고, 굵게만 하지 말고 에디터 문단 서식")
        print("     (제목1/제목2 등 '제목' 계열)으로 지정해 — 구글은 제목 태그 구조를 읽어.")
        print("     사진 삽입+ALT: [사진/그래프/지도 제안] 자리에서 사진 첨부 → 삽입한 사진")
        print("     클릭 → 뜨는 도구모음에서 대체 텍스트 아이콘 클릭 → 팝업에 ALT 문구")
        print("     입력 → 확인.")
        print("  💡 글 주소(최초 1회만): 블로그 관리 → 블로그 설정에서 글 주소 형식을 숫자 대신")
        print("     '문자'로 바꿀 수 있어 (메뉴 위치는 직접 확인). 기존 글 주소가 바뀔 수 있으니 초반에.")

    elif platform == "워드프레스":
        print(f"  - 제목란에 위 제목 그대로")
        print(f"  - 카테고리: {meta['category']}")
        print(f"  - 태그: {meta['tags']}")
        print(f"  - SEO 플러그인(Yoast 등)의 메타 설명 칸에: {meta['meta_description']}")
        print(f"  - 오른쪽 설정 패널의 고유주소(URL/슬러그) 칸에: {meta['slug']}")
        print("  💡 본문 안 [소제목] 줄은 태그를 지우고 그 블록을 '제목(Heading, H2/H3)'으로 바꿔.")
        print("     사진 삽입+ALT: [사진/그래프/지도 제안] 자리에 이미지 블록 추가 → 사진")
        print("     업로드 → 화면 오른쪽 블록 설정 패널의 'Alt text(대체 텍스트)' 칸에")
        print("     ALT 문구 입력.")

    print("  ⚠️ 공통: 사진 파일명은 [사진 제안]의 '파일명'대로 바꿔서 업로드.")
    print("     [내부링크 제안]은 실제 발행된 글일 때만 링크, 아니면 줄째로 삭제.")
    print("     [출처 필요]는 근거를 넣거나 그 주장을 빼고, 대괄호 태그는 전부 지웠는지 확인.")


def get_lines(prompt_text):
    print(prompt_text)
    lines = []
    while True:
        line = input(f"  [{len(lines) + 1}] ").strip()
        if not line:
            break
        lines.append(line)
    return lines


def print_review(draft, meta, platform, target_keyword):
    print("\n🔍 자동 점검 중...")
    cliche_issues = scan_cliches(draft)
    structure_issues = scan_structure(draft)
    seo_issues = scan_seo(meta, platform, target_keyword)
    ai_result = review_draft(draft)

    total = 3 + len(AI_REVIEW_LABELS)  # 클리셰 + 구조 + SEO + AI 5개
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

    if seo_issues:
        print("❌ 검색 최적화(키워드/소제목/메타설명/출처)")
        for issue in seo_issues:
            print(f"   - {issue}")
    else:
        print("✅ 검색 최적화(키워드/소제목/메타설명/출처): 문제 없음")
        passed += 1

    claims = scan_health_claims(meta["body"])
    if claims:
        print("⚠️ 표시광고 표현 확인 필요 (설명 문맥이면 괜찮음 — 통과/실패 집계엔 안 들어감)")
        for c in claims:
            print(f"   - {c}")
        print("   협찬·제공받은 제품이면 글 첫머리에 그 사실을 밝혀야 함 (공정위 추천·보증 심사지침).")

    if not ai_result:
        print("⚠️ AI 점검 실패 (네트워크 문제일 수 있음) — 아래 AI 항목은 점검 안 됨")
    for key, label in AI_REVIEW_LABELS.items():
        if not ai_result:
            break
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
    if "티스토리" in platforms and "워드프레스" in platforms:
        print("\n⚠️ 중복 콘텐츠 주의 — 같은 주제를 티스토리와 워드프레스에 둘 다 올리면 내용이 거의 같아서, 구글이 하나만 검색에 보여주고 나머지는 거의 숨겨 — 두 블로그가 서로 경쟁하게 돼. 원칙은 '한 주제는 한 블로그'. 굳이 둘 다 쓸 거면 주제나 관점을 확실히 나눠서 (예: 소비자 관점 / 실무자 관점) 따로 생성해.")

    topic = input("\n주제: ").strip()
    target_keyword = input("타깃 키워드 (잡고 싶은 검색어, 없으면 엔터 — AI가 고름): ").strip()

    print("\n💭 관련 질문 만드는 중...")
    questions = suggest_questions(topic)
    if questions:
        print("떠오르는 대로 적어봐 (전부 답할 필요 없음):")
        for q in questions:
            print(f"  - {q}")

    key_points = get_lines("\n실제 경험/숫자/사례를 한 줄씩 입력해 (다 넣었으면 빈 줄에서 엔터):")

    if not key_points:
        print("\n❌ 사실/경험을 최소 1개는 입력해야 해. 다시 실행해줘.")
        raise SystemExit(1)

    sources = get_lines("\n참고 자료/출처를 한 줄씩 (예: 식약처 ○○ 고시 / 없으면 바로 엔터):")

    personal_take = input("\n본인 의견/입장 (없으면 그냥 엔터): ").strip()

    os.makedirs("drafts", exist_ok=True)

    for platform in platforms:
        print(f"\n{'#' * 50}")
        print(f"# {platform}")
        print(f"{'#' * 50}")

        print(f"\n⏳ {platform}용 초안 생성 중...\n")
        try:
            draft = draft_post(
                topic, key_points, personal_take, platform=platform,
                target_keyword=target_keyword, sources=sources,
                past_titles=load_past_titles(platform),
            )
        except Exception as e:
            print(f"❌ {platform} 초안 생성 실패: {e}")
            print("   (네트워크 문제일 수 있어 — 다음 플랫폼으로 넘어감)")
            continue
        meta = parse_draft_metadata(draft)

        print_metadata(meta)
        print("\n📄 본문")
        print("=" * 50)
        print(meta["body"])
        print("=" * 50)
        print(f"\n[본문 글자 수: {len(meta['body'])}자]")

        print_review(draft, meta, platform, target_keyword)

        slug = platform.replace(" ", "")
        filename = f"drafts/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"주제: {topic}\n플랫폼: {platform}\n타깃 키워드: {target_keyword}\n\n{draft}")

        print(f"\n💾 저장됨: {filename}")

        if platform in ("티스토리", "워드프레스"):
            html_filename = filename.replace(".txt", ".html")
            with open(html_filename, "w", encoding="utf-8") as f:
                f.write(body_to_html(meta["body"]))
            print(f"🧩 HTML 버전: {html_filename}")
            print("   (메모장으로 열어 전체 복사 → 티스토리 HTML 모드 / 워드프레스 코드 편집기에 붙여넣기."
                  " 소제목이 제목(H2) 서식으로 들어가 있음)")

        overlap = find_keyword_overlap(platform, target_keyword, exclude=[filename])
        if overlap:
            print(f"\n⚠️ 키워드 중복 주의 — '{target_keyword}'로 이미 쓴 {platform} 글:")
            for t in overlap:
                print(f"   - {t}")
            print("   같은 키워드 글끼리 검색 순위를 나눠 먹음. 이미 발행한 글이면 키워드를 더 구체적으로")
            print("   바꾸거나 기존 글 보강을 고려. 같은 글의 이전 초안일 뿐이면 무시해도 됨.")
        print(f"\n📌 발행 체크리스트 [{platform}]")
        print_platform_guide(platform, meta)
