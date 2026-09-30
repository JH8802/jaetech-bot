"""블로그 초안 생성기 — GUI 버전.
사용법: streamlit run blog_app.py
(또는 run_app.bat 더블클릭)
"""
import streamlit as st
from blog_drafter import draft_post, suggest_questions
from blog_reviewer import scan_cliches, scan_structure, review_draft, AI_REVIEW_LABELS
from blog_utils import parse_draft_metadata
from datetime import datetime
import os

st.set_page_config(page_title="블로그 초안 생성기", page_icon="✍️")

if "questions" not in st.session_state:
    st.session_state.questions = []
if "draft" not in st.session_state:
    st.session_state.draft = None
if "filename" not in st.session_state:
    st.session_state.filename = None

st.title("✍️ 블로그 초안 생성기")
st.caption("주제는 뭐든 상관없음 · 발행은 직접, 초안 생성 + 자동 점검까지만")

if st.button("🔄 새로 시작"):
    st.session_state.questions = []
    st.session_state.draft = None
    st.session_state.filename = None
    st.rerun()

st.divider()

platforms = st.multiselect(
    "어디에 발행할 거야? (여러 개 선택 가능)",
    ["네이버 블로그", "티스토리", "워드프레스"],
    default=["네이버 블로그"],
)

topic = st.text_input("주제", placeholder="예: 홈쇼핑 유산균 표시광고, 뭐가 문제인가")

if st.button("💭 관련 질문 만들기"):
    if not topic.strip():
        st.warning("주제를 먼저 입력해줘.")
    else:
        with st.spinner("질문 만드는 중..."):
            st.session_state.questions = suggest_questions(topic)

if st.session_state.questions:
    with st.expander("💭 떠오르는 대로 참고해봐 (전부 답할 필요 없음)", expanded=True):
        for q in st.session_state.questions:
            st.write(f"- {q}")

key_points_text = st.text_area(
    "실제 경험/숫자/사례 (한 줄에 하나씩)",
    height=150,
    placeholder="예)\n균주명 없이 보장균수만 강조하는 표시 사례를 실무에서 자주 봄\n식약처 기준상 효능 표시엔 건강기능식품 인증이 필요함",
)
personal_take = st.text_input("본인 의견/입장 (없으면 비워둬도 됨)")

if st.button("✍️ 초안 생성", type="primary"):
    key_points = [line.strip() for line in key_points_text.split("\n") if line.strip()]
    if not topic.strip():
        st.error("주제를 입력해줘.")
    elif not key_points:
        st.error("사실/경험을 최소 1개는 입력해줘.")
    else:
        with st.spinner("⏳ 초안 생성 중..."):
            draft = draft_post(topic, key_points, personal_take)
        st.session_state.draft = draft

        os.makedirs("drafts", exist_ok=True)
        filename = f"drafts/{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"주제: {topic}\n\n{draft}")
        st.session_state.filename = filename

if st.session_state.draft:
    draft = st.session_state.draft
    meta = parse_draft_metadata(draft)

    with st.spinner("🔍 자동 점검 중..."):
        cliche_issues = scan_cliches(draft)
        structure_issues = scan_structure(draft)
        ai_result = review_draft(draft)

    st.divider()
    st.subheader("📝 발행 정보")
    st.text_input("제목", meta["title"])
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("카테고리", meta["category"])
    with col2:
        st.text_input("태그 (쉼표로 구분)", meta["tags"])
    if "워드프레스" in platforms:
        st.text_area("메타 설명 (워드프레스 SEO 플러그인의 '메타 설명' 칸에)", meta["meta_description"], height=70)
    else:
        with st.expander("메타 설명 (참고용 — 네이버/티스토리는 보통 안 씀)"):
            st.write(meta["meta_description"])

    st.subheader("📄 본문")
    st.text_area("본문 (클릭 후 Ctrl+A, Ctrl+C로 복사)", meta["body"], height=400)
    st.caption(f"본문 글자 수: {len(meta['body'])}자 · 저장됨: {st.session_state.filename}")

    st.subheader("📋 점검 결과")

    if cliche_issues:
        st.error("**클리셰/반복 표현**\n" + "\n".join(f"- {i}" for i in cliche_issues))
    else:
        st.success("클리셰/반복 표현: 없음")

    if structure_issues:
        st.error("**글 구조(가독성/이미지)**\n" + "\n".join(f"- {i}" for i in structure_issues))
    else:
        st.success("글 구조(가독성/이미지): 문제 없음")

    for key, label in AI_REVIEW_LABELS.items():
        val = (ai_result.get(key) or "").strip()
        if val and val != "없음":
            st.error(f"**{label}**\n{val}")
        else:
            st.success(f"{label}: 문제 없음")

    st.caption("참고: 이건 'AI 티/가독성' 체크일 뿐, 각 플랫폼 자체 검색 알고리즘 점수는 아니야.")

    st.divider()
    st.subheader("📌 발행 체크리스트")
    if not platforms:
        st.warning("위에서 발행할 곳을 하나 이상 선택해줘.")
    if "네이버 블로그" in platforms:
        st.info(
            "**네이버 블로그**\n\n"
            f"- 제목란에 위 제목 그대로 붙여넣기\n"
            f"- 카테고리: **{meta['category']}** 선택(또는 생성)\n"
            f"- 에디터 하단 태그 입력란에: **{meta['tags']}**\n\n"
            "본문 안 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.\n\n"
            "**사진 삽입 + ALT 입력**: [사진/그래프/지도 제안] 태그가 있던 그 자리에서 "
            "사진 삽입 버튼으로 이미지 넣기 → 삽입한 사진을 클릭하면 뜨는 툴바에서 "
            "'대체 텍스트' 클릭 → 팝업에 안내된 ALT 문구 입력 → '업데이트'."
        )
    if "티스토리" in platforms:
        st.info(
            "**티스토리**\n\n"
            f"- 제목란에 위 제목 그대로 붙여넣기\n"
            f"- 카테고리: **{meta['category']}** 선택(또는 생성)\n"
            f"- 에디터 하단 태그 입력란에: **{meta['tags']}**\n\n"
            "본문 안 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.\n\n"
            "**사진 삽입 + ALT 입력**: [사진/그래프/지도 제안] 태그가 있던 그 자리에서 "
            "사진 첨부 → 삽입한 사진을 클릭하면 뜨는 도구모음에서 대체 텍스트 아이콘 클릭 → "
            "팝업에 안내된 ALT 문구 입력 → 확인. (HTML 모드로 바꾸면 "
            "`<img alt=\"...\">`로 직접 넣는 것도 가능하지만, 위 방법이 더 쉬움)"
        )
    if "워드프레스" in platforms:
        st.info(
            "**워드프레스**\n\n"
            f"- 제목란에 위 제목 그대로\n"
            f"- 카테고리: **{meta['category']}**\n"
            f"- 태그: **{meta['tags']}**\n"
            f"- SEO 플러그인(Yoast 등)의 메타 설명 칸에 위 메타 설명 붙여넣기\n\n"
            "본문 안 [소제목] 줄은 태그를 지우고 그 블록을 '제목(Heading, H2/H3)'으로 바꿔.\n\n"
            "**사진 삽입 + ALT 입력**: [사진/그래프/지도 제안] 태그가 있던 그 자리에 "
            "이미지 블록을 추가하고 사진을 업로드 → 화면 오른쪽 블록 설정 패널의 "
            "'Alt text(대체 텍스트)' 칸에 안내된 ALT 문구 입력."
        )
