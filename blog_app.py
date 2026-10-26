"""블로그 초안 생성기 — GUI 버전.
사용법: streamlit run blog_app.py
(또는 run_app.bat 더블클릭)

작성 방식 2가지:
- ✍️ 내 메모로 쓰기: 내가 적은 경험·숫자·의견 + 출처로 초안 작성
- 📰 자료로 쓰기: 기사 링크·PDF·캡처를 읽어 '자료 노트'로 정리 → 주제 제안 → 원고 작성
  (구조 편집·재작성·표/목록·SEO·검수 표시까지, 워드프레스 블록 에디터용 HTML 출력)

- 왼쪽 사이드바: 내 문체 샘플(저장하면 모든 초안·다듬기에 반영), 저장된 원고 불러오기
- 입력칸 내용은 자동 저장 (껐다 켜도 이어서 작성)
- 생성·수정한 원고는 drafts/ 폴더에 자동 저장 (덮어쓸 때 이전 버전은 drafts/history/)
"""
import os
import re
from datetime import datetime

import streamlit as st

from blog_drafter import draft_post, suggest_questions, revise_draft
from blog_factcheck import check_numbers, build_references, unverified, find_copied_sentences
from blog_materials import (make_material_note, suggest_topics, draft_from_materials,
                            count_materials, split_notes, AUDIENCES, TONES, LENGTHS)
from blog_reviewer import (scan_cliches, scan_structure, scan_seo, scan_health_claims, scan_ai_patterns,
                           review_draft, collect_issues, ai_issue, AI_REVIEW_LABELS)
from blog_sources import resolve_sources, resolve_files, is_bare_url
from blog_utils import (parse_draft_metadata, load_past_titles, find_keyword_overlap, body_to_html,
                        body_to_gutenberg, find_placeholders, apply_placeholders, compose_draft,
                        write_draft_file, read_draft_file, list_saved_drafts,
                        load_style_sample, save_style_sample, STYLE_SAMPLE_MAX,
                        load_autosave, save_autosave, DATA_DIR, DRAFTS_DIR)

st.set_page_config(page_title="블로그 초안 생성기", page_icon="✍️")

KEY_POINTS_MAX = 1000  # 실제 경험/숫자/사례 최대 글자 수
PERSONAL_TAKE_MAX = 300  # 본인 의견/입장 최대 글자 수
OPINION_MAX = 500  # 자료로 쓰기 — 내 의견·경험 최대 글자 수
PLATFORM_CHOICES = ["네이버 블로그", "티스토리", "워드프레스"]
MODE_MEMO = "✍️ 내 메모로 쓰기"
MODE_MATERIALS = "📰 자료로 쓰기 (기사 링크·PDF·캡처)"

# 자동 저장하는 입력칸 (위젯 key → 기본값)
INPUT_DEFAULTS = {
    "mode": MODE_MEMO,
    "platforms": ["티스토리"],
    "topic": "",
    "kw_input": "",
    "key_points_text": "",
    "sources_text": "",
    "personal_take_text": "",
    "mat_urls": "",
    "mat_notes": "",
    "mat_audience": AUDIENCES[0],
    "mat_tone": list(TONES)[2],
    "mat_length": 3000,
    "mat_opinion": "",
}
# 고를 수 있는 값이 정해진 입력칸 — 저장된 값이 목록에 없으면 기본값으로
INPUT_CHOICES = {"mode": [MODE_MEMO, MODE_MATERIALS], "mat_audience": AUDIENCES,
                 "mat_tone": list(TONES), "mat_length": LENGTHS}
INPUT_LIMITS = {"key_points_text": KEY_POINTS_MAX, "personal_take_text": PERSONAL_TAKE_MAX,
                "mat_opinion": OPINION_MAX}
# 원고 탭의 입력칸 key 앞부분 — 원고 내용이 바뀌면 지워야 새 내용으로 다시 채워짐
FIELD_PREFIXES = ("title", "category", "tags", "meta", "slug", "body", "note")


# ─────────────────────────────────────────────
# 상태 초기화 / 공용 함수
# ─────────────────────────────────────────────
def _clean_input(key, value):
    default = INPUT_DEFAULTS[key]
    if key == "platforms":
        return [p for p in (value if isinstance(value, list) else []) if p in PLATFORM_CHOICES] or list(default)
    if key in INPUT_CHOICES:
        return value if value in INPUT_CHOICES[key] else default
    if not isinstance(value, str):
        return default
    return value[:INPUT_LIMITS[key]] if key in INPUT_LIMITS else value


def init_state():
    defaults = {
        "questions": [], "drafts": {}, "filenames": {}, "target_keyword": "",
        # {플랫폼명: 점검 결과} — Streamlit은 칸 하나만 고쳐도 코드 전체를 다시 실행하므로,
        # 저장해두지 않으면 그때마다 AI 점검(유료)이 또 호출됨
        "reviews": {},
        # 생성 당시 입력값 — 다듬기·숫자 대조 때 "사실의 유일한 재료"로 쓰임
        "inputs": {},
        "sources_report": [], "ph_ver": {}, "uploader_ver": 0,
        "topic_ideas": [], "mat_report": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if "autosave_loaded" not in st.session_state:
        saved = load_autosave()
        # 화면에 안 보이는 입력칸(다른 작성 방식의 칸)은 Streamlit이 값을 지워버려서,
        # 여기(_inputs)에 따로 보관해두고 매번 다시 채운다
        st.session_state._inputs = {key: _clean_input(key, saved.get(key, default))
                                    for key, default in INPUT_DEFAULTS.items()}
        st.session_state.mat_raw = saved.get("mat_raw") if isinstance(saved.get("mat_raw"), dict) else {}
        st.session_state.mat_done = saved.get("mat_done") if isinstance(saved.get("mat_done"), list) else []
        st.session_state.style_sample_text = load_style_sample()
        st.session_state.autosave_loaded = True

    for key in INPUT_DEFAULTS:
        if key not in st.session_state:
            st.session_state[key] = st.session_state._inputs[key]


def set_input(key, value):
    """콜백에서 입력칸 값을 바꿀 때 (보관용 사본도 같이)."""
    st.session_state[key] = value
    st.session_state._inputs[key] = value


def autosave_inputs():
    """입력칸 값을 보관하고, 바뀌었으면 파일에 자동 저장."""
    for key in INPUT_DEFAULTS:
        if key in st.session_state:
            st.session_state._inputs[key] = st.session_state[key]
    data = dict(st.session_state._inputs, mat_raw=st.session_state.mat_raw, mat_done=st.session_state.mat_done)
    if data != st.session_state.get("_last_autosave"):
        save_autosave(data)
        st.session_state._last_autosave = data


def clear_fields(platform):
    for prefix in FIELD_PREFIXES:
        st.session_state.pop(f"{prefix}_{platform}", None)


def lines_of(text):
    return [line.strip() for line in (text or "").split("\n") if line.strip()]


def current_meta(platform, meta):
    """화면 입력칸에 지금 들어 있는 값 (아직 저장 안 한 수정 포함)."""
    ss = st.session_state
    return {
        "title": ss.get(f"title_{platform}", meta["title"]),
        "title_candidates": meta.get("title_candidates", ""),
        "category": ss.get(f"category_{platform}", meta["category"]),
        "tags": ss.get(f"tags_{platform}", meta["tags"]),
        "meta_description": ss.get(f"meta_{platform}", meta["meta_description"]),
        "slug": ss.get(f"slug_{platform}", meta["slug"]),
        "body": ss.get(f"body_{platform}", meta["body"]),
    }


def persist(platform, new_draft):
    """원고를 바꾸고 같은 파일에 저장 (이전 버전은 drafts/history/), 점검은 다시 하게 함."""
    inputs = st.session_state.inputs
    write_draft_file(
        st.session_state.filenames[platform], inputs.get("topic", ""), platform,
        st.session_state.target_keyword, new_draft, inputs, backup=True,
    )
    st.session_state.drafts[platform] = new_draft
    st.session_state.reviews.pop(platform, None)
    clear_fields(platform)


def remember_typed_numbers(old_text, new_text):
    """내가 직접 입력한 숫자는 숫자 대조에서 '근거 있음'으로 인정되게 기록."""
    old_nums = set(re.findall(r"\d+(?:[.,]\d+)*", old_text))
    new_nums = [n for n in re.findall(r"\d+(?:[.,]\d+)*", new_text) if n not in old_nums]
    if new_nums:
        st.session_state.inputs.setdefault("user_additions", []).append("직접 수정: " + " ".join(new_nums))


def finish_generation(drafts, filenames, inputs, keyword):
    st.session_state.drafts = drafts
    st.session_state.filenames = filenames
    st.session_state.target_keyword = keyword
    st.session_state.reviews = {}
    st.session_state.inputs = inputs
    for platform in PLATFORM_CHOICES:
        clear_fields(platform)


def new_draft_path(platform):
    return os.path.join(DRAFTS_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{platform.replace(' ', '')}.txt")


# ─────────────────────────────────────────────
# 버튼 콜백 (입력칸 값을 바꾸는 동작은 콜백에서만 가능)
# ─────────────────────────────────────────────
def reset_all():
    for key in ("questions", "sources_report", "topic_ideas", "mat_report", "mat_done"):
        st.session_state[key] = []
    for key in ("drafts", "filenames", "reviews", "inputs", "mat_raw"):
        st.session_state[key] = {}
    st.session_state.target_keyword = ""
    mode = st.session_state.get("mode", MODE_MEMO)
    for key, default in INPUT_DEFAULTS.items():
        set_input(key, list(default) if isinstance(default, list) else default)
    set_input("mode", mode)  # 작성 방식은 그대로 유지
    for platform in PLATFORM_CHOICES:
        clear_fields(platform)
    autosave_inputs()


def clear_materials_cb():
    set_input("mat_notes", "")
    set_input("mat_urls", "")
    st.session_state.mat_raw = {}
    st.session_state.mat_done = []
    st.session_state.mat_report = []
    st.session_state.topic_ideas = []


def pick_idea_cb(i):
    idea = st.session_state.topic_ideas[i]
    set_input("topic", idea["title"])
    set_input("kw_input", idea["keyword"])


def save_style_cb():
    save_style_sample(st.session_state.style_sample_text)


def load_draft_cb():
    path = st.session_state.get("saved_pick")
    if not path:
        return
    info = read_draft_file(path)
    platform = info["platform"] if info["platform"] in PLATFORM_CHOICES else "티스토리"
    inputs = info["inputs"] or {
        "topic": info["topic"], "target_keyword": info["keyword"], "key_points": [],
        "sources": [], "personal_take": "", "notes": [], "user_additions": [],
    }
    st.session_state.drafts = {platform: info["draft"]}
    st.session_state.filenames = {platform: path}
    st.session_state.target_keyword = info["keyword"]
    st.session_state.inputs = inputs
    st.session_state.reviews = {}
    clear_fields(platform)
    # 그때 입력했던 내용도 입력칸에 다시 채움
    set_input("platforms", [platform])
    set_input("topic", inputs.get("topic") or info["topic"])
    set_input("kw_input", inputs.get("target_keyword") or info["keyword"])
    if inputs.get("mode") == "materials":
        set_input("mode", MODE_MATERIALS)
        set_input("mat_notes", "\n\n".join(inputs.get("sources", [])))
        set_input("mat_opinion", (inputs.get("personal_take") or "")[:OPINION_MAX])
        for key, field in (("mat_audience", "audience"), ("mat_tone", "tone"), ("mat_length", "length")):
            set_input(key, _clean_input(key, inputs.get(field)))
        st.session_state.mat_raw = inputs.get("material_raw", {})
    else:
        set_input("mode", MODE_MEMO)
        set_input("key_points_text", "\n".join(inputs.get("key_points", []))[:KEY_POINTS_MAX])
        set_input("sources_text", "\n".join(inputs.get("sources", [])))
        set_input("personal_take_text", (inputs.get("personal_take") or "")[:PERSONAL_TAKE_MAX])


init_state()

# ─────────────────────────────────────────────
# 사이드바: 내 문체 샘플 / 저장된 원고
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("✍️ 내 문체 샘플")
    st.caption(
        "내가 직접 쓴 글(Threads 글, 예전 블로그 글 등) 2~3개를 붙여넣고 저장하면, "
        "모든 초안과 다듬기가 이 말투·어미·리듬을 따라가. 내용(사실)은 가져오지 않아. "
        "언제든 고쳐서 다시 저장하면 돼."
    )
    st.text_area(
        f"내가 쓴 글 (최대 {STYLE_SAMPLE_MAX:,}자)", key="style_sample_text",
        height=260, max_chars=STYLE_SAMPLE_MAX,
        placeholder="예) 내가 쓴 Threads 글이나 블로그 글을 그대로 붙여넣기.\n글과 글 사이는 빈 줄로 구분하면 돼.",
    )
    st.button("💾 문체 샘플 저장", on_click=save_style_cb)
    saved_sample = load_style_sample()
    if st.session_state.style_sample_text.strip() != saved_sample:
        st.warning("고친 내용이 아직 저장 안 됐어 — 위 버튼을 눌러줘.")
    elif saved_sample:
        st.success(f"저장됨 ({len(saved_sample):,}자) — 모든 초안·다듬기에 반영 중")
    else:
        st.caption("저장된 샘플 없음 — 기본 문체로 작성 중")

    st.divider()
    st.header("📂 저장된 원고")
    saved_items = list_saved_drafts()
    if saved_items:
        labels = {item["path"]: item["label"] for item in saved_items}
        st.selectbox("원고 고르기 (최신순)", list(labels), format_func=labels.get, key="saved_pick")
        st.button("📂 불러오기", on_click=load_draft_cb)
        st.caption(
            "불러오면 그 원고와 그때 입력했던 메모·출처·의견이 다시 채워져. "
            "고친 내용은 같은 파일에 자동 저장되고, 이전 버전은 drafts/history 폴더에 남아."
        )
    else:
        st.caption("아직 저장된 원고가 없어. 초안을 생성하면 자동으로 여기 쌓여.")
    st.caption(f"📁 데이터 폴더: {os.path.abspath(DATA_DIR)}")


# ─────────────────────────────────────────────
# 입력 영역 (공통)
# ─────────────────────────────────────────────
st.title("✍️ 블로그 초안 생성기")
st.caption("발행은 직접, 초안 생성 + 자동 점검까지만 · 입력 내용은 자동 저장")
st.caption("⚠️ 플랫폼을 여러 개 고르면 그 개수만큼 Claude를 호출해 — 비용도 그만큼 늘어남")

st.button("🔄 새로 시작 (입력칸 비우기)", on_click=reset_all)
st.divider()

mode = st.radio("작성 방식", [MODE_MEMO, MODE_MATERIALS], key="mode", horizontal=True)
platforms = st.multiselect(
    "어디에 발행할 거야? (여러 개 선택 가능 — 선택한 만큼 따로 생성됨)",
    PLATFORM_CHOICES, key="platforms",
)
if "티스토리" in platforms and "워드프레스" in platforms:
    st.warning("**중복 콘텐츠 주의** — 같은 주제를 티스토리와 워드프레스에 둘 다 올리면 내용이 거의 같아서, 구글이 하나만 검색에 보여주고 나머지는 거의 숨겨 — 두 블로그가 서로 경쟁하게 돼. 원칙은 '한 주제는 한 블로그'. 굳이 둘 다 쓸 거면 주제나 관점을 확실히 나눠서 (예: 소비자 관점 / 실무자 관점) 따로 생성해.")


def keyword_inputs():
    topic = st.text_input("주제", key="topic", placeholder="예: 홈쇼핑 유산균 표시광고, 뭐가 문제인가")
    keyword = st.text_input(
        "타깃 키워드 (이 글로 잡고 싶은 검색어 — 비우면 AI가 고름)", key="kw_input",
        placeholder="예: 유산균 보장균수",
        help="구글 검색창에 주제를 쳐보고 자동완성에 뜨는 검색어 중 하나를 고르면 좋아.",
    )
    return topic, keyword


# ─────────────────────────────────────────────
# ✍️ 내 메모로 쓰기
# ─────────────────────────────────────────────
if mode == MODE_MEMO:
    topic, target_keyword = keyword_inputs()

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
        f"실제 경험/숫자/사례 (최대 {KEY_POINTS_MAX:,}자 — 한 줄씩 나눠 써도, 문단으로 길게 써도 돼)",
        key="key_points_text", height=220, max_chars=KEY_POINTS_MAX,
        placeholder="예)\n균주명 없이 보장균수만 강조하는 표시 사례를 실무에서 자주 봄. 식약처 기준상 효능 표시엔 건강기능식품 인증이 필요한데, 일반식품으로 팔면서 효능을 암시하는 문구를 쓰는 사례도 종종 봄.\n\n(항목별로 줄바꿈해서 써도 되고, 이렇게 이어서 써도 돼)",
        help="글에 꼭 반영하고 싶은 사실·숫자·실무 경험을 편하게 적어줘. 여기 없는 내용은 AI가 지어서 쓰지 않아.",
    )
    st.caption(f"{len(key_points_text):,} / {KEY_POINTS_MAX:,}자")

    # 링크/파일에서 가져온 출처는 다음 실행 때 입력칸에 넣는다 (입력칸이 그려진 뒤엔 값을 못 바꿔서)
    if "pending_sources" in st.session_state:
        set_input("sources_text", st.session_state.pop("pending_sources"))

    sources_text = st.text_area(
        "참고 자료/출처 (한 줄에 하나씩, 선택) — 링크만 붙여넣어도 돼 (웹페이지·PDF 링크)",
        key="sources_text", height=130,
        placeholder="예)\nhttps://www.mfds.go.kr/... (웹페이지나 PDF 링크만 붙이고 아래 '링크 내용 가져오기')\n식약처 고시 — NMN은 현재 건강기능식품 원료로 인정 안 됨 (직접 적어도 됨)",
        help="건강·돈 주제는 구글이 근거를 엄격하게 봐. 여기 적은 것만 본문에 인용하고, 근거가 필요한데 없으면 [출처 필요]로 표시돼.",
    )
    if st.button("🔗 링크 내용 가져오기 (웹페이지·PDF 링크 → '출처명 — 핵심 내용')"):
        source_lines = lines_of(sources_text)
        if not any(is_bare_url(line) for line in source_lines):
            st.info("가져올 링크가 없어 — 한 줄에 링크 하나만 있는 줄을 읽어.")
        else:
            with st.spinner("🔗 링크 읽는 중... (PDF 링크는 쪽수에 따라 30초~1분 걸릴 수 있어)"):
                resolved, report = resolve_sources(source_lines, topic=topic)
            st.session_state.pending_sources = "\n".join(resolved)
            st.session_state.sources_report = report
            st.rerun()

    uploaded = st.file_uploader(
        "📄 파일로 출처 추가 — 식약처 PDF, 캡처 이미지(png·jpg) 등 (여러 개 가능)",
        type=["pdf", "png", "jpg", "jpeg", "webp"], accept_multiple_files=True,
        key=f"source_files_{st.session_state.uploader_ver}",
        help="PDF는 그대로 올리는 게 캡처보다 정확해 (숫자를 이미지에서 읽지 않아도 돼). 캡처는 필요한 페이지만 볼 때 써. 한글(HWP) 파일은 못 읽어.",
    )
    if st.button("📄 파일 내용 가져오기 (위 출처 칸에 한 줄씩 추가)", disabled=not uploaded):
        with st.spinner(f"📄 파일 {len(uploaded)}개 읽는 중... (PDF는 쪽수에 따라 30초~1분 걸릴 수 있어)"):
            file_lines, report = resolve_files([(f.name, f.getvalue()) for f in uploaded], topic=topic)
        current = sources_text.strip()
        st.session_state.pending_sources = "\n".join(([current] if current else []) + file_lines)
        st.session_state.sources_report = report
        st.session_state.uploader_ver += 1  # 올린 파일 목록 비우기
        st.rerun()

    st.caption(
        "AI는 링크·파일을 직접 못 열어서, 이 버튼들이 대신 읽고 요약해 줘. 웹페이지는 거의 무료, "
        "PDF·캡처는 숫자를 정확히 읽으려고 더 좋은 모델을 써서 파일당 수십 원 정도. "
        "로그인/구독이 필요한 글, 자바스크립트로 그려지는 페이지, 한글(HWP) 파일은 못 읽어. "
        "요약은 AI가 한 거라 **원문과 대조해서 확인**하고, 틀린 부분은 출처 칸에서 직접 고쳐줘."
    )
    for item in st.session_state.get("sources_report", []):
        if item["ok"]:
            st.success(f"✅ {item['url']}\n\n{item['message']}")
        else:
            st.error(f"❌ {item['url']} — {item['message']}\n\n이 자료는 출처 칸에 문서명 + 핵심 내용을 직접 적어줘.")

    personal_take = st.text_area(
        f"본인 의견/입장 (최대 {PERSONAL_TAKE_MAX}자 — 없으면 비워둬도 됨)",
        key="personal_take_text", height=100, max_chars=PERSONAL_TAKE_MAX,
        help="이 글에서 내가 주장하고 싶은 관점·판단. 글의 방향을 잡는 데 쓰여.",
    )
    st.caption(f"{len(personal_take):,} / {PERSONAL_TAKE_MAX:,}자")
    autosave_inputs()

    if st.button("✍️ 초안 생성", type="primary"):
        # 줄바꿈으로 나눠 쓰면 항목별로, 문단으로 길게 써도 그대로 한 덩어리로 전달됨
        key_points = lines_of(key_points_text)
        sources = lines_of(sources_text)
        if any(is_bare_url(s) for s in sources):
            # 링크를 가져오기 전에 바로 초안 생성을 눌렀을 때 — 여기서 자동으로 가져옴
            with st.spinner("🔗 출처 링크 내용 가져오는 중..."):
                sources, source_report = resolve_sources(sources, topic=topic)
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
            inputs = {
                "mode": "memo", "topic": topic, "target_keyword": target_keyword.strip(),
                "key_points": key_points, "sources": sources, "personal_take": personal_take,
                "notes": [], "user_additions": [],
            }
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
                path = new_draft_path(platform)
                write_draft_file(path, topic, platform, target_keyword.strip(), draft, inputs)
                drafts[platform], filenames[platform] = draft, path
            if drafts:
                finish_generation(drafts, filenames, inputs, target_keyword.strip())

# ─────────────────────────────────────────────
# 📰 자료로 쓰기
# ─────────────────────────────────────────────
else:
    st.info(
        "기사 링크·PDF·캡처를 넣으면 AI가 **자료 노트**로 정리하고 → 쓸 만한 **주제를 제안**하고 → "
        "제목 후보·요약 박스·소제목·표·목록·SEO까지 갖춘 **원고**를 써줘. 자료 문장은 그대로 옮기지 않고 "
        "새로 쓰며, 인정 범위를 벗어난 표현이나 자료끼리 충돌하는 내용은 **[검수]**로 표시해."
    )

    # 1️⃣ 자료 넣기
    st.subheader("1️⃣ 자료 넣기")
    st.text_area(
        "기사·자료 링크 (한 줄에 하나 — 웹페이지·PDF 링크)", key="mat_urls", height=110,
        placeholder="https://www.hankyung.com/article/...\nhttps://www.mfds.go.kr/brd/.../down.do?...",
    )
    mat_files = st.file_uploader(
        "📄 PDF·캡처 이미지 (여러 개 가능)", type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True, key=f"mat_files_{st.session_state.uploader_ver}",
        help="PDF는 그대로 올리는 게 캡처보다 정확해. 한글(HWP) 파일은 못 읽어.",
    )
    new_urls = [u for u in lines_of(st.session_state.mat_urls)
                if is_bare_url(u) and u not in st.session_state.mat_done]
    read_label = f"📚 자료 읽고 정리하기 (새 링크 {len(new_urls)}개 · 파일 {len(mat_files or [])}개)"
    if st.button(read_label, type="primary", disabled=not (new_urls or mat_files)):
        jobs = [("url", u) for u in new_urls] + [("file", f.name, f.getvalue()) for f in (mat_files or [])]
        notes = st.session_state.mat_notes.strip()
        number = count_materials(notes)
        report = []
        progress = st.progress(0.0, text="자료 읽는 중...")
        for idx, job in enumerate(jobs):
            label = job[1]
            progress.progress(idx / len(jobs), text=f"자료 읽는 중 ({idx + 1}/{len(jobs)}): {label[:60]}")
            try:
                result = make_material_note(job, topic=st.session_state.topic)
            except Exception as e:
                report.append({"name": label, "ok": False, "message": str(e)})
                continue
            number += 1
            note = f"[자료 {number}] {label}\n{result['note']}"
            notes = f"{notes}\n\n{note}" if notes else note
            if result["raw"]:
                st.session_state.mat_raw[f"자료 {number}"] = result["raw"]
            if job[0] == "url":
                st.session_state.mat_done.append(label)
            report.append({"name": label, "ok": True, "message": f"자료 {number}로 정리됨"})
        progress.empty()
        st.session_state.pending_mat_notes = notes
        st.session_state.mat_report = report
        st.session_state.uploader_ver += 1
        st.rerun()

    for item in st.session_state.mat_report:
        if item["ok"]:
            st.success(f"✅ {item['name'][:80]} — {item['message']}")
        else:
            st.error(f"❌ {item['name'][:80]} — {item['message']}")

    if "pending_mat_notes" in st.session_state:
        set_input("mat_notes", st.session_state.pop("pending_mat_notes"))
    mat_notes = st.text_area(
        "📒 자료 노트 — AI가 원문을 사실·수치 위주로 다시 정리한 것 (이 노트만 원고의 근거로 쓰여)",
        key="mat_notes", height=320,
        help="AI가 정리한 거라 원문과 대조해서 틀린 부분은 여기서 직접 고쳐줘. 직접 메모를 '[자료 N] 출처' 형식으로 추가해도 돼.",
    )
    col_a, col_b = st.columns([3, 1])
    col_a.caption(f"자료 {count_materials(mat_notes)}개 · {len(mat_notes):,}자 · 이미 읽은 링크는 다시 읽지 않아")
    col_b.button("🗑️ 자료 비우기", on_click=clear_materials_cb)

    # 2️⃣ 주제 정하기
    st.subheader("2️⃣ 주제 정하기")
    if st.button("💡 이 자료로 쓸 만한 주제 제안받기", disabled=not mat_notes.strip()):
        with st.spinner("자료를 보고 주제를 고르는 중..."):
            st.session_state.topic_ideas = suggest_topics(mat_notes, st.session_state.mat_audience)
        if not st.session_state.topic_ideas:
            st.warning("주제 제안에 실패했어 — 다시 눌러보거나 아래 주제를 직접 적어줘.")
    for i, idea in enumerate(st.session_state.topic_ideas):
        with st.container(border=True):
            st.markdown(f"**{idea['title']}**")
            st.caption(f"키워드: {idea['keyword']} · {idea['materials']}")
            st.write(idea["angle"])
            st.button("이 주제로 정하기", key=f"pick_idea_{i}", on_click=pick_idea_cb, args=(i,))
    topic, target_keyword = keyword_inputs()

    # 3️⃣ 글 설정
    st.subheader("3️⃣ 글 설정")
    col1, col2 = st.columns(2)
    with col1:
        st.selectbox("독자", AUDIENCES, key="mat_audience")
        st.select_slider("분량 (본문)", options=LENGTHS, key="mat_length", format_func=lambda n: f"{n:,}자 내외")
    with col2:
        st.radio("말투", list(TONES), key="mat_tone")
    opinion = st.text_area(
        f"내 의견·실무 경험 (최대 {OPINION_MAX}자 — 강력 추천)", key="mat_opinion", height=120,
        max_chars=OPINION_MAX,
        placeholder="예) 실무에서 보면 1정당 함량을 안 적은 제품이 꽤 많다. 나는 총량만 크게 쓴 제품은 일단 거른다.",
        help="자료만 다시 정리한 글은 구글이 가치가 낮다고 봐. 한두 줄이라도 내 판단·경험이 들어가야 '내 글'이 돼.",
    )
    st.caption(f"{len(opinion):,} / {OPINION_MAX}자")
    if not opinion.strip():
        st.warning("내 의견·경험이 비어 있으면 '자료를 다시 정리한 글'이 돼서 구글 평가가 낮아질 수 있어. 한두 줄이라도 적는 걸 추천해.")
    autosave_inputs()

    if st.button("✍️ 자료로 원고 쓰기", type="primary"):
        if not mat_notes.strip():
            st.error("자료 노트가 비어 있어. 먼저 자료를 읽어서 정리해줘.")
        elif not topic.strip():
            st.error("주제를 정해줘 (제안받은 주제에서 고르거나 직접 입력).")
        elif not platforms:
            st.error("발행할 곳을 하나 이상 선택해줘.")
        else:
            inputs = {
                "mode": "materials", "topic": topic, "target_keyword": target_keyword.strip(),
                "key_points": lines_of(opinion), "sources": split_notes(mat_notes),
                "personal_take": opinion, "notes": [], "user_additions": [],
                "audience": st.session_state.mat_audience, "tone": st.session_state.mat_tone,
                "length": st.session_state.mat_length, "material_raw": dict(st.session_state.mat_raw),
            }
            drafts, filenames = {}, {}
            for platform in platforms:
                with st.spinner(f"⏳ {platform}용 원고 쓰는 중... (자료가 많으면 1~2분 걸릴 수 있어)"):
                    try:
                        draft = draft_from_materials(
                            mat_notes, topic, target_keyword.strip(),
                            audience=st.session_state.mat_audience, tone=st.session_state.mat_tone,
                            length=st.session_state.mat_length, opinion=opinion, platform=platform,
                            past_titles=load_past_titles(platform),
                        )
                    except Exception as e:
                        st.error(f"❌ {platform} 원고 작성 실패: {e}\n(네트워크 문제일 수 있어 — 다시 눌러봐)")
                        continue
                path = new_draft_path(platform)
                write_draft_file(path, topic, platform, target_keyword.strip(), draft, inputs)
                drafts[platform], filenames[platform] = draft, path
            if drafts:
                finish_generation(drafts, filenames, inputs, target_keyword.strip())

# ─────────────────────────────────────────────
# 원고 탭
# ─────────────────────────────────────────────
PLACEHOLDER_UI = {
    "source": ("출처 입력 — '(식약처 건강기능식품 기준 및 규격, 2024)'처럼 괄호로 쓰면 문장 끝에 붙고, "
               "'○○ 연구(2016)에 따르면 …'처럼 문장으로 쓰면 그 뒤에 새 문장으로 들어가",
               "근거를 못 찾음 → 태그만 지우기 (비추천: 근거 없는 문장이 남음)"),
    "add": ("넣을 내용 (쓴 그대로 그 자리에 들어가)", "이 항목 지우기"),
    "link": ("발행된 그 글의 주소(URL) — 넣으면 HTML에서 링크가 돼", "이 줄 지우기 (아직 발행 안 한 글이면)"),
    "visual": ("이미지 주소(URL, 선택) — 비워두면 HTML에 📌로 남아서 에디터에서 사진을 넣으면 돼",
               "이 사진 제안 지우기 (사진 안 넣음)"),
    "review": ("표시 자리에 넣을 내용 (선택) — 보통은 본문 칸에서 해당 문장을 직접 고치고 💾 저장한 뒤, 여기선 '확인 완료'만 체크",
               "확인 완료 — 이 검수 표시 지우기"),
}

if st.session_state.drafts:
    st.divider()
    tabs = st.tabs(list(st.session_state.drafts.keys()))

    for tab, platform in zip(tabs, list(st.session_state.drafts.keys())):
        draft = st.session_state.drafts[platform]
        meta = parse_draft_metadata(draft)
        inputs = st.session_state.inputs

        with tab:
            if platform not in st.session_state.reviews:
                with st.spinner("🔍 자동 점검 중..."):
                    st.session_state.reviews[platform] = {
                        "cliche": scan_cliches(draft),
                        "structure": scan_structure(draft),
                        "seo": scan_seo(meta, platform, st.session_state.target_keyword),
                        "claims": scan_health_claims(meta["body"]),
                        "ai_patterns": scan_ai_patterns(meta["body"]),
                        "facts": check_numbers(meta["body"], build_references(inputs)),
                        "copied": find_copied_sentences(meta["body"], inputs.get("material_raw", {})),
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

            # ── 발행 정보 ──
            st.subheader("📝 발행 정보")
            st.text_input("제목", meta["title"], key=f"title_{platform}")
            if meta.get("title_candidates"):
                st.caption("💡 다른 제목 후보: " + " · ".join(f"「{t}」" for t in meta["title_candidates"].split(" / ")))
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

            # ── 본문 ──
            st.subheader("📄 본문")
            st.text_area(
                "본문 (여기서 직접 고쳐도 돼 — 고친 뒤 아래 💾 저장을 눌러야 HTML에 반영됨)",
                meta["body"], height=400, key=f"body_{platform}",
            )
            st.caption(f"본문 글자 수: {len(meta['body'])}자 · 저장 파일: {st.session_state.filenames[platform]}")
            if st.button("💾 위 칸에서 고친 내용 저장 (제목·카테고리·태그·메타설명·본문)", key=f"save_{platform}"):
                edited = current_meta(platform, meta)
                new_draft = compose_draft(edited)
                if new_draft.strip() == compose_draft(meta).strip():
                    st.info("바뀐 내용이 없어.")
                else:
                    remember_typed_numbers(meta["body"], edited["body"])
                    persist(platform, new_draft)
                    st.rerun()

            # ── 남은 항목 채우기 ──
            body_now = st.session_state.get(f"body_{platform}", meta["body"])
            items = find_placeholders(body_now)
            if items:
                with st.expander(f"✏️ 남은 항목 채우기 — {len(items)}개 (출처·추가 정보·링크·사진)", expanded=True):
                    st.caption(
                        "찾은 내용을 칸에 입력하고 맨 아래 버튼을 누르면 본문에 바로 반영되고 저장돼. "
                        "비워둔 항목은 그대로 남아 (나중에 채워도 돼). 숫자를 입력하면 숫자 대조에서 "
                        "'직접 입력'으로 인정돼."
                    )
                    ver = st.session_state.ph_ver.get(platform, 0)
                    with st.form(key=f"ph_form_{platform}_{ver}"):
                        fills = {}
                        for i, item in enumerate(items):
                            st.markdown(f"**{i + 1}. {item['label']}** — {item['hint'] or '(설명 없음)'}")
                            if item["context"]:
                                st.caption(f"앞 문장: …{item['context'][-90:]}")
                            text_label, delete_label = PLACEHOLDER_UI[item["kind"]]
                            widget = st.text_area if item["kind"] == "add" else st.text_input
                            text = widget(text_label, key=f"ph_{platform}_{ver}_{i}")
                            delete = st.checkbox(delete_label, key=f"phdel_{platform}_{ver}_{i}")
                            fills[i] = {"text": text, "delete": delete}
                        submitted = st.form_submit_button("✅ 입력한 내용 본문에 반영", type="primary")
                    if submitted:
                        new_body, added = apply_placeholders(body_now, fills)
                        bad_urls = [
                            i + 1 for i, item in enumerate(items)
                            if item["kind"] in ("link", "visual") and fills[i]["text"].strip()
                            and not fills[i]["delete"] and not re.match(r"https?://", fills[i]["text"].strip())
                        ]
                        if bad_urls:
                            st.warning(f"{', '.join(map(str, bad_urls))}번은 http:// 또는 https://로 시작하는 주소만 넣을 수 있어 — 그 항목은 그대로 뒀어.")
                        if new_body.strip() == body_now.strip():
                            st.info("반영할 입력이 없어.")
                        else:
                            if added:
                                inputs.setdefault("user_additions", []).extend(added)
                            edited = current_meta(platform, meta)
                            edited["body"] = new_body
                            persist(platform, compose_draft(edited))
                            st.session_state.ph_ver[platform] = ver + 1
                            st.rerun()
            else:
                st.success("✅ 채울 항목 없음 — 아래 HTML을 복사해서 바로 발행하면 돼.")

            # ── HTML ──
            if platform in ("티스토리", "워드프레스"):
                if platform == "티스토리":
                    where = "티스토리 에디터 오른쪽 위 '기본모드'를 HTML로 바꾼 뒤"
                    html_title = "🧩 HTML 버전 — 소제목·표·목록·요약 박스가 서식으로 이미 들어가 있음"
                    html_code = body_to_html(meta["body"])
                else:
                    where = "워드프레스 편집 화면 오른쪽 위 ⋮ 메뉴 → '코드 편집기'에서"
                    html_title = "🧩 블록 에디터용 HTML — 소제목·문단·표·목록·요약 박스가 각각 블록으로 바로 만들어짐"
                    html_code = body_to_gutenberg(meta["body"])
                with st.expander(html_title, expanded=not items):
                    if items:
                        st.warning(f"아직 채우지 않은 항목 {len(items)}개가 노란 표시로 들어가 있어. 위에서 채우거나 지운 뒤 복사해줘.")
                    st.caption(
                        f"{where} 붙여넣기 (오른쪽 위 복사 아이콘 클릭). 본문 칸에서 직접 고쳤다면 "
                        "💾 저장을 먼저 눌러야 여기에 반영돼. 📌 사진 자리는 기본모드로 돌아와서 사진을 넣고 그 줄을 지워."
                    )
                    if platform == "워드프레스":
                        st.caption("붙여넣은 뒤 ⋮ 메뉴 → '비주얼 편집기'로 돌아오면 블록으로 보여. "
                                   "📌 노란 블록 자리에 이미지 블록을 넣고 그 노란 블록은 지워.")
                    st.code(html_code, language="html")

            # ── 점검 결과 ──
            st.subheader("📋 점검 결과")
            if review["cliche"]:
                st.error("**클리셰/반복 표현**\n" + "\n".join(f"- {i}" for i in review["cliche"]))
            else:
                st.success("클리셰/반복 표현: 없음")

            if review["ai_patterns"]:
                st.error("**AI 말투(반복되는 말버릇·같은 어미)**\n" + "\n".join(f"- {i}" for i in review["ai_patterns"]))
            else:
                st.success("AI 말투(반복되는 말버릇·같은 어미): 문제 없음")

            if review["structure"]:
                st.error("**글 구조(가독성/이미지)**\n" + "\n".join(f"- {i}" for i in review["structure"]))
            else:
                st.success("글 구조(가독성/이미지): 문제 없음")

            if review["seo"]:
                st.error("**검색 최적화(키워드/소제목/메타설명/태그/출처)**\n" + "\n".join(f"- {i}" for i in review["seo"]))
            else:
                st.success("검색 최적화(키워드/소제목/메타설명/태그/출처): 문제 없음")

            if review["claims"]:
                st.warning(
                    "**표시광고 표현 확인 필요** (질병 치료·예방을 암시할 수 있는 표현 — "
                    "'이런 표현은 쓰면 안 된다'는 설명 문맥이면 괜찮아)\n"
                    + "\n".join(f"- {i}" for i in review["claims"])
                    + "\n\n협찬·제공받은 제품이면 글 첫머리에 그 사실을 밝혀야 해 (공정위 추천·보증 심사지침)."
                )
            else:
                st.success("표시광고 표현: 걸리는 표현 없음")

            facts = review["facts"]
            has_materials = any(build_references(inputs).values())
            missing = unverified(facts)
            if not has_materials:
                st.info("숫자 대조: 이 원고는 입력 재료 기록이 없어서 대조를 못 해 (예전에 만든 원고).")
            elif missing:
                st.error(
                    f"**숫자 대조: 근거 확인 안 된 숫자 {len(missing)}개** (메모·출처·의견·직접 입력 어디에도 없음 — "
                    "AI가 지어냈거나 잘못 옮겼을 수 있어. 단위 환산·계산한 숫자면 맞는지 직접 확인)\n"
                    + "\n".join(f"- **{r['number']}** — {r['context']}" for r in missing)
                )
            else:
                st.success(f"숫자 대조: 본문 숫자 {len(facts)}개 모두 입력한 재료에서 확인됨")
            if facts and has_materials:
                with st.expander("🔢 숫자 대조표 전체 보기"):
                    st.dataframe(
                        [{"숫자": r["number"], "본문 문맥": r["context"],
                          "찾은 곳": ", ".join(r["found_in"]) or "❌ 없음"} for r in facts],
                        hide_index=True,
                    )
                    st.caption("'1', '2' 같은 흔한 작은 숫자는 재료 어딘가에 거의 항상 있어서 확인됨으로 나올 수 있어. 숫자만 보고, 기관명 같은 고유명사는 확인하지 않아.")

            copied = review.get("copied", [])
            if copied:
                st.error(
                    f"**원문과 거의 같은 문장 {len(copied)}개** (기사 원문과 6어절 이상 연속으로 같음 — 저작권 문제가 "
                    "될 수 있으니 다듬기를 누르거나 직접 새로 써줘)\n"
                    + "\n".join(f"- {c['sentence']} ← {c['source']}" for c in copied)
                )
            elif inputs.get("material_raw"):
                st.success("원문 복사 검사: 기사 원문을 그대로 옮긴 문장 없음")
            elif inputs.get("mode") == "materials":
                st.info("원문 복사 검사: PDF·캡처 자료는 원문 글자가 없어서 검사를 못 해 (웹페이지 기사만 검사).")

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

            # ── 다듬기 ──
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
                        if author_note.strip():
                            inputs.setdefault("notes", []).append(author_note.strip())
                        persist(platform, revised)
                        st.rerun()

            st.caption("참고: 이건 'AI 티/가독성' 체크일 뿐, 이 플랫폼 자체 검색 알고리즘 점수는 아니야.")

            # ── 발행 체크리스트 ──
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
                    "- 본문: 위 🧩 HTML 버전을 복사 → 에디터 오른쪽 위 '기본모드'를 **HTML**로 바꿔서 붙여넣기 → "
                    "다시 기본모드로 돌아오면 소제목이 제목 서식으로 들어가 있어\n\n"
                    "**사진 삽입 + ALT 입력**: 📌 사진 자리에서 사진 첨부 → 삽입한 사진을 클릭하면 뜨는 "
                    "도구모음에서 대체 텍스트 아이콘 클릭 → 팝업에 안내된 ALT 문구 입력 → 확인 → 📌 줄 삭제.\n\n"
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
                    f"- 오른쪽 설정 패널의 고유주소(URL/슬러그) 칸에: **{meta['slug']}**\n"
                    "- 본문: 위 🧩 HTML 버전을 복사 → ⋮ 메뉴 → '코드 편집기'에 붙여넣기\n\n"
                    "**사진 삽입 + ALT 입력**: 📌 사진 자리에 이미지 블록을 추가하고 사진을 업로드 → "
                    "화면 오른쪽 블록 설정 패널의 'Alt text(대체 텍스트)' 칸에 안내된 ALT 문구 입력 → 📌 줄 삭제."
                )

            st.warning(
                "**모든 플랫폼 공통 — 발행 전 마지막 확인**\n"
                "- **사진 파일명**: [사진 제안]의 '파일명'대로 업로드 전에 사진 파일 이름을 바꿔둬 "
                "(예: IMG_1234.jpg → probiotics-label-check.jpg). 구글 이미지 검색이 파일명도 읽어.\n"
                "- **[출처 필요]·[추가 필요]·[검수]·[내부링크 제안]**: 위 '✏️ 남은 항목 채우기'에서 입력하거나 확인 처리하면 본문에 바로 반영돼. "
                "내부링크는 **실제로 발행된 글**의 주소만 넣어.\n"
                "- **숫자 대조**에서 빨간 숫자가 있으면 원문과 한 번 더 확인."
            )
