"""내가 쓴 글 점검 — 본문은 저자가 직접 쓰고, AI는 포장과 점검만 한다.

- AI가 만드는 것: 제목·제목 후보·카테고리·메타설명·주소·태그, 요약 박스, 소제목 제안(원고에 소제목이 없을 때),
  사진 자리와 ALT, FAQ(선택)
- 포장 단계에서 AI는 본문 문장을 고치지 않는다: AI는 위 정보만 JSON으로 돌려주고, 원고 조립은 이 프로그램이 한다
  (저자 문장은 한 글자도 바뀌지 않음)
- 저자가 원할 때만 '다듬기'(edit_own_draft): ① 맞춤법·오타만 ② 구조 정리(소제목·문단 순서·반복 줄이기)
  (메모·자료로 만든 초안의 결과 화면에서도 같은 함수를 쓴다)
- 자료 노트가 있으면 원고의 사실·수치가 자료와 다른 곳만 찾아 표시한다 (compare_with_notes)
"""
import json
import os
import re

import anthropic
from dotenv import load_dotenv

from blog_drafter import category_rule, tag_rule
from blog_utils import create_text

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

OWN_MIN_CHARS = 500  # 이보다 짧은 원고는 받지 않음
# 원고 안에서 소제목으로 인정하는 줄: "## 제목", "# 제목", "■ 제목", "▶ 제목", "[소제목] 제목"
_HEADING_RE = re.compile(r"^\s*(?:#{1,3}\s+|■\s*|▶\s*|\[소제목\]\s*)(\S.*)$")


def split_own_text(text):
    """원고를 [("h", 소제목) | ("p", 문단)] 목록으로 나눈다. 문단 안의 줄바꿈은 그대로 둔다."""
    items, para = [], []

    def flush():
        if para:
            items.append(("p", "\n".join(para)))
            para.clear()

    for line in (text or "").replace("\r\n", "\n").split("\n"):
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            items.append(("h", heading.group(1).strip()))
        elif not line.strip():
            flush()
        else:
            para.append(line.rstrip())
    flush()
    return items


def _parse_json_object(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise RuntimeError("AI 응답을 읽지 못했어 (형식 오류) — 다시 눌러봐.")
    return json.loads(m.group(0), strict=False)


def package_own_draft(own_text, target_keyword="", platform="워드프레스", want_faq=False):
    """내 원고에 제목·메타·요약·목차·사진 ALT(·FAQ)를 붙여 발행용 원고 텍스트로 조립한다.
    반환: (원고 텍스트, 정보 dict)"""
    items = split_own_text(own_text)
    paragraphs = [t for k, t in items if k == "p"]
    headings = [t for k, t in items if k == "h"]
    if len("".join(paragraphs)) < OWN_MIN_CHARS:
        raise ValueError(f"원고가 너무 짧아 ({len(''.join(paragraphs))}자) — {OWN_MIN_CHARS}자 이상 붙여넣어줘.")

    numbered = []
    n = 0
    for kind, text in items:
        if kind == "h":
            numbered.append(f"(소제목) {text}")
        else:
            n += 1
            numbered.append(f"[{n}] {text}")
    need_headings = len(headings) < 2
    heading_rule = (
        '- "headings": 원고에 소제목이 거의 없어. 문단 사이 자연스러운 자리에 소제목 3~5개를 제안해 — '
        '각 소제목은 사람들이 검색할 법한 질문·키워드로, 그 아래 문단들이 실제로 답하는 내용으로. '
        '그중 1~2개에는 초점 키프레이즈를 글자 그대로 넣어 (전부 넣지는 마). '
        '"before"는 그 소제목이 들어갈 문단 번호 (그 문단 바로 앞에 들어감). 첫 문단(1) 앞에는 넣지 마.'
        if need_headings else '- "headings": 원고에 소제목이 이미 있으니 빈 배열 [] 로 둬.'
    )
    faq_rule = (
        '- "faq": 독자가 실제로 궁금해할 질문 2~4개와 답. 답은 반드시 원고에 있는 내용만으로 1~3문장 '
        '(원고에 답이 없는 질문은 만들지 마).'
        if want_faq else '- "faq": 빈 배열 [] 로 둬.'
    )
    prompt = f"""아래는 블로그 저자가 직접 쓴 원고야. 원고 본문은 절대 고치지 말고, 발행에 필요한 정보만 만들어줘.

타깃 키워드: {target_keyword or "(지정 안 함 — 원고 내용에서 사람들이 실제로 검색할 법한 검색어 하나를 골라 기준으로)"}

만들 것 (모두 원고에 있는 내용만 근거로. 원고에 없는 사실·수치·경험을 보태지 마):
- "title": 초점 키프레이즈를 글자 그대로 한 번 넣은 제목(가능하면 앞쪽에), 20~30자, 낚시성 과장 금지
- "title_candidates": 다른 각도의 제목 후보 2개
- "category": {category_rule()}
- "focus_keyphrase": 초점 키프레이즈 — 타깃 키워드를 글자 그대로 (지정 안 했으면 네가 고른 검색어)
- "meta_description": 검색결과 설명 1~2문장, 120~155자, 원고의 핵심만. 초점 키프레이즈를 글자 그대로 1번 넣고,
  마지막 단어에 조사를 바로 붙이지 마 ("…보장균수는"(X) → "유산균 보장균수 기준", "유산균 보장균수, "(O))
- "slug": 영문 소문자 단어 3~6개를 하이픈으로 연결
- "tags": 태그 목록 — {tag_rule(platform)}
- "summary": "한눈에 보기" 요약 3~4개. 원고 핵심을 한 줄씩, 숫자는 원고에 있는 그대로
{heading_rule}
- "photos": 사진이 있으면 좋을 자리 1~2개. "after"는 그 사진이 들어갈 문단 번호(그 문단 바로 뒤),
  "desc"는 어떤 사진인지, "alt"는 이미지에 실제로 보이는 것을 설명하는 대체 텍스트(그중 1개에는 초점 키프레이즈를
  자연스럽게 넣어), "filename"은 영문 소문자 하이픈 파일명.jpg
{faq_rule}
- 질병 치료·예방으로 읽힐 수 있는 표현은 제목·설명·요약·FAQ 어디에도 쓰지 마.

반드시 아래 JSON 하나만 출력해. 다른 설명 없이.
{{"title": "", "title_candidates": ["", ""], "category": "", "focus_keyphrase": "", "meta_description": "", "slug": "",
 "tags": [""], "summary": [""], "headings": [{{"before": 2, "text": ""}}],
 "photos": [{{"after": 1, "desc": "", "alt": "", "filename": ""}}], "faq": [{{"q": "", "a": ""}}]}}

[원고 — 번호는 문단 번호, (소제목)은 저자가 쓴 소제목]
{chr(10).join(numbered)}"""

    text = create_text(client, model="claude-sonnet-5-5", max_tokens=8000,
                       extra_body={"output_config": {"effort": "low"}},
                       messages=[{"role": "user", "content": prompt}])
    data = _parse_json_object(text)
    return assemble_own_draft(items, data, need_headings), {
        "headings_added": len(data.get("headings") or []) if need_headings else 0,
        "faq": len(data.get("faq") or []) if want_faq else 0,
        "paragraphs": len(paragraphs),
    }


def _clean(value, limit=200):
    return " ".join(str(value or "").split())[:limit]


def assemble_own_draft(items, data, use_ai_headings=True):
    """원고 조각 + AI 정보 → 원고 텍스트 (blog_utils 표기법). 저자 문단은 그대로 옮기기만 한다."""
    n_paragraphs = sum(1 for k, _ in items if k == "p")
    heading_before = {}
    if use_ai_headings:
        for h in data.get("headings") or []:
            try:
                pos = int(h.get("before"))
            except (TypeError, ValueError):
                continue
            if 2 <= pos <= n_paragraphs and _clean(h.get("text")):
                heading_before.setdefault(pos, _clean(h.get("text"), 60))
    photo_after = {}
    for p in data.get("photos") or []:
        try:
            pos = int(p.get("after"))
        except (TypeError, ValueError):
            continue
        if 1 <= pos <= n_paragraphs and _clean(p.get("alt")):
            filename = re.sub(r"[^a-z0-9.-]", "", re.sub(r"[\s_]+", "-", str(p.get("filename", "")).strip().lower())) or "photo.jpg"
            photo_after.setdefault(pos, f'[사진 제안] {_clean(p.get("desc"), 80)} / ALT: "{_clean(p.get("alt"), 120)}" / 파일명: {filename}')

    summary = [_clean(s, 120) for s in (data.get("summary") or []) if _clean(s)]
    heading_count = sum(1 for k, _ in items if k == "h") + len(heading_before)

    body, n, intro_done = [], 0, False

    def add_intro_boxes():
        if summary:
            body.append("[요약]\n" + "\n".join(f"- {s}" for s in summary) + "\n[요약 끝]")
        if heading_count >= 3:
            body.append("[목차]")

    for kind, text in items:
        if kind == "h":
            if not intro_done:
                add_intro_boxes()
                intro_done = True
            body.append(f"[소제목] {text}")
            continue
        n += 1
        if n in heading_before:
            if not intro_done:
                add_intro_boxes()
                intro_done = True
            body.append(f"[소제목] {heading_before[n]}")
        body.append(text)
        if n == 1 and not intro_done:
            add_intro_boxes()
            intro_done = True
        if n in photo_after:
            body.append(photo_after[n])

    faq = [(_clean(f.get("q"), 120), _clean(f.get("a"), 400)) for f in (data.get("faq") or [])
           if _clean(f.get("q")) and _clean(f.get("a"))]
    if faq:
        body.append("[소제목] 자주 묻는 질문")
        body.extend(f"Q. {q}\nA. {a}" for q, a in faq)

    tags = data.get("tags") or []
    tags = ", ".join(_clean(t, 30) for t in (tags if isinstance(tags, list) else str(tags).split(",")) if _clean(t))
    head = [f"[제목] {_clean(data.get('title'), 60)}"]
    head += [f"[제목 후보] {_clean(t, 60)}" for t in (data.get("title_candidates") or []) if _clean(t)]
    head += [f"[카테고리] {_clean(data.get('category'), 40)}",
             f"[메타설명] {_clean(data.get('meta_description'), 200)}",
             f"[주소] {re.sub(r'[^a-z0-9-]', '', str(data.get('slug', '')).lower())}"]
    focus = _clean(data.get("focus_keyphrase"), 60)
    if focus:
        head.append(f"[초점 키프레이즈] {focus}")
    return "\n".join(head) + "\n\n" + "\n\n".join(body) + f"\n\n[태그] {tags}"


def compare_with_notes(own_body, notes_text):
    """원고의 사실·수치가 자료 노트와 다르게 쓰인 곳만 찾는다 (저자 경험·자료에 없는 내용은 지적 안 함).
    반환: [{"quote", "material", "issue"}] — 실패하면 None"""
    prompt = f"""아래 [원고]와 [자료 노트]를 비교해서, 원고에 쓰인 사실·수치·날짜·기관명·인용이 자료 노트와
**서로 다르게** 쓰인 곳만 찾아줘.

지적할 것:
- 같은 대상인데 숫자·단위·날짜·이름·범위가 자료와 다름
- "○○에 따르면"처럼 자료를 인용했는데 그 자료에는 그런 내용이 없거나 반대임
지적하지 말 것:
- 저자의 경험·의견·판단 (자료에 없어도 정상)
- 자료에 아예 없는 내용 (다른 게 아니라 없는 것뿐)
- 표현만 다르고 뜻이 같은 것

반드시 JSON 배열만 출력해. 없으면 [].
[{{"quote": "원고 문장 일부 그대로", "material": "자료 노트의 해당 내용 (자료 번호 포함)", "issue": "무엇이 다른지 한 문장"}}]

[원고]
{own_body}

[자료 노트]
{notes_text}"""
    try:
        text = create_text(client, model="claude-sonnet-5-5", max_tokens=4000,
                           extra_body={"output_config": {"effort": "low"}},
                           messages=[{"role": "user", "content": prompt}])
        m = re.search(r"\[.*\]", text, re.DOTALL)
        items = json.loads(m.group(0), strict=False) if m else []
        return [{k: _clean(i.get(k), 300) for k in ("quote", "material", "issue")}
                for i in items if isinstance(i, dict) and i.get("quote")]
    except Exception as e:
        print(f"⚠️ 자료 대조 실패: {e}")
        return None


# ─────────────────────────────────────────────
# 내 글 다듬기 — 고칠 범위를 저자가 고른다
# ─────────────────────────────────────────────
EDIT_LEVELS = {
    "proofread": "✅ 맞춤법·오타만 고치기 (문장·순서 그대로)",
    "structure": "🧱 구조 정리 (소제목·문단 순서·반복 줄이기 — 내 문장·말투는 최대한 유지)",
}

_FORMAT_RULE = """형식 규칙 (반드시 지켜):
- 맨 위 [제목] [제목 후보] [카테고리] [메타설명] [주소] [초점 키프레이즈] 줄과 맨 끝 [태그] 줄은 그대로 둬.
- [요약]…[요약 끝], [목차], [소제목], [사진 제안], [원문 카드: …], [버튼: …], [링크: …], [[글자 | 주소]], [출처 필요], [추가 필요], [검수] 같은
  대괄호 표시는 지우거나 바꾸지 마 (구조 정리 단계에서 소제목 문구·[요약] 내용은 고쳐도 됨).
- 마크다운 기호(#, * 등)는 쓰지 마.
- 고친 원고 전체만 출력해. 설명이나 변경 내역은 붙이지 마."""


def edit_own_draft(draft, level, target_keyword="", request=""):
    """내가 쓴 원고를 저자가 고른 범위 안에서만 다듬는다.
    level: "proofread"(맞춤법·오타만) | "structure"(구조 정리)
    request: 저자가 추가로 바라는 점 (선택)"""
    if level == "proofread":
        task = """아래 블로그 원고의 맞춤법·띄어쓰기·오타·명백한 문법 오류만 고쳐줘.
- 단어 선택, 문장 순서, 문장 길이, 말투, 내용은 절대 바꾸지 마. 틀린 글자만 고치는 교정이야.
- 구어체·말버릇("근데", "~거든" 등)은 오류가 아니니 그대로 둬.
- 숫자·단위·고유명사·제품명은 건드리지 마 (오타가 확실해 보여도 그대로 두고, 대신 그 문장 끝에
  [검수: 숫자/이름 오타 확인 필요 — 무엇] 을 붙여)."""
    else:
        task = f"""아래 블로그 원고를 읽기 쉽게 구조만 정리해줘. 저자가 확인하고 손본 원고라, 지금 문장과 말투를 최대한 살리는 편집이야.
- 같은 이야기가 반복되거나 흐름이 오락가락하는 부분은 문단 순서를 바꾸거나 합쳐서 정리하고, 중복 문장은 하나만 남겨.
- 검색하는 사람이 이해하기 쉬운 흐름(문제 → 근거 → 판단 기준 → 정리)으로 문단을 배치하고,
  [소제목] 3~5개로 나눠 (각 소제목은 그 아래 내용이 답하는 질문·키워드로{', 하나 이상에 타깃 키워드 "' + target_keyword + '"' if target_keyword else ''}).
- 너무 긴 문단은 나누고, 문단을 잇는 짧은 연결 문장 정도만 새로 써도 돼.
- 저자 문장을 새로 쓰지 말고 그대로 옮기는 게 기본이야. 고친다면 연결·중복 제거·오타 수정에 필요한 만큼만.
- 원고에 없는 사실·숫자·사례·경험은 절대 보태지 마. 빼는 건 반복되는 문장만.
- [요약] 박스 내용은 정리된 본문에 맞게 고쳐도 돼.
- 20어절(띄어쓰기 단위)이 넘는 긴 문장은 두 문장으로 끊어 (내용·말투는 그대로).""" + (f"""
- 초점 키프레이즈 "{target_keyword}": 첫 문단의 첫 두 문장 안에 글자 그대로 1번, 본문 전체에 3회 이상 되게 맞춰.
  새 문장을 보태지 말고, 저자 문장 속 같은 뜻의 표현을 키프레이즈 글자 그대로 바꾸는 방식으로.
  마지막 단어에 조사를 바로 붙이지 마 ("…보장균수는"(X) → "유산균 보장균수 기준은"(O))."""
                                        if target_keyword else "")
    extra = f"\n\n저자가 추가로 바라는 점: {request.strip()}" if request.strip() else ""
    prompt = f"{task}{extra}\n\n{_FORMAT_RULE}\n\n[원고]\n{draft}"
    return create_text(client, model="claude-sonnet-5-5", max_tokens=16000,
                       messages=[{"role": "user", "content": prompt}])
