"""블로그 초안 생성기 — GUI 버전.
사용법: streamlit run blog_app.py
(또는 run_app.bat 더블클릭)
"""
import streamlit as st
from blog_drafter import draft_post, suggest_questions
from blog_reviewer import scan_cliches, scan_structure, review_draft
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

platform_label = st.radio(
    "어디에 발행할 거야?",
    ["네이버 블로그 / 티스토리", "워드프레스", "둘 다"],
)
platform_choice = {"네이버 블로그 / 티스토리": "1", "워드프레스": "2", "둘 다": "3"}[platform_label]

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
    st.divider()
    st.subheader("📄 초안")
    st.text_area("결과 (클릭 후 Ctrl+A, Ctrl+C로 복사)", st.session_state.draft, height=400)
    st.caption(f"글자 수: {len(st.session_state.draft)}자 · 저장됨: {st.session_state.filename}")

    with st.spinner("🔍 자동 점검 중..."):
        cliche_issues = scan_cliches(st.session_state.draft)
        structure_issues = scan_structure(st.session_state.draft)
        ai_result = review_draft(st.session_state.draft)

    st.subheader("📋 점검 결과")

    if cliche_issues:
        st.error("**클리셰/반복 표현**\n" + "\n".join(f"- {i}" for i in cliche_issues))
    else:
        st.success("클리셰/반복 표현: 없음")

    if structure_issues:
        st.error("**글 구조(가독성/이미지)**\n" + "\n".join(f"- {i}" for i in structure_issues))
    else:
        st.success("글 구조(가독성/이미지): 문제 없음")

    ai_labels = {
        "sentence_rhythm": "문장 길이 변주",
        "opinion": "저자 의견",
        "specificity": "사실 구체성",
        "differentiation": "차별화(뻔한 내용 여부)",
    }
    for key, label in ai_labels.items():
        val = (ai_result.get(key) or "").strip()
        if val and val != "없음":
            st.error(f"**{label}**\n{val}")
        else:
            st.success(f"{label}: 문제 없음")

    st.caption("참고: 이건 'AI 티/가독성' 체크일 뿐, 각 플랫폼 자체 검색 알고리즘 점수는 아니야.")

    st.divider()
    st.subheader("📌 발행 전 체크")
    if platform_choice in ("1", "3"):
        st.info(
            "**네이버 블로그 / 티스토리**\n\n"
            "[소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.\n\n"
            "[사진/그래프/지도 제안] 자리에는 실제 이미지를 삽입하고, "
            "ALT로 안내된 문구를 에디터의 대체텍스트 입력창에 그대로 넣어."
        )
    if platform_choice in ("2", "3"):
        st.info(
            "**워드프레스**\n\n"
            "[소제목] 줄은 태그를 지우고 그 블록을 '제목(Heading, H2/H3)'으로 바꿔.\n\n"
            "[사진/그래프/지도 제안] 자리에는 이미지 블록을 넣고, "
            "블록 설정의 '대체 텍스트(Alt text)' 칸에 ALT 문구를 그대로 넣어."
        )
