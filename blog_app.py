"""블로그 초안 생성기 — GUI 버전.
사용법: streamlit run blog_app.py
(또는 run_app.bat 더블클릭)

플랫폼을 여러 개 고르면 그 개수만큼 초안을 따로 생성한다
(네이버/티스토리/워드프레스는 문체·소제목 밀도·사진 개수가 실제로 다르게 나옴).
"""
import streamlit as st
from blog_drafter import draft_post, suggest_questions
from blog_reviewer import scan_cliches, scan_structure, scan_seo, review_draft, AI_REVIEW_LABELS
from blog_utils import parse_draft_metadata, load_past_titles
from datetime import datetime
import os

st.set_page_config(page_title="블로그 초안 생성기", page_icon="✍️")

if "questions" not in st.session_state:
    st.session_state.questions = []
if "drafts" not in st.session_state:
    st.session_state.drafts = {}  # {플랫폼명: draft 텍스트}
if "filenames" not in st.session_state:
    st.session_state.filenames = {}  # {플랫폼명: 저장 경로}
if "target_keyword" not in st.session_state:
    st.session_state.target_keyword = ""  # 생성 당시 키워드 (점검에 사용)

st.title("✍️ 블로그 초안 생성기")
st.caption("주제는 뭐든 상관없음 · 발행은 직접, 초안 생성 + 자동 점검까지만")
st.caption("⚠️ 플랫폼을 여러 개 고르면 그 개수만큼 Claude를 호출해 — 비용도 그만큼 늘어남")

if st.button("🔄 새로 시작"):
    st.session_state.questions = []
    st.session_state.drafts = {}
    st.session_state.filenames = {}
    st.session_state.target_keyword = ""
    st.rerun()

st.divider()

platforms = st.multiselect(
    "어디에 발행할 거야? (여러 개 선택 가능 — 선택한 만큼 따로 생성됨)",
    ["네이버 블로그", "티스토리", "워드프레스"],
    default=["티스토리"],
)

topic = st.text_input("주제", placeholder="예: 홈쇼핑 유산균 표시광고, 뭐가 문제인가")
target_keyword = st.text_input(
    "타깃 키워드 (이 글로 잡고 싶은 검색어 — 비우면 AI가 고름)",
    placeholder="예: 유산균 보장균수",
    help="구글 검색창에 주제를 쳐보고 자동완성에 뜨는 검색어 중 하나를 고르면 좋아.",
)

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
sources_text = st.text_area(
    "참고 자료/출처 (한 줄에 하나씩, 선택)",
    height=90,
    placeholder="예)\n식약처 「건강기능식품의 기준 및 규격」 고시\nEFSA 프로바이오틱스 건강강조표시 의견서(2009)",
    help="건강·돈 주제는 구글이 근거를 엄격하게 봐. 여기 적은 것만 본문에 인용하고, 근거가 필요한데 없으면 [출처 필요]로 표시돼.",
)
personal_take = st.text_input("본인 의견/입장 (없으면 비워둬도 됨)")

if st.button("✍️ 초안 생성", type="primary"):
    key_points = [line.strip() for line in key_points_text.split("\n") if line.strip()]
    sources = [line.strip() for line in sources_text.split("\n") if line.strip()]
    if not topic.strip():
        st.error("주제를 입력해줘.")
    elif not key_points:
        st.error("사실/경험을 최소 1개는 입력해줘.")
    elif not platforms:
        st.error("발행할 곳을 하나 이상 선택해줘.")
    else:
        os.makedirs("drafts", exist_ok=True)
        drafts, filenames = {}, {}
        for platform in platforms:
            with st.spinner(f"⏳ {platform}용 초안 생성 중..."):
                try:
                    draft = draft_post(
                        topic, key_points, personal_take, platform=platform,
                        target_keyword=target_keyword.strip(), sources=sources,
                        past_titles=load_past_titles(platform),
                    )
                except Exception as e:
                    st.error(f"❌ {platform} 초안 생성 실패: {e}\n(네트워크 문제일 수 있어 — 아래 '초안 생성'을 다시 눌러봐)")
                    continue
            drafts[platform] = draft

            slug = platform.replace(" ", "")
            filename = f"drafts/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"주제: {topic}\n플랫폼: {platform}\n\n{draft}")
            filenames[platform] = filename

        st.session_state.drafts = drafts
        st.session_state.filenames = filenames
        st.session_state.target_keyword = target_keyword.strip()

if st.session_state.drafts:
    st.divider()
    tabs = st.tabs(list(st.session_state.drafts.keys()))

    for tab, platform in zip(tabs, st.session_state.drafts.keys()):
        draft = st.session_state.drafts[platform]
        meta = parse_draft_metadata(draft)

        with tab:
            with st.spinner("🔍 자동 점검 중..."):
                cliche_issues = scan_cliches(draft)
                structure_issues = scan_structure(draft)
                seo_issues = scan_seo(meta, platform, st.session_state.target_keyword)
                ai_result = review_draft(draft)

            st.subheader("📝 발행 정보")
            st.text_input("제목", meta["title"], key=f"title_{platform}")
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("카테고리", meta["category"], key=f"category_{platform}")
            with col2:
                st.text_input("태그 (쉼표로 구분)", meta["tags"], key=f"tags_{platform}")
            if platform == "워드프레스":
                st.text_area(
                    "메타 설명 (워드프레스 SEO 플러그인의 '메타 설명' 칸에)",
                    meta["meta_description"], height=70, key=f"meta_{platform}",
                )
                st.text_input(
                    "글 주소/슬러그 (오른쪽 설정 패널의 '고유주소(URL)' 칸에)",
                    meta["slug"], key=f"slug_{platform}",
                )
            elif platform == "티스토리":
                st.text_area(
                    "메타 설명 (구글 검색결과 설명용 — 티스토리 설정/에디터에 칸이 있으면 거기에, 없으면 첫 문단에 녹이기)",
                    meta["meta_description"], height=70, key=f"meta_{platform}",
                )
            else:
                with st.expander("메타 설명 (참고용 — 이 플랫폼은 보통 안 씀)"):
                    st.write(meta["meta_description"])

            st.subheader("📄 본문")
            st.text_area(
                "본문 (클릭 후 Ctrl+A, Ctrl+C로 복사)",
                meta["body"], height=400, key=f"body_{platform}",
            )
            st.caption(f"본문 글자 수: {len(meta['body'])}자 · 저장됨: {st.session_state.filenames[platform]}")

            st.subheader("📋 점검 결과")
            if cliche_issues:
                st.error("**클리셰/반복 표현**\n" + "\n".join(f"- {i}" for i in cliche_issues))
            else:
                st.success("클리셰/반복 표현: 없음")

            if structure_issues:
                st.error("**글 구조(가독성/이미지)**\n" + "\n".join(f"- {i}" for i in structure_issues))
            else:
                st.success("글 구조(가독성/이미지): 문제 없음")

            if seo_issues:
                st.error("**검색 최적화(키워드/소제목/메타설명/출처)**\n" + "\n".join(f"- {i}" for i in seo_issues))
            else:
                st.success("검색 최적화(키워드/소제목/메타설명/출처): 문제 없음")

            for key, label in AI_REVIEW_LABELS.items():
                val = (ai_result.get(key) or "").strip()
                if val and val != "없음":
                    st.error(f"**{label}**\n{val}")
                else:
                    st.success(f"{label}: 문제 없음")

            st.caption("참고: 이건 'AI 티/가독성' 체크일 뿐, 이 플랫폼 자체 검색 알고리즘 점수는 아니야.")

            st.divider()
            st.subheader("📌 발행 체크리스트")

            if platform == "네이버 블로그":
                st.info(
                    f"- 제목란에 위 제목 그대로 붙여넣기\n"
                    f"- 카테고리: **{meta['category']}** 선택(또는 생성)\n"
                    f"- 에디터 하단 태그 입력란에: **{meta['tags']}**\n\n"
                    "본문 안 [소제목] 줄은 태그를 지우고 에디터에서 직접 굵게/크게 처리해.\n\n"
                    "**사진 삽입 + ALT 입력**: [사진/그래프/지도 제안] 태그가 있던 그 자리에서 "
                    "사진 삽입 버튼으로 이미지 넣기 → 삽입한 사진을 클릭하면 뜨는 툴바에서 "
                    "'대체 텍스트' 클릭 → 팝업에 안내된 ALT 문구 입력 → '업데이트'."
                )
            elif platform == "티스토리":
                st.info(
                    f"- 제목란에 위 제목 그대로 붙여넣기\n"
                    f"- 카테고리: **{meta['category']}** 선택(또는 생성)\n"
                    f"- 에디터 하단 태그 입력란에: **{meta['tags']}**\n"
                    "- 구글 SEO: 첫 문단에 핵심 키워드와 이 글이 답하는 질문이 들어갔는지 확인 "
                    "(구글이 검색결과 설명으로 첫 문단을 가져올 수 있음)\n\n"
                    "본문 안 [소제목] 줄은 태그를 지우고, 굵게만 하지 말고 에디터의 문단 서식"
                    "(제목1/제목2 등 '제목' 계열)으로 지정해 — 구글은 제목 태그 구조를 읽어서 "
                    "글 내용을 파악해. (※ 티스토리 에디터별 메뉴 이름은 달라질 수 있음)\n\n"
                    "**사진 삽입 + ALT 입력**: [사진/그래프/지도 제안] 태그가 있던 그 자리에서 "
                    "사진 첨부 → 삽입한 사진을 클릭하면 뜨는 도구모음에서 대체 텍스트 아이콘 클릭 → "
                    "팝업에 안내된 ALT 문구 입력 → 확인. (HTML 모드로 바꾸면 "
                    "`<img alt=\"...\">`로 직접 넣는 것도 가능하지만, 위 방법이 더 쉬움)\n\n"
                    "**글 주소(최초 1회만)**: 티스토리 블로그 관리 → 블로그 설정에서 글 주소 "
                    "형식을 숫자 대신 '문자'(제목이 주소가 됨)로 바꿀 수 있어 — 메뉴 위치는 "
                    "바뀔 수 있으니 직접 확인해줘. 이미 쓴 글 주소가 바뀔 수 있어서 글이 "
                    "적은 초반에 한 번만 설정하는 게 좋아."
                )
            elif platform == "워드프레스":
                st.info(
                    f"- 제목란에 위 제목 그대로\n"
                    f"- 카테고리: **{meta['category']}**\n"
                    f"- 태그: **{meta['tags']}**\n"
                    f"- SEO 플러그인(Yoast 등)의 메타 설명 칸에 위 메타 설명 붙여넣기\n"
                    f"- 오른쪽 설정 패널의 고유주소(URL/슬러그) 칸에: **{meta['slug']}**\n\n"
                    "본문 안 [소제목] 줄은 태그를 지우고 그 블록을 '제목(Heading, H2/H3)'으로 바꿔.\n\n"
                    "**사진 삽입 + ALT 입력**: [사진/그래프/지도 제안] 태그가 있던 그 자리에 "
                    "이미지 블록을 추가하고 사진을 업로드 → 화면 오른쪽 블록 설정 패널의 "
                    "'Alt text(대체 텍스트)' 칸에 안내된 ALT 문구 입력."
                )

            st.warning(
                "**모든 플랫폼 공통 — 발행 전에 본문에서 지울 태그들**\n"
                "- **사진 파일명**: [사진 제안] 줄의 '파일명'대로 업로드 전에 사진 파일 이름을 "
                "바꿔둬 (예: IMG_1234.jpg → probiotics-label-check.jpg). 구글 이미지 검색이 파일명도 읽어.\n"
                "- **[내부링크 제안]**: 그 글이 **실제로 발행된 글일 때만** 해당 문장에 링크를 걸고, "
                "아직 발행 안 했으면 줄째로 지워 (초안 폴더 기준이라 발행 안 한 글도 섞여 있음).\n"
                "- **[출처 필요]**: 근거를 찾아 문장에 넣거나, 못 찾으면 그 주장 자체를 빼.\n"
                "- [소제목]·[사진 제안] 등 대괄호 태그는 발행 전에 전부 지웠는지 마지막으로 확인."
            )
