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
PHOTO_RE = re.compile(r"<\s*사진\s*(\d+)\s*>")
MAX_HASHTAGS = 10
MIN_HASHTAGS = 5
HASHTAG_RANGE = {"invest": (3, 5)}  # 글 종류별 (최소, 최대). 없으면 (MIN_HASHTAGS, MAX_HASHTAGS)
RATING_HEAD = "★ 별점 한눈에 보기"
ONE_LINER_RE = re.compile(r"^(한\s*줄\s*(평|정리)|오늘의\s*한\s*줄)\s*[:：]")
SOURCE_HEAD = "📰 참고한 기사"
SUMMARY_HEAD = "📌 이 글 핵심 3줄"  # 정보글 상단 요약(줄마다 ①②③, 문장 단위로 다시 나누지 않음)
# 문장 끝(. ? !) 뒤 공백. 닫는 태그·따옴표·괄호가 붙어 있어도 문장 끝으로 본다(lookbehind 는 갈래마다 길이가 고정이어야 해서 나눠 씀)
SENT_END_RE = re.compile(r"(?<=[.?!])\s+|(?<=[.?!][\"”’')\]])\s+|(?<=[.?!]\{\{/bold\}\})\s+|(?<=[.?!]\{\{/color\}\})\s+|(?<=[.?!]\{\{/highlight\}\})\s+")


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


_PHOTO_ONLY = re.compile(r"<사진(\d+)>")


def _is_text_paragraph(par: str) -> bool:
    return not (_PHOTO_ONLY.fullmatch(par) or HEADING_RE.match(strip_tags(par)) or MAP_LINE_MARK in par
                or (par.startswith("#") and par.count("#") >= 3))


def _insert_missing_photos(paras: list[str], missing: list[int]) -> list[str]:
    """AI가 빠뜨린 사진 번호를 번호 순서를 지키며 앞뒤 사진 사이 글 문단 뒤에 고르게 끼워 넣습니다."""
    tag_i = find_hashtag_index(paras)
    end = tag_i if tag_i is not None else len(paras)
    placed = {int(_PHOTO_ONLY.fullmatch(p).group(1)): i for i, p in enumerate(paras) if _PHOTO_ONLY.fullmatch(p)}
    # 같은 '앞 사진 ~ 뒤 사진' 구간에 들어갈 번호끼리 묶기
    gaps: dict[tuple[int, int], list[int]] = {}
    for n in missing:
        lo = max((i for k, i in placed.items() if k < n), default=-1)
        hi = min((i for k, i in placed.items() if k > n), default=end)
        if hi <= lo:  # AI가 번호 순서와 다르게 놓은 경우: 앞 사진 뒤 ~ 글 끝 사이를 씁니다
            hi = end
        gaps.setdefault((lo, hi), []).append(n)
    after: dict[int, list[int]] = {}  # 문단 인덱스 → 그 문단 뒤에 놓을 번호들
    for (lo, hi), nums in gaps.items():
        slots = [j for j in range(lo + 1, hi) if _is_text_paragraph(paras[j])]
        # 소제목 바로 앞 문단은 피하고(있다면), 없으면 전체 문단을 씁니다
        good = [j for j in slots if j + 1 >= len(paras) or not HEADING_RE.match(strip_tags(paras[j + 1]))] or slots
        if not good:
            good = [max(lo, 0)] if paras else [0]
        for i, n in enumerate(nums):
            j = good[min(len(good) - 1, (i + 1) * len(good) // (len(nums) + 1))]
            after.setdefault(j, []).append(n)
    out = []
    for i, par in enumerate(paras):
        out.append(par)
        out += [f"<사진{n}>" for n in sorted(after.get(i, []))]
    return out


def normalize_photos(text: str, photo_count: int) -> tuple[str, list[str]]:
    """<사진N> 자리를 정리합니다: 단독 줄로 분리, 없는 번호·중복 제거, 빠진 번호는 자동으로 끼워 넣고 알림."""
    notes = []
    out, seen = [], set()
    for par in split_paragraphs(text):
        found = [int(n) for n in PHOTO_RE.findall(par)]
        if not found:
            out.append(par)
            continue
        rest = re.sub(r"[ \t]{2,}", " ", PHOTO_RE.sub("", par)).strip()
        is_tags = rest.startswith("#") and rest.count("#") >= 3
        if rest and (HEADING_RE.match(strip_tags(rest)) or is_tags):
            found = []  # 소제목·해시태그 줄에 붙은 사진 자리는 버립니다
        if rest:
            out.append(rest)
        for n in found:
            if 1 <= n <= photo_count and n not in seen:
                seen.add(n)
                out.append(f"<사진{n}>")
    dropped = sum(len(PHOTO_RE.findall(p)) for p in split_paragraphs(text)) - len(seen)
    missing = [n for n in range(1, photo_count + 1) if n not in seen]
    if missing:
        out = _insert_missing_photos(out, missing)
        notes.append("AI가 빠뜨린 사진 " + ", ".join(map(str, missing)) + "번 자리를 번호 순서에 맞게 자동으로 넣었어요. 위치가 어색하면 에디터에서 옮기세요.")
    if dropped > 0:
        notes.append(f"잘못되었거나 겹치는 사진 자리 {dropped}개를 뺐어요.")
    return "\n\n".join(out), notes


def count_chars(text: str) -> int:
    """화면 카운터와 같은 기준: 태그 제거, 해시태그 문단 제외, 공백 제외. 사진 자리는 '사진N'(원본과 같은 방식)으로 셉니다."""
    paras = split_paragraphs(PHOTO_RE.sub(lambda m: f"사진{m.group(1)}", strip_tags(text)))
    idx = find_hashtag_index(paras)
    if idx is not None:
        paras.pop(idx)
    return len(re.sub(r"\s", "", "\n".join(paras)))


def region_of(place: dict | None) -> str:
    """주소에서 구 이름을 뽑습니다. (예: '서울 마포구 백범로' → '마포')"""
    m = re.search(r"([가-힣]{2,})구", (place or {}).get("address", ""))
    return m.group(1) if m else ""


def build_rating_block(ratings: list[dict]) -> str:
    """항목별 별점(1~5점)을 글 끝에 넣을 한 문단으로 만듭니다. 모양이 매번 같도록 코드가 직접 만듭니다."""
    lines = [RATING_HEAD]
    for r in ratings:
        n = max(1, min(5, int(r["score"])))
        lines.append(f"{r['label']} {'★' * n}{'☆' * (5 - n)} {n}/5")
    return "\n".join(lines)


def _put_rating_block(paras: list[str], ratings: list[dict]) -> tuple[list[str], list[str]]:
    """'한 줄 평' 문단 바로 앞(없으면 해시태그 앞)에 별점 블록을 넣습니다. 이미 있던 블록은 지우고 다시 만듭니다."""
    notes = []
    paras = [p for p in paras if not p.startswith(RATING_HEAD)]
    tag_i = find_hashtag_index(paras)
    end = tag_i if tag_i is not None else len(paras)
    one = next((i for i in range(end - 1, -1, -1) if ONE_LINER_RE.match(strip_tags(paras[i]))), None)
    if ratings:
        paras.insert(one if one is not None else end, build_rating_block(ratings))
    return paras, notes


def build_source_block(news: list[dict]) -> str:
    """참고 기사 목록(코드가 만듦): 언론사 「제목」 (날짜) 주소"""
    lines = [SOURCE_HEAD]
    for n in news:
        head = " ".join(x for x in [n.get("source", ""), f"「{n['title']}」" if n.get("title") else "", f"({n['published'][:10]})" if n.get("published") else ""] if x)
        lines.append(f"- {head or '기사'}" + (f" {n['url']}" if n.get("url") else ""))
    return "\n".join(lines)


def _put_source_block(paras: list[str], news: list[dict]) -> list[str]:
    """이미 있던 참고 기사 문단은 지우고, 기사가 있으면 해시태그 바로 앞에 다시 넣습니다."""
    paras = [p for p in paras if not strip_tags(p).startswith(SOURCE_HEAD)]
    if news:
        idx = find_hashtag_index(paras)
        paras.insert(idx if idx is not None else len(paras), build_source_block(news))
    return paras


def is_special_paragraph(par: str) -> bool:
    """소제목·해시태그·별점·참고 기사·사진·지도 줄처럼 문장 단위로 다루지 않는 문단"""
    plain = strip_tags(par).strip()
    return bool(HEADING_RE.match(plain) or plain.startswith(("#", RATING_HEAD, SOURCE_HEAD, SUMMARY_HEAD)) or PHOTO_RE.fullmatch(plain)
                or MAP_LINE_MARK in plain)


def split_sentences(par: str) -> list[str]:
    return [x.strip() for x in SENT_END_RE.split(par.replace("\n", " ")) if x.strip()]


def one_sentence_per_line(paras: list[str]) -> list[str]:
    """투자 생각 글: 문단 안에서 문장이 끝나면 줄을 바꿉니다(네이버에 붙이면 문장마다 엔터)."""
    return [p if is_special_paragraph(p) else "\n".join(split_sentences(p)) for p in paras]


def finalize(kind: str, raw: str, place: dict | None, keywords: list[str], title: str = "", photo_count: int = 0,
             ratings: list[dict] | None = None, news: list[dict] | None = None) -> dict:
    """원고를 정리해 {body, chars, notes} 를 돌려줍니다."""
    body, notes = clean_markdown(raw.replace("\r\n", "\n"), title)
    body = normalize_tags(body)
    body, photo_notes = normalize_photos(body, photo_count)
    notes += photo_notes
    body, hl = limit_highlights(body, 2)
    if hl > 2:
        notes.append(f"형광펜 {hl}곳 중 2곳만 남겼어요.")
    elif hl < 2:
        notes.append(f"형광펜이 {hl}곳이에요(권장 2곳).")

    paras = split_paragraphs(body)
    must = []
    if kind in ("food", "hotel") and place and place.get("name"):
        name = place["name"].strip()
        must = [name.replace(" ", ""), name.split()[0]]
        region = region_of(place)
        if region:
            must.append(f"{region}{'호텔' if kind == 'hotel' else '맛집'}")  # 상호 + 지역 태그는 빠지면 코드가 넣음(설계서 §4.6)
        must += [k.replace(" ", "") for k in keywords[:2]]
    elif keywords and kind != "invest":  # 투자 생각 글의 해시태그는 AI가 고른 핵심 키워드만
        must = [k.replace(" ", "") for k in keywords[:3]]
    tag_min, tag_max = HASHTAG_RANGE.get(kind, (MIN_HASHTAGS, MAX_HASHTAGS))
    idx = find_hashtag_index(paras)
    if idx is None:
        notes.append("해시태그 문단이 없어 핵심 키워드로 만들었어요.")
        paras.append(normalize_hashtags("", must, tag_max))
    else:
        paras[idx] = normalize_hashtags(paras[idx], must, tag_max)
        n_tags = paras[idx].count("#")
        if n_tags < tag_min:
            notes.append(f"해시태그가 {n_tags}개예요(권장 {tag_min}~{tag_max}개).")
    if kind in ("food", "hotel"):
        paras, rn = _put_rating_block(paras, ratings or [])
        notes += rn
        end = find_hashtag_index(paras)
        if not any(ONE_LINER_RE.match(strip_tags(p)) for p in paras[: end if end is not None else len(paras)]):
            notes.append("글 끝의 '한 줄 평'이 없어요. 직접 한 줄 평을 써 넣어 주세요.")
    paras = _put_source_block(paras, news or [])
    if kind == "invest":  # 투자 생각은 소제목 없이 쓰는 고정 문체: 남은 소제목 줄은 지움
        kept = [p for p in paras if not HEADING_RE.match(strip_tags(p))]
        if len(kept) < len(paras):
            notes.append(f"투자 생각 문체(소제목 없음)에 맞춰 소제목 {len(paras) - len(kept)}줄을 지웠어요.")
        paras = kept
    paras = one_sentence_per_line(paras)  # 모든 글: 문장마다 줄바꿈(모바일 가독성). 소제목·별점·요약 등은 그대로
    body = "\n\n".join(paras)

    if kind in ("food", "hotel"):
        body = insert_map_line(body, (place or {}).get("name", ""))
    return {"body": body, "chars": count_chars(body), "notes": notes}
