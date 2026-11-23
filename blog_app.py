"""블로그 초안 생성기 — GUI 버전.
사용법: streamlit run blog_app.py
(또는 run_app.bat 더블클릭)

작성 방식 2가지:
- ✍️ 내 메모로 쓰기: 내가 적은 경험·숫자·의견 + 출처로 초안 작성
- 📰 자료로 쓰기: 기사 링크·PDF·캡처를 읽어 '자료 노트'로 정리 → 주제 제안 → 원고 작성
  (구조 편집·재작성·표/목록·SEO·검수 표시까지, 워드프레스 블록 에디터용 HTML 출력)

- 타깃 키워드 칸 아래 '구글 자동완성으로 키워드 찾기': 실제 검색어 모으기 → 키워드 플래너용 목록·상위 글 확인 링크
- 왼쪽 사이드바: 내 문체 샘플(저장하면 모든 초안·다듬기에 반영), 저장된 원고 불러오기
- 입력칸 내용은 자동 저장 (껐다 켜도 이어서 작성)
- 생성·수정한 원고는 drafts/ 폴더에 자동 저장 (덮어쓸 때 이전 버전은 drafts/history/)
"""
import difflib
import os
import re
from datetime import datetime

import streamlit as st

from blog_drafter import draft_post, suggest_questions, revise_draft
from blog_factcheck import check_numbers, build_references, unverified, find_copied_sentences
from blog_materials import (make_material_note, suggest_topics, draft_from_materials,
                            count_materials, split_notes, AUDIENCES, TONES, LENGTHS,
                            EXPERIENCE_FIELDS, EXPERIENCE_FIELD_MAX, EXPERIENCE_MIN_FIELDS,
                            EXPERIENCE_MIN_TOTAL, format_experience, experience_problem)
from blog_keywords import expand_keyword, google_search_url
from blog_own import package_own_draft, compare_with_notes, edit_own_draft, EDIT_LEVELS, OWN_MIN_CHARS
from blog_reviewer import (scan_cliches, scan_structure, scan_seo, scan_health_claims, scan_ai_patterns,
                           scan_experience_claims, scan_sections, readiness, own_texts,
                           review_draft, collect_issues, ai_issue, AI_REVIEW_LABELS)
from blog_sources import resolve_sources, resolve_files, is_bare_url
from blog_utils import (parse_draft_metadata, load_past_titles, find_keyword_overlap, body_to_html,
                        body_to_gutenberg, find_placeholders, apply_placeholders, compose_draft,
                        write_draft_file, read_draft_file, list_saved_drafts,
                        load_style_sample, save_style_sample, STYLE_SAMPLE_MAX,
                        load_autosave, save_autosave, DATA_DIR, DRAFTS_DIR,
                        load_settings, save_settings, publish_tail, source_cards, card_numbers)

st.set_page_config(page_title="블로그 초안 생성기", page_icon="✍️")

KEY_POINTS_MAX = 1000  # 실제 경험/숫자/사례 최대 글자 수
PERSONAL_TAKE_MAX = 300  # 본인 의견/입장 최대 글자 수
OWN_BODY_MAX = 20000  # 내가 쓴 글 — 원고 최대 글자 수
PLATFORM_CHOICES = ["네이버 블로그", "티스토리", "워드프레스"]
MODE_MEMO = "✍️ 내 메모로 쓰기"
MODE_MATERIALS = "📰 자료로 쓰기 (기사 링크·PDF·캡처)"
MODE_OWN = "📝 내가 쓴 글 가져오기"
OLD_MODE_NAMES = {  # 예전 이름으로 자동 저장된 값
    "📝 내가 쓴 글 점검 (AI는 본문 안 고침)": MODE_OWN,
    "📝 내가 쓴 글 점검·다듬기": MODE_OWN,
}
MODES = [MODE_MEMO, MODE_MATERIALS, MODE_OWN]

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
    "exp_seen": "",
    "exp_myth": "",
    "exp_criteria": "",
    "own_body": "",
    "own_faq": False,
}
# 고를 수 있는 값이 정해진 입력칸 — 저장된 값이 목록에 없으면 기본값으로
INPUT_CHOICES = {"mode": MODES, "mat_audience": AUDIENCES,
                 "mat_tone": list(TONES), "mat_length": LENGTHS}
INPUT_LIMITS = {"key_points_text": KEY_POINTS_MAX, "personal_take_text": PERSONAL_TAKE_MAX,
                "own_body": OWN_BODY_MAX, **{k: EXPERIENCE_FIELD_MAX for k in EXPERIENCE_FIELDS}}
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
    if isinstance(default, bool):
        return bool(value)
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
        # 다듬기 되돌리기·바뀐 곳 보기용 {플랫폼명: …}
        "undo": {}, "last_edit": {},
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if "autosave_loaded" not in st.session_state:
        saved = load_autosave()
        # 예전 '내 의견·실무 경험' 한 칸(mat_opinion)에 적어둔 내용은 '실무에서 본 것' 칸으로 옮김
        saved["mode"] = OLD_MODE_NAMES.get(saved.get("mode"), saved.get("mode"))
        if saved.get("mat_opinion") and not any(saved.get(k) for k in EXPERIENCE_FIELDS):
            saved["exp_seen"] = saved["mat_opinion"]
        # 화면에 안 보이는 입력칸(다른 작성 방식의 칸)은 Streamlit이 값을 지워버려서,
        # 여기(_inputs)에 따로 보관해두고 매번 다시 채운다
        st.session_state._inputs = {key: _clean_input(key, saved.get(key, default))
                                    for key, default in INPUT_DEFAULTS.items()}
        st.session_state.mat_raw = saved.get("mat_raw") if isinstance(saved.get("mat_raw"), dict) else {}
        st.session_state.mat_done = saved.get("mat_done") if isinstance(saved.get("mat_done"), list) else []
        st.session_state.style_sample_text = load_style_sample()
        settings = load_settings()
        st.session_state.set_author_bio = settings["author_bio"]
        st.session_state.set_disclosure = settings["disclosure"]
        st.session_state.set_disclose_ai = bool(settings["disclose_ai"])
        st.session_state.set_categories = "\n".join(settings["categories"])
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


def apply_edit(platform, old_draft, new_draft, label):
    """다듬기 결과를 반영하고, 되돌리기·바뀐 곳 보기를 위해 이전 원고를 기억해 둔다."""
    st.session_state.undo[platform] = old_draft
    st.session_state.last_edit[platform] = {"label": label, "old": old_draft, "new": new_draft}
    persist(platform, new_draft)


def edit_history_ui(platform):
    """방금 다듬기에서 바뀐 곳을 보여주고, 다듬기 전으로 되돌릴 수 있게 한다."""
    edit = st.session_state.last_edit.get(platform)
    if not edit or st.session_state.drafts.get(platform) != edit["new"]:
        return
    def sentences(draft):  # 문단 하나가 한 줄이라, 문장 단위로 쪼개야 바뀐 곳만 보임
        body = parse_draft_metadata(draft)["body"]
        return [x for line in body.split("\n") for x in re.split(r"(?<=[.!?])\s+", line.strip()) if x]
    diff = [l for l in difflib.unified_diff(sentences(edit["old"]), sentences(edit["new"]), lineterm="", n=0)
            if not l.startswith(("---", "+++", "@@"))]
    changed = sum(1 for l in diff if l.startswith("+"))
    with st.expander(f"🔍 방금 다듬기({edit['label']})에서 바뀐 곳 — 문장 {changed}개", expanded=True):
        st.caption("빨간 줄(-)이 원래 문장, 초록 줄(+)이 바뀐 문장이야. 마음에 안 들면 아래 버튼으로 되돌려.")
        st.code("\n".join(diff) or "(본문은 그대로 — 제목·요약 등만 바뀜)", language="diff")
        if st.button("↩️ 다듬기 전으로 되돌리기", key=f"undo_{platform}"):
            persist(platform, st.session_state.undo.pop(platform))
            st.session_state.last_edit.pop(platform, None)
            st.rerun()


def finish_generation(drafts, filenames, inputs, keyword):
    st.session_state.undo, st.session_state.last_edit = {}, {}
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
    for key in ("drafts", "filenames", "reviews", "inputs", "mat_raw", "undo", "last_edit"):
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


def save_settings_cb():
    save_settings({
        "author_bio": st.session_state.set_author_bio.strip(),
        "disclosure": st.session_state.set_disclosure.strip(),
        "disclose_ai": st.session_state.set_disclose_ai,
        "categories": lines_of(st.session_state.set_categories),
    })
    st.session_state.reviews = {}  # 카테고리·저자 소개가 바뀌면 점검을 다시 하게


def written_date(path):
    """원고 파일 이름(YYYYMMDD_...)에서 작성일을 '2026년 11월 21일' 형태로."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})_", os.path.basename(path or ""))
    return f"{m.group(1)}년 {int(m.group(2))}월 {int(m.group(3))}일" if m else ""


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
    st.session_state.undo, st.session_state.last_edit = {}, {}
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
        experience = inputs.get("experience") or {"exp_seen": inputs.get("personal_take", "")}
        for key in EXPERIENCE_FIELDS:
            set_input(key, _clean_input(key, experience.get(key, "")))
        for key, field in (("mat_audience", "audience"), ("mat_tone", "tone"), ("mat_length", "length")):
            set_input(key, _clean_input(key, inputs.get(field)))
        st.session_state.mat_raw = inputs.get("material_raw", {})
    elif inputs.get("mode") == "own":
        set_input("mode", MODE_OWN)
        set_input("own_body", _clean_input("own_body", inputs.get("own_body", "")))
        set_input("own_faq", bool(inputs.get("want_faq")))
        set_input("mat_notes", "\n\n".join(inputs.get("sources", [])))
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
    st.header("👤 저자 소개·사이트 설정")
    st.caption("저장하면 모든 글의 발행용 HTML 끝에 '참고 자료'와 '글쓴이' 박스가 자동으로 붙어. "
               "누가, 어떤 근거로 썼는지 보여주는 게 구글이 보는 신뢰 신호야.")
    st.text_area(
        "저자 소개 (2~4줄)", key="set_author_bio", height=110,
        placeholder="예) 식품공학을 전공하고 홈쇼핑 품질관리 업무를 ○년째 하고 있습니다. "
                    "건강기능식품 표시·광고 검토와 수입식품 서류 검토를 담당합니다.",
        help="회사 이름은 넣지 않는 걸 권장. 전공·경력·담당 업무처럼 전문성을 보여주는 내용 위주로.",
    )
    st.text_input("이해관계 고지 (선택)", key="set_disclosure",
                  placeholder="예) 이 글에 나온 업체·제품과 금전적 관계가 없습니다.")
    st.checkbox("AI 도구 도움을 받았다고 글 끝에 밝히기", key="set_disclose_ai",
                help="의무는 아니야 (구글은 AI 사용 여부가 아니라 글 품질로 평가해). 켜면 글 끝에 "
                     "'초안 정리에 AI 도구의 도움을 받았고, 내용 확인과 최종 판단은 필자가 했습니다'가 붙어. "
                     "협찬·제휴 링크가 있을 때 밝히는 '이해관계 고지'는 이것과 별개로 꼭 써야 해.")
    st.text_area(
        "내 블로그 카테고리 목록 (한 줄에 하나)", key="set_categories", height=110,
        placeholder="예)\n건강기능식품 표시·광고\n식품 안전·이슈\n재테크",
        help="적어두면 AI가 이 중에서만 고르고, 목록에 없는 카테고리는 점검에서 지적해. 비우면 AI가 자유롭게 정해.",
    )
    st.button("💾 저자 소개·설정 저장", on_click=save_settings_cb)
    saved_settings = load_settings()
    if saved_settings["author_bio"].strip():
        st.success("저자 소개 저장됨 — 발행용 HTML에 자동으로 붙어")
    else:
        st.warning("저자 소개가 비어 있어 — 티스토리·워드프레스 글은 '발행 준비'에서 막혀.")

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

mode = st.radio("작성 방식", MODES, key="mode", horizontal=True)
platforms = st.multiselect(
    "어디에 발행할 거야? (여러 개 선택 가능 — 선택한 만큼 따로 생성됨)",
    PLATFORM_CHOICES, key="platforms",
)
if "티스토리" in platforms and "워드프레스" in platforms:
    st.warning("**중복 콘텐츠 주의** — 같은 주제를 티스토리와 워드프레스에 둘 다 올리면 내용이 거의 같아서, 구글이 하나만 검색에 보여주고 나머지는 거의 숨겨 — 두 블로그가 서로 경쟁하게 돼. 원칙은 '한 주제는 한 블로그'. 굳이 둘 다 쓸 거면 주제나 관점을 확실히 나눠서 (예: 소비자 관점 / 실무자 관점) 따로 생성해.")


def use_suggestion_cb():
    pick = st.session_state.get("ac_pick")
    if pick:
        set_input("kw_input", pick)


def keyword_suggest_ui(topic=""):
    """구글 자동완성으로 실제 검색어를 모아 보여주고, 골라서 타깃 키워드로 쓰게 한다.
    타깃 키워드 칸보다 먼저 그린다 (주제 → 실제 검색어 보기 → 타깃 키워드 고르기 순서)."""
    keyword = st.session_state.get("kw_input", "")
    with st.expander("🔎 구글 자동완성으로 키워드 찾기 (무료) — 타깃 키워드 정하기 전에",
                     expanded=not keyword.strip()):
        st.caption(
            "사람들이 구글 검색창에 **실제로 이어서 치는 검색어**를 모아줘 (방법·차이·기준·부작용 등으로 넓혀서). "
            "검색량은 안 나오니까, 아래 목록을 복사해서 구글 키워드 플래너 → '검색량 및 예측 가져오기'에 붙여넣어 확인해. "
            "AI 비용 없음 · 10~20초 걸려."
        )
        seed = st.text_input("기본 검색어", key="ac_seed",
                             placeholder=keyword.strip() or topic.strip() or "예: 유산균 보장균수")
        seed = seed.strip() or keyword.strip() or topic.strip()
        if st.button("🔎 자동완성 불러오기", key="ac_run", disabled=not seed):
            with st.spinner(f"구글 자동완성 모으는 중... ({seed})"):
                try:
                    st.session_state.ac_result = {"seed": seed, **expand_keyword(seed)}
                except Exception as e:
                    st.session_state.ac_result = None
                    st.error(f"❌ {e}\n인터넷 연결을 확인하고, 잠시 뒤 다시 눌러봐. "
                             "(구글이 짧은 시간에 여러 번 물어보면 잠깐 막을 때가 있어)")

        result = st.session_state.get("ac_result")
        if result:
            if not result["all"]:
                st.info(f"'{result['seed']}'로는 자동완성이 거의 없어 — 검색하는 사람이 적은 표현일 수 있어. "
                        "더 짧거나 흔한 말로 바꿔서 다시 해봐.")
            else:
                st.markdown(f"**'{result['seed']}' 관련 검색어 {len(result['all'])}개**")
                for group, items in result["groups"].items():
                    st.markdown(f"{group}: " + " · ".join(items))
                if result.get("failed"):
                    st.caption(f"(일부 {result['failed']}번은 못 불러와서 빠졌어)")
                st.caption("키워드 플래너에 붙여넣을 목록 (오른쪽 위 복사 버튼):")
                st.code("\n".join([result["seed"]] + result["all"]), language=None)
                st.selectbox("타깃 키워드로 쓸 검색어", result["all"], key="ac_pick")
                st.button("✅ 이 검색어를 타깃 키워드로 (아래 칸에 들어가)", key="ac_use", on_click=use_suggestion_cb)


def top_results_link(keyword):
    """타깃 키워드로 구글 상위 글을 직접 보러 가는 버튼 (경쟁 판단용)."""
    if keyword.strip():
        st.link_button(f"🌐 구글에서 '{keyword.strip()}' 검색해서 상위 글 보기", google_search_url(keyword.strip()))
        st.caption("상위 10개가 공공기관·대형 언론·백과사전 위주면 경쟁이 세고, 오래된 글·얕은 블로그 글·"
                   "질문에 제대로 답 안 하는 글이 섞여 있으면 기회야. (시크릿 창에서 보면 더 정확해)")


def keyword_inputs():
    topic = st.text_input("주제", key="topic", placeholder="예: 홈쇼핑 유산균 표시광고, 뭐가 문제인가")
    keyword_suggest_ui(topic)
    keyword = st.text_input(
        "타깃 키워드 (이 글로 잡고 싶은 검색어 — 비우면 AI가 고름)", key="kw_input",
        placeholder="예: 유산균 보장균수",
        help="위 '구글 자동완성으로 키워드 찾기'에서 실제 검색어를 골라 쓰면 좋아.",
    )
    top_results_link(keyword)
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
# 자료 넣기 (자료로 쓰기·내가 쓴 글 가져오기 공용)
# ─────────────────────────────────────────────
def materials_input_ui(note_label):
    """기사 링크·PDF·캡처를 읽어 자료 노트로 정리하는 화면 조각. 반환: 자료 노트 글자"""
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
    if st.button(read_label, disabled=not (new_urls or mat_files)):
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
    notes_text = st.text_area(
        note_label, key="mat_notes", height=280,
        help="AI가 정리한 거라 원문과 대조해서 틀린 부분은 여기서 직접 고쳐줘. 직접 메모를 '[자료 N] 출처' 형식으로 추가해도 돼.",
    )
    col_a, col_b = st.columns([3, 1])
    col_a.caption(f"자료 {count_materials(notes_text)}개 · {len(notes_text):,}자 · 이미 읽은 링크는 다시 읽지 않아")
    col_b.button("🗑️ 자료 비우기", on_click=clear_materials_cb)
    return notes_text


def experience_values():
    return {k: st.session_state.get(k, "") for k in EXPERIENCE_FIELDS}


# ─────────────────────────────────────────────
# 📰 자료로 쓰기
# ─────────────────────────────────────────────
if mode == MODE_MATERIALS:
    st.info(
        "기사 링크·PDF·캡처를 **자료 노트**로 정리하고, **내 실무 경험**을 중심으로 원고를 짜. "
        "자료는 내 판단을 뒷받침하는 근거로만 쓰여 — 자료만 다시 정리한 글은 구글이 낮게 보기 때문에 "
        "경험 칸은 **필수**야. 인정 범위를 벗어난 표현이나 자료끼리 충돌하는 내용은 [검수] 표시로 남겨."
    )

    st.subheader("1️⃣ 자료 넣기")
    mat_notes = materials_input_ui(
        "📒 자료 노트 — AI가 원문을 사실·수치 위주로 다시 정리한 것 (이 노트가 원고의 근거로 쓰여)")

    st.subheader("2️⃣ 내 실무 경험 (필수)")
    st.caption(
        f"글의 뼈대가 되는 부분이야. 칸을 {EXPERIENCE_MIN_FIELDS}개 이상, 합계 {EXPERIENCE_MIN_TOTAL}자 이상 채워야 "
        "원고를 쓸 수 있어. 소제목도 이 경험을 중심으로 짜여 (오해 → 바로잡는 섹션, 기준 → 체크리스트 섹션)."
    )
    placeholders = {
        "exp_seen": "예) 라벨 검토하다 보면 '혈당 케어'만 크게 쓰고 기능성 원료명은 뒷면에 작게 적은 제품이 꽤 많다.",
        "exp_myth": "예) '혈당 영양제'면 다 기능성을 인정받은 줄 아는데, 일반식품인데 이름만 비슷하게 붙인 경우도 있다.",
        "exp_criteria": "예) 나는 기능성 인정 문구가 정확히 적혀 있는지, 1일 섭취량 기준 함량이 있는지부터 본다.",
    }
    for key, label in EXPERIENCE_FIELDS.items():
        st.text_area(label, key=key, height=90, max_chars=EXPERIENCE_FIELD_MAX, placeholder=placeholders[key])
    exp_vals = experience_values()
    exp_issue = experience_problem(exp_vals)
    exp_total = sum(len(v.strip()) for v in exp_vals.values())
    if exp_issue:
        st.warning(f"⛔ {exp_issue} — 경험이 부족하면 '자료를 다시 정리한 글'이 돼서 구글 평가가 낮아져.")
    else:
        st.success(f"✅ 경험 입력 충분 (합계 {exp_total:,}자)")

    st.subheader("3️⃣ 주제 정하기")
    if st.button("💡 이 자료와 내 경험으로 쓸 만한 주제 제안받기", disabled=not mat_notes.strip()):
        with st.spinner("자료와 경험을 보고 주제를 고르는 중..."):
            st.session_state.topic_ideas = suggest_topics(
                mat_notes, st.session_state.mat_audience, format_experience(exp_vals))
        if not st.session_state.topic_ideas:
            st.warning("주제 제안에 실패했어 — 다시 눌러보거나 아래 주제를 직접 적어줘.")
    st.caption("큰 주제(예: '혈당 영양제')는 경쟁이 세서, QA 실무자의 판단이 차별점이 되는 좁은 주제 위주로 제안해. "
               "경험 칸을 먼저 채우면 더 잘 맞는 주제가 나와.")
    for i, idea in enumerate(st.session_state.topic_ideas):
        with st.container(border=True):
            st.markdown(f"**{idea['title']}**")
            st.caption(f"키워드: {idea['keyword']} · {idea['materials']}")
            st.write(idea["angle"])
            if idea.get("edge"):
                st.caption(f"🎯 차별점: {idea['edge']}")
            st.button("이 주제로 정하기", key=f"pick_idea_{i}", on_click=pick_idea_cb, args=(i,))
    topic, target_keyword = keyword_inputs()

    st.subheader("4️⃣ 글 설정")
    col1, col2 = st.columns(2)
    with col1:
        st.selectbox("독자", AUDIENCES, key="mat_audience")
        st.select_slider("분량 (본문)", options=LENGTHS, key="mat_length", format_func=lambda n: f"{n:,}자 내외")
    with col2:
        st.radio("말투", list(TONES), key="mat_tone")
    autosave_inputs()

    if st.button("✍️ 자료로 원고 쓰기", type="primary"):
        if not mat_notes.strip():
            st.error("자료 노트가 비어 있어. 먼저 자료를 읽어서 정리해줘.")
        elif exp_issue:
            st.error(f"내 실무 경험이 부족해: {exp_issue}.")
        elif not topic.strip():
            st.error("주제를 정해줘 (제안받은 주제에서 고르거나 직접 입력).")
        elif not platforms:
            st.error("발행할 곳을 하나 이상 선택해줘.")
        else:
            opinion = format_experience(exp_vals)
            inputs = {
                "mode": "materials", "topic": topic, "target_keyword": target_keyword.strip(),
                "key_points": [v.strip() for v in exp_vals.values() if v.strip()],
                "sources": split_notes(mat_notes), "personal_take": opinion,
                "experience": exp_vals, "notes": [], "user_additions": [],
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
# 📝 내가 쓴 글 가져오기
# ─────────────────────────────────────────────
elif mode == MODE_OWN:
    st.info(
        "내가 직접 쓴 원고를 붙여넣으면, 먼저 **본문은 그대로 둔 채** 제목 후보·메타설명·요약 박스·"
        "목차·사진 자리와 ALT(·FAQ)를 만들어 붙이고 점검해. 자료 노트가 있으면 원고의 수치·사실이 "
        "자료와 **다르게 쓰인 곳**도 찾아줘.\n\n"
        "그다음 결과 화면 맨 아래 **✨ 다듬기**에서 원할 때만 ① 맞춤법·오타만 ② 구조 정리(소제목·문단 순서) 중 "
        "골라 고칠 수 있어 — 바뀐 곳을 보여주고, 마음에 안 들면 되돌릴 수 있어. "
        "(메모·자료로 만든 초안도 결과 화면에서 똑같이 다듬을 수 있어)"
    )

    st.subheader("1️⃣ 내 원고")
    own_body = st.text_area(
        f"원고 붙여넣기 (최소 {OWN_MIN_CHARS}자)", key="own_body", height=360, max_chars=OWN_BODY_MAX,
        placeholder="메모장·워드에서 쓴 원고를 그대로 붙여넣어.\n\n## 소제목은 이렇게 줄 맨 앞에 ## 를 붙이면 그대로 소제목이 돼 (■, ▶ 도 돼)\n\n소제목이 없으면 AI가 넣을 자리를 제안해 — 문장은 안 바꿔.",
    )
    st.caption(f"{len(own_body):,}자")
    keyword_suggest_ui()
    own_keyword = st.text_input(
        "타깃 키워드 (이 글로 잡고 싶은 검색어 — 비우면 AI가 원고에서 고름)", key="kw_input",
        placeholder="예: 혈당 영양제 기능성 문구",
    )
    top_results_link(own_keyword)

    st.subheader("2️⃣ 근거 자료 (선택)")
    st.caption("원고에서 인용한 기사·PDF를 넣으면, 원고의 수치·사실이 자료와 다르게 쓰인 곳을 찾아줘. "
               "자료에 링크가 있으면 원문 카드·참고 자료 목록에도 쓰여.")
    own_notes = materials_input_ui("📒 자료 노트 (원고와 대조할 근거)")

    st.subheader("3️⃣ 옵션")
    st.checkbox("FAQ(자주 묻는 질문) 만들기 — 원고에 답이 있는 질문만", key="own_faq",
                help="구글은 2023년부터 대부분의 사이트에서 FAQ를 검색결과에 펼쳐 보여주지 않아. "
                     "독자에게 실제로 도움이 될 때만 켜.")
    autosave_inputs()

    if st.button("🧩 제목·요약·목차 만들고 점검하기", type="primary"):
        if len(own_body.strip()) < OWN_MIN_CHARS:
            st.error(f"원고가 너무 짧아 — {OWN_MIN_CHARS}자 이상 붙여넣어줘.")
        elif not platforms:
            st.error("발행할 곳을 하나 이상 선택해줘.")
        else:
            inputs = {
                "mode": "own", "topic": "", "target_keyword": own_keyword.strip(),
                "own_body": own_body, "want_faq": st.session_state.own_faq,
                # 원고 전체가 저자 글 — 경험 점검·숫자 대조에서 '저자가 쓴 것'으로 인정됨
                "key_points": lines_of(own_body), "personal_take": "",
                "sources": split_notes(own_notes), "notes": [], "user_additions": [],
                "material_raw": dict(st.session_state.mat_raw),
            }
            drafts, filenames = {}, {}
            for platform in platforms:
                with st.spinner(f"⏳ {platform}용 제목·요약·목차 만드는 중..."):
                    try:
                        draft, info = package_own_draft(own_body, own_keyword.strip(), platform,
                                                        want_faq=st.session_state.own_faq)
                    except Exception as e:
                        st.error(f"❌ {platform} 처리 실패: {e}")
                        continue
                inputs["topic"] = inputs["topic"] or parse_draft_metadata(draft)["title"]
                path = new_draft_path(platform)
                write_draft_file(path, inputs["topic"], platform, own_keyword.strip(), draft, inputs)
                drafts[platform], filenames[platform] = draft, path
            if drafts:
                finish_generation(drafts, filenames, inputs, own_keyword.strip())

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
                        "experience": scan_experience_claims(meta["body"], own_texts(inputs)),
                        "sections": scan_sections(meta["body"]),
                        # 내가 쓴 글 + 자료 노트가 있을 때만: 원고가 자료와 다르게 쓴 곳 (AI 1회)
                        "mismatch": (compare_with_notes(meta["body"], "\n\n".join(inputs["sources"]))
                                     if inputs.get("mode") == "own" and inputs.get("sources") else []),
                        "ai": review_draft(draft),
                        "overlap": find_keyword_overlap(
                            platform, st.session_state.target_keyword,
                            exclude=st.session_state.filenames.values(),
                        ),
                    }
            review = st.session_state.reviews[platform]

            rows = readiness(review, meta["body"], inputs, load_settings(), platform)
            blocks = [r for r in rows if r[1] == "block"]
            warns = [r for r in rows if r[1] == "warn"]
            icon = {"ok": "✅", "block": "⛔", "warn": "⚠️"}
            if blocks:
                st.error(f"🚦 **발행 준비 안 됨 — 해결할 항목 {len(blocks)}개**\n"
                         + "\n".join(f"- ⛔ {name}: {detail}" for name, _, detail in blocks))
            else:
                st.success("🚦 **발행 준비 완료** — 반드시 해결할 항목 없음"
                           + (f" (확인 권장 {len(warns)}개는 아래 참고)" if warns else ""))
            with st.expander("🚦 발행 준비 체크리스트 전체 보기"):
                for name, state, detail in rows:
                    st.write(f"{icon[state]} **{name}** — {detail}")
                st.caption("⛔ = 발행 전 반드시 해결 · ⚠️ = 확인 권장 · ⛔가 0개가 되면 아래 HTML을 복사해서 발행하면 돼.")

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

            # ── HTML ── (본문 + 참고 자료 + 글쓴이 박스)
            settings = load_settings()
            tail = publish_tail(inputs, settings, written_date(st.session_state.filenames.get(platform)))
            publish_body = meta["body"] + ("\n\n" + tail if tail else "")
            cards = source_cards(inputs)
            if platform in ("티스토리", "워드프레스"):
                if platform == "티스토리":
                    where = "티스토리 에디터 오른쪽 위 '기본모드'를 HTML로 바꾼 뒤"
                    html_title = "🧩 HTML 버전 — 소제목·표·목록·요약 박스가 서식으로 이미 들어가 있음"
                    html_code = body_to_html(publish_body, cards)
                else:
                    where = "워드프레스 편집 화면 오른쪽 위 ⋮ 메뉴 → '코드 편집기'에서"
                    html_title = "🧩 블록 에디터용 HTML — 소제목·문단·표·목록·요약 박스가 각각 블록으로 바로 만들어짐"
                    html_code = body_to_gutenberg(publish_body, cards)
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
                    if tail:
                        st.caption("맨 끝에 '참고 자료'(원문 링크)와 '글쓴이' 박스가 자동으로 붙어 있어 — 본문 칸에는 안 보여.")
                    used = [n for n in card_numbers(meta["body"]) if n in cards]
                    if used:
                        st.caption(f"📰 본문 속 원문 카드 {len(used)}개 → '원문 보기' 버튼이 있는 링크 박스로 바뀌어 있어.")
                    elif cards:
                        st.caption("📰 링크가 있는 출처가 있는데 본문에 원문 카드가 없어. 넣고 싶은 문단 다음 줄에 "
                                   "[원문 카드: 번호]를 적고 💾 저장하면 돼 (번호는 자료 노트의 [자료 N] / 출처 칸의 줄 순서).")
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

            mismatch = review.get("mismatch", [])
            if mismatch is None:
                st.warning("자료 대조: 원고와 자료 노트 비교에 실패했어 — '🔁 다시 점검'을 눌러봐.")
            elif mismatch:
                st.error(
                    f"**자료와 다르게 쓴 곳 {len(mismatch)}개** (원고의 수치·사실이 자료 노트와 다름 — 원문을 확인하고 "
                    "본문 칸에서 직접 고친 뒤 💾 저장)\n"
                    + "\n".join(f"- 원고: {m['quote']}\n  - 자료: {m['material']}\n  - {m['issue']}" for m in mismatch)
                )
            elif inputs.get("mode") == "own" and inputs.get("sources"):
                st.success("자료 대조: 원고와 자료 노트가 다르게 쓰인 곳 없음")

            experience = review.get("experience", [])
            if experience:
                st.error(
                    f"**지어낸 경험 의심 {len(experience)}개** (저자 메모·의견에 근거가 없는 '실무에서 보면', "
                    "'직접 확인해 보니' 같은 경험 주장 — 실제 경험이면 메모에 적고 다듬기, 아니면 빼야 해)\n"
                    + "\n".join(f"- {e}" for e in experience)
                )
            else:
                st.success("경험 주장: 메모·의견에 근거 없는 경험 주장 없음")

            if review.get("sections"):
                st.warning("**검색 의도 (섹션마다 답을 주는지)**\n" + "\n".join(f"- {i}" for i in review["sections"]))
            else:
                st.success("검색 의도: 섹션마다 내용이 충분함")

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
            edit_history_ui(platform)
            is_own = inputs.get("mode") == "own"
            issues = [] if is_own else collect_issues(review)
            levels = {**({} if is_own else {"review": f"🩺 점검 지적 반영 (지적된 {len(issues)}건 고치기)"}), **EDIT_LEVELS}
            st.subheader("✨ 다듬기")
            st.caption(
                ("AI 초안이면 먼저 '점검 지적 반영'으로 지적된 곳을 고치고, 본문을 직접 손본 뒤 마지막에 "
                 "'맞춤법·오타만'을 한 번 돌리는 걸 추천해. " if not is_own else
                 "처음엔 '맞춤법·오타만'을 추천해 — 내 문장이 그대로 남아서 '내 글'의 장점이 살아. ")
                + "글이 길고 흐름이 오락가락하면 '구조 정리'를 써. 어느 쪽이든 원고·재료에 없는 사실·숫자·경험은 "
                "보태지 않고, 바뀐 곳을 보여주고 되돌릴 수 있어. 누르면 Claude를 1번 호출해."
            )
            level = st.radio("다듬기 범위", list(levels), format_func=levels.get,
                             key=f"edit_level_{inputs.get('mode', 'memo')}_{platform}")
            if level == "review":
                request = st.text_area(
                    "추가 메모 (선택) — 지적을 해결할 구체적인 사실·사례·의견이 있으면 적어줘",
                    height=90, key=f"note_{platform}",
                    placeholder="예) 구체성 부족 지적 → 지난달 점검한 A제품은 균주명 없이 '500억 보장'만 표기돼 있었음",
                )
            else:
                request = st.text_area("추가로 바라는 점 (선택)", height=68, key=f"note_{platform}",
                                       placeholder="예) 마지막 문단의 내 결론은 꼭 그대로 둬 / 소제목은 질문형으로")
            label = levels[level].split(" (")[0]
            if st.button("✨ 다듬기 실행", key=f"revise_{platform}", type="primary"):
                edited = ""
                if level == "review" and not issues and not request.strip():
                    st.info("지적된 부분도 추가 메모도 없어서 다듬을 게 없어. '맞춤법·오타만'이나 '구조 정리'를 골라봐.")
                else:
                    with st.spinner(f"⏳ {label} 하는 중..."):
                        try:
                            if level == "review":
                                edited = revise_draft(
                                    draft, issues, inputs.get("key_points", []),
                                    sources=inputs.get("sources"),
                                    personal_take=inputs.get("personal_take", ""),
                                    author_note=request.strip(), platform=platform,
                                    target_keyword=st.session_state.target_keyword,
                                )
                            else:
                                edited = edit_own_draft(draft, level, st.session_state.target_keyword, request)
                        except Exception as e:
                            st.error(f"❌ 다듬기 실패: {e}\n(네트워크 문제일 수 있어 — 다시 눌러봐)")
                if edited and edited.strip() == draft.strip():
                    st.info(
                        "수정본이 이전 원고와 똑같아 — 지적된 부분을 AI가 재료 없이는 고칠 수 없다고 판단한 거야. "
                        "위 '추가 메모'에 그 지적을 해결할 사실·사례·기준을 적고 다시 눌러봐."
                        if level == "review" else "고칠 곳이 없대 — 이미 깔끔한 원고야."
                    )
                elif edited:
                    if not parse_draft_metadata(edited)["title"]:
                        st.error("❌ 다듬은 결과의 형식이 깨져서 반영하지 않았어. 다시 눌러봐.")
                    else:
                        if request.strip():
                            inputs.setdefault("notes", []).append(request.strip())
                        apply_edit(platform, draft, edited, label)
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
