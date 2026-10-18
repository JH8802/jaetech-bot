"""블로그 초안 생성기 — GUI 버전.
사용법: streamlit run blog_app.py
(또는 run_app.bat 더블클릭)

플랫폼을 여러 개 고르면 그 개수만큼 초안을 따로 생성한다
(네이버/티스토리/워드프레스는 문체·소제목 밀도·사진 개수가 실제로 다르게 나옴).
"""
import streamlit as st
from blog_drafter import draft_post, suggest_questions, revise_draft
from blog_reviewer import (scan_cliches, scan_structure, scan_seo, scan_health_claims,
                           review_draft, collect_issues, ai_issue, AI_REVIEW_LABELS)
from blog_sources import resolve_sources, is_bare_url
from blog_utils import parse_draft_metadata, load_past_titles, find_keyword_overlap, body_to_html
from datetime import datetime
import os
import shutil

st.set_page_config(page_title="블로그 초안 생성기", page_icon="✍️")

if "questions" not in st.session_state:
    st.session_state.questions = []
if "drafts" not in st.session_state:
    st.session_state.drafts = {}  # {플랫폼명: draft 텍스트}
if "filenames" not in st.session_state:
    st.session_state.filenames = {}  # {플랫폼명: 저장 경로}
if "target_keyword" not in st.session_state:
    st.session_state.target_keyword = ""  # 생성 당시 키워드 (점검에 사용)
if "reviews" not in st.session_state:
    # {플랫폼명: 점검 결과} — Streamlit은 칸 하나만 고쳐도 코드 전체를 다시
    # 실행하므로, 저장해두지 않으면 그때마다 AI 점검(유료)이 또 호출됨
    st.session_state.reviews = {}
if "inputs" not in st.session_state:
    # 생성 당시 입력값 — 다듬기 때 "새 사실의 유일한 재료"로 다시 넘겨줌
    st.session_state.inputs = {}

st.title("✍️ 블로그 초안 생성기")
st.caption("주제는 뭐든 상관없음 · 발행은 직접, 초안 생성 + 자동 점검까지만")
st.caption("⚠️ 플랫폼을 여러 개 고르면 그 개수만큼 Claude를 호출해 — 비용도 그만큼 늘어남")

if st.button("🔄 새로 시작"):
    st.session_state.questions = []
    st.session_state.drafts = {}
    st.session_state.filenames = {}
    st.session_state.target_keyword = ""
    st.session_state.reviews = {}
    st.session_state.inputs = {}
    st.rerun()

st.divider()

platforms = st.multiselect(
    "어디에 발행할 거야? (여러 개 선택 가능 — 선택한 만큼 따로 생성됨)",
    ["네이버 블로그", "티스토리", "워드프레스"],
    default=["티스토리"],
)
if "티스토리" in platforms and "워드프레스" in platforms:
    st.warning("**중복 콘텐츠 주의** — 같은 주제를 티스토리와 워드프레스에 둘 다 올리면 내용이 거의 같아서, 구글이 하나만 검색에 보여주고 나머지는 거의 숨겨 — 두 블로그가 서로 경쟁하게 돼. 원칙은 '한 주제는 한 블로그'. 굳이 둘 다 쓸 거면 주제나 관점을 확실히 나눠서 (예: 소비자 관점 / 실무자 관점) 따로 생성해.")

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

KEY_POINTS_MAX = 1000  # 실제 경험/숫자/사례 최대 글자 수
PERSONAL_TAKE_MAX = 300  # 본인 의견/입장 최대 글자 수

key_points_text = st.text_area(
    f"실제 경험/숫자/사례 (최대 {KEY_POINTS_MAX:,}자 — 한 줄씩 나눠 써도, 문단으로 길게 써도 돼)",
    height=220,
    max_chars=KEY_POINTS_MAX,
    placeholder="예)\n균주명 없이 보장균수만 강조하는 표시 사례를 실무에서 자주 봄. 식약처 기준상 효능 표시엔 건강기능식품 인증이 필요한데, 일반식품으로 팔면서 효능을 암시하는 문구를 쓰는 사례도 종종 봄.\n\n(항목별로 줄바꿈해서 써도 되고, 이렇게 이어서 써도 돼)",
    help="글에 꼭 반영하고 싶은 사실·숫자·실무 경험을 편하게 적어줘. 여기 없는 내용은 AI가 지어서 쓰지 않아.",
)
st.caption(f"{len(key_points_text):,} / {KEY_POINTS_MAX:,}자")


def fetch_sources_callback():
    """'링크 내용 가져오기' 버튼: 링크만 있는 줄을 '출처명 — 핵심 내용' 한 줄로 바꿔서
    입력칸에 채워 넣는다 (버튼 콜백에서만 입력칸 값을 바꿀 수 있음)."""
    lines = [l.strip() for l in st.session_state.get("sources_text", "").split("\n") if l.strip()]
    if not any(is_bare_url(l) for l in lines):
        st.session_state.sources_report = []
        return
    resolved, report = resolve_sources(lines)
    st.session_state.sources_text = "\n".join(resolved)
    st.session_state.sources_report = report


sources_text = st.text_area(
    "참고 자료/출처 (한 줄에 하나씩, 선택) — 링크만 붙여넣어도 돼",
    key="sources_text",
    height=110,
    placeholder="예)\nhttps://www.mfds.go.kr/... (링크만 붙이고 아래 '링크 내용 가져오기'를 누르면 자동 정리)\n식약처 고시 — NMN은 현재 건강기능식품 원료로 인정 안 됨 (직접 적어도 됨)",
    help="건강·돈 주제는 구글이 근거를 엄격하게 봐. 여기 적은 것만 본문에 인용하고, 근거가 필요한데 없으면 [출처 필요]로 표시돼.",
)
st.button(
    "🔗 링크 내용 가져오기 (링크 줄을 '출처명 — 핵심 내용'으로 자동 정리)",
    on_click=fetch_sources_callback,
)
st.caption(
    "AI는 링크를 직접 못 열어서, 이 버튼이 페이지를 대신 읽고 요약해 줘 (비용 거의 없음). "
    "로그인/구독이 필요한 글, PDF, 자바스크립트로 그려지는 페이지는 못 읽을 수 있어. "
    "요약은 AI가 한 거라 **원문과 대조해서 확인**하고, 틀린 부분은 입력칸에서 직접 고쳐줘."
)
for item in st.session_state.get("sources_report", []):
    if item["ok"]:
        st.success(f"✅ {item['url']}\n\n{item['message']}")
    else:
        st.error(f"❌ {item['url']} — {item['message']}\n\n이 링크는 위 입력칸에 문서명 + 핵심 내용을 직접 적어줘.")
personal_take = st.text_area(
    f"본인 의견/입장 (최대 {PERSONAL_TAKE_MAX}자 — 없으면 비워둬도 됨)",
    height=100,
    max_chars=PERSONAL_TAKE_MAX,
    help="이 글에서 내가 주장하고 싶은 관점·판단. 글의 방향을 잡는 데 쓰여.",
)
st.caption(f"{len(personal_take):,} / {PERSONAL_TAKE_MAX:,}자")

if st.button("✍️ 초안 생성", type="primary"):
    # 줄바꿈으로 나눠 쓰면 항목별로, 문단으로 길게 써도 그대로 한 덩어리로 전달됨
    key_points = [line.strip() for line in key_points_text.split("\n") if line.strip()]
    sources = [line.strip() for line in sources_text.split("\n") if line.strip()]
    if any(is_bare_url(s) for s in sources):
        # 링크를 가져오기 전에 바로 초안 생성을 눌렀을 때 — 여기서 자동으로 가져옴
        with st.spinner("🔗 출처 링크 내용 가져오는 중..."):
            sources, source_report = resolve_sources(sources)
        failed = [r for r in source_report if not r["ok"]]
        if failed:
            st.warning(
                "읽지 못한 링크는 출처에서 뺐어 (AI가 못 읽는 링크를 그냥 넘기면 내용을 지어낼 수 있어):\n"
                + "\n".join(f"- {r['url']} — {r['message']}" for r in failed)
            )
            sources = [s for s in sources if not is_bare_url(s)]
        if source_report:
            with st.expander("📎 자동으로 정리된 출처 (원문과 대조해서 확인)"):
                for r in source_report:
                    if r["ok"]:
                        st.write(f"- {r['message']}")
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
                f.write(f"주제: {topic}\n플랫폼: {platform}\n타깃 키워드: {target_keyword.strip()}\n\n{draft}")
            filenames[platform] = filename

        st.session_state.drafts = drafts
        st.session_state.filenames = filenames
        st.session_state.target_keyword = target_keyword.strip()
        st.session_state.reviews = {}
        st.session_state.inputs = {
            "topic": topic, "key_points": key_points, "sources": sources,
            "personal_take": personal_take,
        }

if st.session_state.drafts:
    st.divider()
    tabs = st.tabs(list(st.session_state.drafts.keys()))

    for tab, platform in zip(tabs, st.session_state.drafts.keys()):
        draft = st.session_state.drafts[platform]
        meta = parse_draft_metadata(draft)

        with tab:
            if platform not in st.session_state.reviews:
                with st.spinner("🔍 자동 점검 중..."):
                    st.session_state.reviews[platform] = {
                        "cliche": scan_cliches(draft),
                        "structure": scan_structure(draft),
                        "seo": scan_seo(meta, platform, st.session_state.target_keyword),
                        "claims": scan_health_claims(meta["body"]),
                        "ai": review_draft(draft),
                        "overlap": find_keyword_overlap(
                            platform, st.session_state.target_keyword,
                            exclude=st.session_state.filenames.values(),
                        ),
                    }
            review = st.session_state.reviews[platform]

            if review["overlap"]:
                st.warning(
                    f"**키워드 중복 주의** — 이 {platform}에 타깃 키워드 "
                    f"'{st.session_state.target_keyword}'로 쓴 글이 이미 있어:\n"
                    + "\n".join(f"- {t}" for t in review["overlap"])
                    + "\n\n같은 키워드 글이 여러 개면 내 글끼리 검색 순위를 나눠 먹어. "
                    "이미 발행한 글이면 키워드를 바꾸거나(더 구체적으로), 새 글 대신 기존 글을 "
                    "보강하는 걸 고려해봐. 같은 글의 이전 초안일 뿐이면 무시해도 돼."
                )

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

            if platform in ("티스토리", "워드프레스"):
                where = ("티스토리 에디터를 HTML 모드로 바꾼 뒤" if platform == "티스토리"
                         else "워드프레스 편집 화면 오른쪽 위 ⋮ 메뉴 → '코드 편집기'에서")
                with st.expander("🧩 HTML 버전 — 소제목이 제목(H2) 서식으로 이미 들어가 있음"):
                    st.caption(
                        f"{where} 붙여넣기 (오른쪽 위 복사 아이콘 클릭). 노란 📌 줄은 그 자리에 "
                        "사진/링크를 넣은 뒤 지워. 사진의 ALT는 사진을 넣을 때 따로 입력해야 해."
                    )
                    st.code(body_to_html(meta["body"]), language="html")

            st.subheader("📋 점검 결과")
            if review["cliche"]:
                st.error("**클리셰/반복 표현**\n" + "\n".join(f"- {i}" for i in review["cliche"]))
            else:
                st.success("클리셰/반복 표현: 없음")

            if review["structure"]:
                st.error("**글 구조(가독성/이미지)**\n" + "\n".join(f"- {i}" for i in review["structure"]))
            else:
                st.success("글 구조(가독성/이미지): 문제 없음")

            if review["seo"]:
                st.error("**검색 최적화(키워드/소제목/메타설명/출처)**\n" + "\n".join(f"- {i}" for i in review["seo"]))
            else:
                st.success("검색 최적화(키워드/소제목/메타설명/출처): 문제 없음")

            if review["claims"]:
                st.warning(
                    "**표시광고 표현 확인 필요** (질병 치료·예방을 암시할 수 있는 표현 — "
                    "'이런 표현은 쓰면 안 된다'는 설명 문맥이면 괜찮아)\n"
                    + "\n".join(f"- {i}" for i in review["claims"])
                    + "\n\n협찬·제공받은 제품이면 글 첫머리에 그 사실을 밝혀야 해 (공정위 추천·보증 심사지침)."
                )
            else:
                st.success("표시광고 표현: 걸리는 표현 없음")

            if not review["ai"]:
                st.warning("AI 점검(문장 리듬·의견·구체성·차별화·키워드)이 실패했어 — 네트워크 문제일 수 있어. "
                           "아래 '다시 점검'을 눌러봐.")
            for key, label in AI_REVIEW_LABELS.items():
                if not review["ai"]:
                    break
                val = ai_issue(review["ai"].get(key))
                if val:
                    st.error(f"**{label}**\n{val}")
                else:
                    st.success(f"{label}: 문제 없음")

            if st.button("🔁 다시 점검", key=f"recheck_{platform}"):
                del st.session_state.reviews[platform]
                st.rerun()

            st.divider()
            st.subheader("✨ 점검 반영해서 다듬기")
            issues = collect_issues(review)
            st.caption(
                f"지적된 {len(issues)}건을 반영해 수정본을 만들어. 문제 없는 부분은 그대로 두고, "
                "새 사실은 처음 입력한 재료와 아래 메모에 있는 것만 써 (지어내지 않음). "
                "누르면 Claude를 1번 더 호출해. 이전 버전은 drafts/history 폴더에 남아."
            )
            author_note = st.text_area(
                "추가 메모 (선택) — 지적을 해결할 구체적인 사실·사례·의견이 있으면 적어줘",
                height=90, key=f"note_{platform}",
                placeholder="예) 구체성 부족 지적 → 지난달 점검한 A제품은 균주명 없이 '500억 보장'만 표기돼 있었음",
            )
            if st.button("✨ 점검 반영해서 다듬기", key=f"revise_{platform}", type="primary"):
                if not issues and not author_note.strip():
                    st.info("지적된 부분도 추가 메모도 없어서 다듬을 게 없어.")
                else:
                    inputs = st.session_state.inputs
                    with st.spinner(f"⏳ {platform} 수정본 만드는 중..."):
                        try:
                            revised = revise_draft(
                                draft, issues, inputs.get("key_points", []),
                                sources=inputs.get("sources"),
                                personal_take=inputs.get("personal_take", ""),
                                author_note=author_note.strip(), platform=platform,
                                target_keyword=st.session_state.target_keyword,
                            )
                        except Exception as e:
                            revised = ""
                            st.error(f"❌ 다듬기 실패: {e}\n(네트워크 문제일 수 있어 — 다시 눌러봐)")
                    if revised and revised.strip() == draft.strip():
                        st.info(
                            "수정본이 이전 초안과 똑같아 — 지적된 부분을 AI가 재료 없이는 고칠 수 없다고 "
                            "판단한 거야. 위 '추가 메모'에 그 지적을 해결할 사실·사례·기준을 적고 다시 눌러봐."
                        )
                    elif revised:
                        path = st.session_state.filenames[platform]
                        os.makedirs("drafts/history", exist_ok=True)
                        stamp = datetime.now().strftime("%H%M%S")
                        old_name = os.path.basename(path)[:-len(".txt")]
                        shutil.copy(path, f"drafts/history/{old_name}_이전_{stamp}.txt")
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(
                                f"주제: {inputs.get('topic', '')}\n플랫폼: {platform}\n"
                                f"타깃 키워드: {st.session_state.target_keyword}\n\n{revised}"
                            )
                        st.session_state.drafts[platform] = revised
                        del st.session_state.reviews[platform]
                        # 키가 있는 입력칸은 이전 값을 기억하므로 지워야 새 내용으로 바뀜
                        for prefix in ("title", "category", "tags", "meta", "slug", "body", "note"):
                            st.session_state.pop(f"{prefix}_{platform}", None)
                        st.rerun()

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
