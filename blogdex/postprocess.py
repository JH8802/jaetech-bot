"""AI가 쓴 원고를 서버에서 다듬는 후처리.

태그 정리, 형광펜 개수 제한, 해시태그 정리, 지도 줄 삽입, 글자수 계산.
글자수 기준은 DESIGN.md §2.8/§2.12 에서 확인한 규칙을 따릅니다.
(태그 제거, 해시태그 문단 제외, 공백 제외)
"""
import re

TAG_RE = re.compile(r"\{\{(/?)(bold|color|highlight)\}\}")
UNKNOWN_TAG_RE = re.compile(r"\{\{/?(?!bold\b|color\b|highlight\b)[A-Za-z_]+\}\}")
HEADING_RE = re.compile(r"^\d+\.\s")
MAP_LINE_MARK = "플레이스 지도 삽입"
MAX_HASHTAGS = 30


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]", "", strip_tags(s)).replace("제목", "")


def clean_markdown(text: str, title: str = "") -> tuple[str, list[str]]:
    """AI가 형식을 어겼을 때의 안전장치: 코드블록·마크다운 굵게·소제목 기호·목록 기호·맨 앞 제목 줄을 정리합니다."""
    notes = []
    fixed = re.sub(r"(?m)^\s*```.*$", "", text)
    fixed, n_bold = re.subn(r"\*\*(.+?)\*\*", r"{{bold}}\1{{/bold}}", fixed)
    fixed, n_head = re.subn(r"(?m)^\s*#{1,6}\s+", "", fixed)  # '## 1. 소제목' → '1. 소제목' (해시태그는 # 뒤에 공백이 없어 영향 없음)
    fixed, n_list = re.subn(r"(?m)^\s*[-*•]\s+", "", fixed)
    if n_bold or n_head or n_list:
        notes.append("마크다운 기호를 블로그 형식으로 바꿨어요.")
    paras = split_paragraphs(fixed)
    if paras and title and _norm(paras[0]) == _norm(title):
        paras.pop(0)
        notes.append("본문 맨 앞의 제목 줄을 뺐어요.")
    return "\n\n".join(paras), notes


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text)


def _normalize_paragraph_tags(par: str) -> str:
    """한 문단 안에서 태그를 짝 맞추고, 열린 태그는 문단 끝에서 닫습니다."""
    out, stack, pos = [], [], 0
    for m in TAG_RE.finditer(par):
        out.append(par[pos:m.start()])
        pos = m.end()
        closing, name = m.group(1) == "/", m.group(2)
        if not closing:
            if name in stack:
                continue  # 이미 열린 태그를 또 열면 무시
            stack.append(name)
            out.append("{{%s}}" % name)
        elif name in stack:
            while stack and stack[-1] != name:  # 안쪽에 열린 태그부터 닫아 겹침 방지
                out.append("{{/%s}}" % stack.pop())
            stack.pop()
            out.append("{{/%s}}" % name)
        # 여는 태그 없이 나온 닫는 태그는 버림
    out.append(par[pos:])
    while stack:
        out.append("{{/%s}}" % stack.pop())
    return "".join(out)


def normalize_tags(text: str) -> str:
    text = UNKNOWN_TAG_RE.sub("", text)
    paras = [_normalize_paragraph_tags(p) for p in split_paragraphs(text)]
    body = "\n\n".join(paras)
    # 마침표·쉼표는 태그 밖으로 (형광펜 뒤에 ' .' 이 생기는 문제 방지)
    body = re.sub(r"[ \t]*([.,])(\{\{/(?:bold|color|highlight)\}\})", r"\2\1", body)
    return body


def limit_highlights(text: str, keep: int = 2) -> tuple[str, int]:
    """형광펜은 keep 곳만 남기고 나머지는 굵게로 바꿉니다. 반환: (본문, 원래 개수)"""
    pattern = re.compile(r"\{\{highlight\}\}(.*?)\{\{/highlight\}\}", re.S)
    total = len(pattern.findall(text))
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        return m.group(0) if count <= keep else "{{bold}}%s{{/bold}}" % m.group(1)

    return pattern.sub(repl, text), total


def find_hashtag_index(paras: list[str]) -> int | None:
    for i in range(len(paras) - 1, -1, -1):
        if paras[i].startswith("#") and paras[i].count("#") >= 3:
            return i
    return None


def normalize_hashtags(tag_text: str, must_have: list[str] | None = None, limit: int = MAX_HASHTAGS) -> str:
    raw = re.findall(r"#[^\s#]+", tag_text)
    cleaned, seen = [], set()
    # 필수 태그(상호·핵심 키워드)를 맨 앞에 두고, 이어서 AI가 쓴 태그를 이어 붙입니다.
    candidates = ["#" + t.lstrip("#").replace(" ", "") for t in (must_have or []) if t.strip()] + raw
    for t in candidates:
        t = re.sub(r"[.,!?~]+$", "", t.replace(" ", ""))
        if len(t) < 2 or t.lower() in seen:
            continue
        seen.add(t.lower())
        cleaned.append(t)
    return " ".join(cleaned[:limit])


def insert_map_line(text: str, place_name: str) -> str:
    """맛집글: 1번 섹션 끝(2번 소제목 앞)에 지도 삽입 자리 줄을 넣습니다."""
    if MAP_LINE_MARK in text or not place_name:
        return text
    paras = split_paragraphs(text)
    line = f"(플레이스 지도 삽입: 〈{place_name}〉)"
    heads = [i for i, p in enumerate(paras) if HEADING_RE.match(strip_tags(p))]
    if len(heads) >= 2:
        paras.insert(heads[1], line)
    elif heads:
        end = find_hashtag_index(paras)
        paras.insert(end if end is not None else len(paras), line)
    else:
        return text
    return "\n\n".join(paras)


def count_chars(text: str) -> int:
    """화면 카운터와 같은 기준: 태그 제거, 해시태그 문단 제외, 공백 제외."""
    paras = split_paragraphs(strip_tags(text))
    idx = find_hashtag_index(paras)
    if idx is not None:
        paras.pop(idx)
    return len(re.sub(r"\s", "", "\n".join(paras)))


def region_of(place: dict | None) -> str:
    """주소에서 구 이름을 뽑습니다. (예: '서울 마포구 백범로' → '마포')"""
    m = re.search(r"([가-힣]{2,})구", (place or {}).get("address", ""))
    return m.group(1) if m else ""


def finalize(kind: str, raw: str, place: dict | None, keywords: list[str], title: str = "") -> dict:
    """원고를 정리해 {body, chars, notes} 를 돌려줍니다."""
    body, notes = clean_markdown(raw.replace("\r\n", "\n"), title)
    body = normalize_tags(body)
    body, hl = limit_highlights(body, 2)
    if hl > 2:
        notes.append(f"형광펜 {hl}곳 중 2곳만 남겼어요.")
    elif hl < 2:
        notes.append(f"형광펜이 {hl}곳이에요(권장 2곳).")

    paras = split_paragraphs(body)
    must = []
    if kind == "food" and place and place.get("name"):
        name = place["name"].strip()
        must = [name.replace(" ", ""), name.split()[0]]
        region = region_of(place)
        if region:
            must.append(f"{region}맛집")  # 상호 + 지역 태그는 빠지면 코드가 넣음(설계서 §4.6)
    elif keywords:
        must = [keywords[0].replace(" ", "")]
    idx = find_hashtag_index(paras)
    if idx is None:
        notes.append("해시태그 문단이 없어 핵심 키워드로 만들었어요.")
        paras.append(normalize_hashtags("", must))
    else:
        paras[idx] = normalize_hashtags(paras[idx], must)
        n_tags = paras[idx].count("#")
        if n_tags < 28:
            notes.append(f"해시태그가 {n_tags}개예요(권장 28~30개).")
    body = "\n\n".join(paras)

    if kind == "food":
        body = insert_map_line(body, (place or {}).get("name", ""))
    return {"body": body, "chars": count_chars(body), "notes": notes}
