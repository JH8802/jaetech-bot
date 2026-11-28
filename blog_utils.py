import html
import json
import os
import re
import shutil
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser

from dotenv import load_dotenv

load_dotenv()

# 원고·문체 샘플·자동 저장을 둘 폴더. PC 두 대에서 같이 쓰려면 .env에
#   BLOG_DATA_DIR=C:\Users\이름\OneDrive\blog_data
# 처럼 클라우드 동기화 폴더를 지정하면 된다. 비워두면 프로그램 폴더를 그대로 씀.
DATA_DIR = os.path.expanduser(os.getenv("BLOG_DATA_DIR", "").strip().strip('"')) or "."
DRAFTS_DIR = os.path.join(DATA_DIR, "drafts")


def extract_text(message):
    """Claude 응답에서 실제 텍스트만 뽑아낸다.

    확장 사고(thinking)가 켜져 있으면 content[0]이 텍스트가 아닐 수 있어서,
    타입으로 찾아야 한다 (content[0]을 무조건 텍스트로 가정하면 안 됨).
    """
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


def create_text(client, **kwargs):
    """client.messages.create()를 호출하고 텍스트만 돌려준다 — 글이 비었거나
    중간에 끊기면(stop_reason == "max_tokens") 생각(thinking)을 줄여서 1번 재시도하고,
    그래도 안 되면 이유를 담아 RuntimeError를 낸다.

    Sonnet은 답을 쓰기 전에 '생각'에 토큰을 쓰는데, 입력이 길면 이게 max_tokens를
    다 써버려서 본문이 0자로 오는 경우가 있다. (예전엔 이걸 조용히 빈 글로 넘겼음)
    """
    message = client.messages.create(**kwargs)
    text = extract_text(message).strip()

    if message.stop_reason != "refusal" and (message.stop_reason == "max_tokens" or not text):
        retry = dict(kwargs)
        body = dict(retry.get("extra_body") or {})
        body["output_config"] = {"effort": "low"}  # 생각 최소화 (구버전 SDK도 받도록 extra_body로)
        retry["extra_body"] = body
        message = client.messages.create(**retry)
        text = extract_text(message).strip()

    if message.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 요청을 거절했어 (안전 필터). 주제나 입력 내용을 조금 바꿔서 다시 시도해봐.")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("글이 길이 제한에 걸려 중간에 끊겼어. 입력(사실/출처)을 조금 줄이거나 다시 눌러봐.")
    if not text:
        raise RuntimeError(f"Claude가 빈 응답을 돌려줬어 (stop_reason={message.stop_reason}). 다시 눌러봐.")
    return text


METADATA_TAGS = {
    "[제목]": "title",
    "[카테고리]": "category",
    "[메타설명]": "meta_description",
    "[주소]": "slug",
    "[태그]": "tags",
    "[제목 후보]": "title_candidates",  # 자료로 쓰기 모드 — 여러 줄이면 " / "로 이어 붙임
    "[초점 키프레이즈]": "focus_keyphrase",  # 워드프레스 Yoast SEO의 '초점 키프레이즈' 칸에 넣을 검색어
}


def parse_draft_metadata(draft):
    """draft_post()가 만든 텍스트에서 [제목]/[카테고리]/[메타설명]/[주소]/[태그]
    줄을 뽑아내고, 나머지는 본문으로 분리한다.

    반환: {"title": str, "category": str, "meta_description": str,
           "slug": str, "tags": str, "body": str}
    """
    meta = {key: "" for key in METADATA_TAGS.values()}
    body_lines = []

    for line in draft.split("\n"):
        stripped = line.strip()
        matched_key = next((k for tag, k in METADATA_TAGS.items() if stripped.startswith(tag)), None)
        if matched_key:
            tag = next(tag for tag, k in METADATA_TAGS.items() if k == matched_key)
            value = stripped[len(tag):].strip()
            if matched_key == "title_candidates" and meta[matched_key]:
                meta[matched_key] += " / " + value
            else:
                meta[matched_key] = value
        else:
            body_lines.append(line)

    meta["body"] = "\n".join(body_lines).strip()
    return meta


_WORD_CHAR = r"[0-9A-Za-z가-힣]"


def _keyphrase_pattern(keyphrase, exact=True):
    words = [re.escape(w) for w in (keyphrase or "").split()]
    if not words:
        return None
    tail = f"(?!{_WORD_CHAR})" if exact else ""
    return re.compile(f"(?<!{_WORD_CHAR})" + r"\s*".join(words) + tail, re.IGNORECASE)


def count_keyphrase(text, keyphrase, exact=True):
    """초점 키프레이즈가 몇 번 나오는지.
    exact=True: Yoast SEO처럼 글자 그대로 + 바로 뒤에 조사 없이 (띄어쓰기·문장부호가 오는 것)만 셈
                ('유산균 보장균수 기준' O, '유산균 보장균수는' X)
    exact=False: 조사가 붙은 것까지 셈"""
    pattern = _keyphrase_pattern(keyphrase, exact)
    return len(pattern.findall(text or "")) if pattern else 0


def keyphrase_target(body_chars):
    """본문 길이에 맞는 키프레이즈 권장 횟수 (최소, 최대) — 대략 800자당 1회, 최소 3회."""
    low = max(3, round(body_chars / 800))
    return low, low + 2


def prose_sentences(body):
    """본문에서 '글 문장'만 뽑는다 (표시 줄·표·목록·사진 제안 제외) — 문장 길이 점검용."""
    sentences, in_box = [], False
    for line in (body or "").split("\n"):
        s = line.strip()
        if s.startswith(("[표]", "[요약]", "[참고 자료]", "[저자 소개]")):
            in_box = True
        if in_box:
            if s.startswith(("[표 끝]", "[요약 끝]", "[참고 자료 끝]", "[저자 소개 끝]")):
                in_box = False
            continue
        if not s or (s.startswith("[") and not s.startswith("[[")) or "|" in visible_text(s) or re.match(r"^(?:[-•·]|\d{1,2}[.)]|Q\.|A\.)\s", s):
            continue
        sentences += [x for x in re.split(r"(?<=[.!?])\s+", visible_text(s)) if x.strip()]
    return sentences


LONG_SENTENCE_WORDS = 20      # Yoast 가독성 기준: 20단어(어절) 넘으면 긴 문장
LONG_SENTENCE_MAX_RATIO = 25  # 긴 문장이 전체의 25%를 넘으면 경고


def long_sentence_stats(body):
    """(긴 문장 목록, 전체 문장 수, 긴 문장 비율 %)"""
    sentences = prose_sentences(body)
    long_ones = [s for s in sentences if len(s.split()) > LONG_SENTENCE_WORDS]
    ratio = round(100 * len(long_ones) / len(sentences)) if sentences else 0
    return long_ones, len(sentences), ratio


def has_keyword(text, keyword):
    """띄어쓰기 차이는 무시하고, 키워드의 단어가 모두 들어 있으면 포함으로 본다
    (예: '유산균 보장균수' → '유산균의 보장균수'도 통과)."""
    flat = text.replace(" ", "").lower()
    return all(word.lower() in flat for word in keyword.split())


def _read_past_drafts(platform, drafts_dir=DRAFTS_DIR):
    """drafts/ 폴더에서 같은 플랫폼 초안을 최신순으로 읽어
    (파일명, 제목, 타깃 키워드)를 하나씩 돌려준다.
    다른 플랫폼 글은 다른 블로그라 비교/링크 대상이 아니므로 제외."""
    if not os.path.isdir(drafts_dir):
        return

    for name in sorted((f for f in os.listdir(drafts_dir) if f.endswith(".txt")), reverse=True):
        try:
            with open(os.path.join(drafts_dir, name), encoding="utf-8") as f:
                lines = [line.strip() for line in f]
        except (OSError, UnicodeDecodeError):
            continue

        header = lines[:4]
        if f"플랫폼: {platform}" not in header:
            continue
        title = next((l[len("[제목]"):].strip() for l in lines if l.startswith("[제목]")), "")
        keyword = next((l[len("타깃 키워드:"):].strip() for l in header if l.startswith("타깃 키워드:")), "")
        yield name, title, keyword


def load_past_titles(platform, drafts_dir=DRAFTS_DIR, limit=30):
    """같은 플랫폼 지난 초안의 [제목]만 최신순·중복 없이 (내부 링크 추천용)."""
    titles = []
    for _, title, _ in _read_past_drafts(platform, drafts_dir):
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def find_keyword_overlap(platform, keyword, exclude=(), drafts_dir=DRAFTS_DIR):
    """같은 플랫폼에 같은 타깃 키워드로 쓴 지난 글 제목들을 찾는다.
    같은 키워드 글이 여러 개면 내 글끼리 검색 순위를 나눠 먹음(키워드 잠식).
    지난 글의 타깃 키워드가 같거나, 키워드 기록이 없는 옛 초안이면 제목에
    키워드가 들어 있는지로 판단. exclude: 이번에 방금 저장한 파일 경로들."""
    if not keyword:
        return []

    excluded = {os.path.basename(f) for f in exclude}
    flat = keyword.replace(" ", "").lower()
    matches = []
    for name, title, past_keyword in _read_past_drafts(platform, drafts_dir):
        if name in excluded or not title:
            continue
        same = (past_keyword.replace(" ", "").lower() == flat) if past_keyword else has_keyword(title, keyword)
        if same and title not in matches:
            matches.append(title)
    return matches


VISUAL_TAGS = ("[사진 제안]", "[그래프 제안]", "[지도 제안]")

# 본문 안에서 '내가 채워야 하는 자리' — 줄 전체(내부링크/사진류)이거나 문장 안(출처/추가 필요)
PLACEHOLDER_RE = re.compile(
    r"^[ \t]*\[(?:내부링크 제안|사진 제안|그래프 제안|지도 제안)\][^\n]*$"
    r"|([.。!?])?[ \t]*\[출처 필요[^\]\n]*\]"
    r"|\[추가 필요[^\]\n]*\]"
    r"|\[검수[^\]\n]*\]",
    re.MULTILINE,
)
_INLINE_TAG_RE = re.compile(r"\[(?:출처 필요|추가 필요|검수)[^\]\n]*\]")
# 문장 속 링크: [[보이는 글자 | https://주소]]
INLINE_LINK_RE = re.compile(r"\[\[\s*([^\[\]|\n]+?)\s*\|\s*(https?://[^\s\[\]|]+)\s*\]\]")


def _split_cells(row):
    """표 한 줄을 | 로 나눈다 — 칸 안의 문장 속 링크 [[글자 | 주소]]의 | 는 나누지 않음."""
    links = []
    protected = INLINE_LINK_RE.sub(lambda m: links.append(m.group(0)) or f"\x00{len(links) - 1}\x00", row)
    return [re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], c).strip() for c in protected.split("|")]


def visible_text(text):
    """문장 속 링크 표시를 보이는 글자만 남긴다 (문장 길이·키프레이즈 셀 때)."""
    return INLINE_LINK_RE.sub(lambda m: m.group(1), text or "")


def _host(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_internal_url(url, site_url=None):
    """내 블로그 주소(사이드바 설정)와 같은 사이트면 True, 다르면 False, 내 주소를 안 적었으면 None."""
    site = (load_settings()["site_url"] if site_url is None else site_url).strip()
    if not site:
        return None
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    mine, other = _host(site), _host(url)
    return bool(mine) and (other == mine or other.endswith("." + mine))


def _link_tag(text, url, internal):
    """내부 링크는 같은 창, 외부 링크는 새 창(+noopener)."""
    extra = "" if internal else ' target="_blank" rel="noreferrer noopener"'
    return f'<a href="{html.escape(url)}"{extra}>{html.escape(text)}</a>'


def link_stats(body, site_url=None):
    """본문의 (내부 링크 수, 외부 링크 수) — [링크: …] 줄, 문장 속 [[…]], [버튼: …], [원문 카드]."""
    site = load_settings()["site_url"] if site_url is None else site_url
    internal = external = 0
    for line in (body or "").split("\n"):
        s = line.strip()
        urls = []
        m = _LINK_LINE_RE.match(s)
        if m:
            kind = is_internal_url(m.group(2), site)
            internal, external = (internal + 1, external) if kind in (True, None) else (internal, external + 1)
            continue
        if _CARD_RE.match(s):
            external += 1
            continue
        b = _BUTTON_LINE_RE.match(s)
        if b:
            urls.append(b.group(2))
        urls += [u for _, u in INLINE_LINK_RE.findall(s)]
        for u in urls:
            if is_internal_url(u, site):
                internal += 1
            else:
                external += 1
    return internal, external
_LINK_LINE_RE = re.compile(r"^\[링크:\s*(.*?)\s*\|\s*(https?://\S+)\s*\]$")
_BUTTON_LINE_RE = re.compile(r"^\[버튼:\s*(.+?)\s*\|\s*(https?://[^\s|\]]+)\s*((?:\|[^|\]]*)*)\]$")
_IMAGE_LINE_RE = re.compile(r"^\[이미지:\s*(https?://\S+)\s*\|\s*(.*?)\s*\]$")
_BULLET_RE = re.compile(r"^[-•·]\s+")
_CARD_RE = re.compile(r"^\[원문 카드\s*[:：]\s*(?:자료|출처)?\s*(\d+)\s*\]$")
_NUMBERED_RE = re.compile(r"^\d{1,2}[.)]\s+")
NOTICE_PREFIXES = VISUAL_TAGS + ("[내부링크 제안]", "[추가 필요", "[검수")
SUMMARY_TITLE = "한눈에 보기"
TOC_TITLE = "목차"


def _anchors(blocks):
    """[목차]가 있을 때만 소제목마다 이동용 id(sec-1, sec-2 …)를 붙인다. 반환: {블록 순번: id}"""
    if not any(kind == "toc" for kind, _ in blocks):
        return {}
    ids, n = {}, 0
    for idx, (kind, _) in enumerate(blocks):
        if kind == "h2":
            n += 1
            ids[idx] = f"sec-{n}"
    return ids
REFS_TITLE = "참고 자료"
AUTHOR_TITLE = "글쓴이"


def _ref_item(item):
    """'이름 | 주소' → 링크, '이름'만 있으면 글자만."""
    name, _, url = item.partition(" | ")
    url = url.strip()
    if re.match(r"https?://\S+$", url):
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(name.strip())}</a>'
    return html.escape(item.strip())


def parse_body_blocks(body):
    """본문(태그 포함 일반 텍스트)을 블록 목록으로 해석한다 — HTML/워드프레스 블록 출력 공용.

    본문 표기법:
      [소제목] 제목                → ("h2", 제목)
      [요약] … [요약 끝]            → ("summary", [줄...])   한눈에 보기 박스
      [표] 표 제목(선택)
      항목 | 값 | 비고 (첫 줄 = 머리글)
      … [표 끝]                     → ("table", {"caption", "rows"})
      - 항목 / 1. 항목 (연속된 줄)   → ("ul"|"ol", [항목...])
      [링크: 제목 | 주소]           → ("link", (제목, 주소))
      [버튼: 문구 | 주소 | 옵션…]   → ("button", (문구, 주소, 옵션 dict))   CTA 버튼
                                       옵션(선택, 순서 무관): 색(파랑·초록·주황·빨강·검정), 왼쪽, 같은 창, 제휴
      [이미지: 주소 | ALT]          → ("image", (주소, ALT))
      [사진 제안]·[내부링크 제안]·[추가 필요]·[검수] 줄 → ("notice", 줄)
      그 외 연속된 줄               → ("p", [줄...])
    """
    blocks, para = [], []
    lines = body.split("\n")
    i = 0

    def flush():
        if para:
            blocks.append(("p", list(para)))
            para.clear()

    while i < len(lines):
        s = lines[i].strip()
        if not s:
            flush()
        elif s.startswith("[요약]"):
            flush()
            items = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("[요약 끝]"):
                if lines[i].strip():
                    items.append(_BULLET_RE.sub("", lines[i].strip()))
                i += 1
            blocks.append(("summary", items))
        elif s.startswith("[목차]"):
            flush()
            blocks.append(("toc", None))
        elif _CARD_RE.match(s):
            flush()
            blocks.append(("card", int(_CARD_RE.match(s).group(1))))
        elif s.startswith(("[참고 자료]", "[저자 소개]")):
            flush()
            kind = "refs" if s.startswith("[참고 자료]") else "author"
            end = "[참고 자료 끝]" if kind == "refs" else "[저자 소개 끝]"
            items = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(end):
                if lines[i].strip():
                    items.append(_BULLET_RE.sub("", lines[i].strip()))
                i += 1
            blocks.append((kind, items))
        elif s.startswith("[표]"):
            flush()
            caption = s[s.index("]") + 1:].strip() if "]" in s else ""
            rows = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("[표 끝]"):
                row = lines[i].strip().strip("|")
                if row and not re.fullmatch(r"[\s|:\-]+", row):  # 마크다운식 구분선(---|---)은 건너뜀
                    rows.append(_split_cells(row))
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                blocks.append(("table", {"caption": caption, "rows": rows}))
        elif s.startswith("[소제목]"):
            flush()
            blocks.append(("h2", s[len("[소제목]"):].strip()))
        elif _LINK_LINE_RE.match(s):
            flush()
            blocks.append(("link", _LINK_LINE_RE.match(s).groups()))
        elif _BUTTON_LINE_RE.match(s):
            flush()
            text, url, opts = _BUTTON_LINE_RE.match(s).groups()
            blocks.append(("button", (text, url, parse_button_options(opts))))
        elif _IMAGE_LINE_RE.match(s):
            flush()
            blocks.append(("image", _IMAGE_LINE_RE.match(s).groups()))
        elif s.startswith(NOTICE_PREFIXES):
            flush()
            blocks.append(("notice", s))
        elif _BULLET_RE.match(s) or _NUMBERED_RE.match(s):
            flush()
            kind = "ul" if _BULLET_RE.match(s) else "ol"
            pattern = _BULLET_RE if kind == "ul" else _NUMBERED_RE
            items = []
            while i < len(lines) and pattern.match(lines[i].strip()):
                items.append(pattern.sub("", lines[i].strip()))
                i += 1
            blocks.append((kind, items))
            continue
        else:
            para.append(s)
        i += 1
    flush()
    return blocks


def _inline(text):
    """문단 안 글자: HTML 이스케이프 + 문장 속 링크 [[글자 | 주소]] + 아직 안 채운 [출처 필요]/[추가 필요]/[검수] 형광펜."""
    out, last = [], 0
    for m in INLINE_LINK_RE.finditer(text):
        out.append(_INLINE_TAG_RE.sub(lambda t: f"<mark>{t.group(0)}</mark>", html.escape(text[last:m.start()])))
        out.append(_link_tag(m.group(1), m.group(2), is_internal_url(m.group(2))))
        last = m.end()
    out.append(_INLINE_TAG_RE.sub(lambda t: f"<mark>{t.group(0)}</mark>", html.escape(text[last:])))
    return "".join(out)


def _link_line(title, url):
    """[링크: 제목 | 주소] 줄 — 내 블로그 글이면 '함께 보면 좋은 글', 다른 사이트면 '참고'(새 창)."""
    if is_internal_url(url) is False:
        return f"📎 참고: {_link_tag(title, url, False)}"
    return f"👉 함께 보면 좋은 글: {_link_tag(title, url, True)}"


def _table_html(data):
    head, *rest = data["rows"]
    thead = "<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead>"
    tbody = "<tbody>" + "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rest
    ) + "</tbody>"
    return f"<table>{thead}{tbody}</table>"


def _card_html(card):
    url = html.escape(card["url"])
    meta = " · ".join(x for x in (card.get("site"), card.get("date")) if x)
    desc = f'<p style="margin:0 0 10px;color:#555;font-size:14px;">{html.escape(card["desc"])}</p>' if card.get("desc") else ""
    return (
        '<div style="border:1px solid #e3e6ea;border-radius:10px;padding:14px 18px;margin:18px 0;background:#f8f9fb;">'
        f'<p style="margin:0 0 4px;color:#888;font-size:13px;">📰 {html.escape(meta)}</p>'
        f'<p style="margin:0 0 6px;font-weight:bold;"><a href="{url}" target="_blank" rel="noopener" '
        f'style="color:inherit;text-decoration:none;">{html.escape(card["title"])}</a></p>{desc}'
        f'<p style="margin:0;"><a href="{url}" target="_blank" rel="noopener" '
        'style="display:inline-block;padding:6px 14px;border-radius:6px;background:#2f6fde;color:#fff;'
        'text-decoration:none;font-size:14px;">원문 보기 →</a></p></div>'
    )


def _card_gutenberg(card):
    url = html.escape(card["url"])
    meta = " · ".join(x for x in (card.get("site"), card.get("date")) if x)
    parts = [
        _wp("paragraph", f"<p>📰 {html.escape(meta)}</p>"),
        _wp("paragraph", f'<p><strong><a href="{url}" target="_blank" rel="noreferrer noopener">'
                         f'{html.escape(card["title"])}</a></strong></p>'),
    ]
    if card.get("desc"):
        parts.append(_wp("paragraph", f"<p>{html.escape(card['desc'])}</p>"))
    parts.append(_wp("buttons", '<div class="wp-block-buttons">' + _wp(
        "button", f'<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="{url}" '
                  'target="_blank" rel="noreferrer noopener">원문 보기 →</a></div>') + "</div>"))
    return _wp(
        "group",
        '<div class="wp-block-group has-background" style="background-color:#f8f9fb;'
        'padding-top:16px;padding-right:20px;padding-bottom:16px;padding-left:20px">'
        + "\n\n".join(parts) + "</div>",
        '{"style":{"color":{"background":"#f8f9fb"},"spacing":{"padding":{"top":"16px",'
        '"bottom":"16px","left":"20px","right":"20px"}}},"layout":{"type":"constrained"}}',
    )


# ─────────────────────────────────────────────
# CTA 버튼 (원고 없이도 링크만으로 만들 수 있음)
# ─────────────────────────────────────────────
CTA_COLORS = {"파랑": "#2f6fde", "초록": "#1f9d55", "주황": "#f07c1d", "빨강": "#e03131", "검정": "#222222"}
CTA_SPONSORED_NOTE = "※ 이 링크는 제휴 링크로, 이 링크를 통해 구매하면 글쓴이가 일정 수수료를 받을 수 있습니다."


BUTTON_OPTION_WORDS = ("왼쪽", "가운데", "같은 창", "새 창", "제휴")


def parse_button_options(text):
    """'| 초록 | 왼쪽 | 제휴' 같은 버튼 옵션 → cta_html/cta_gutenberg 인자. 모르는 말은 무시."""
    args = {}
    for word in (w.strip() for w in (text or "").split("|")):
        if word in CTA_COLORS:
            args["color"] = CTA_COLORS[word]
        elif word == "왼쪽":
            args["center"] = False
        elif word == "같은 창":
            args["new_tab"] = False
        elif word == "제휴":
            args["sponsored"] = True
            args["note"] = CTA_SPONSORED_NOTE
    return args


def button_line_problems(body):
    """본문의 [버튼: …] 줄에서 잘못 쓴 곳을 찾는다 (형식 오류·모르는 옵션)."""
    problems = []
    for line in (body or "").split("\n"):
        s = line.strip()
        if not s.startswith("[버튼"):
            continue
        m = _BUTTON_LINE_RE.match(s)
        if not m:
            problems.append(f"버튼 줄 형식이 틀려서 버튼이 안 만들어짐: '{s[:60]}' — [버튼: 문구 | https://주소] 형식으로")
            continue
        unknown = [w.strip() for w in m.group(3).split("|")
                   if w.strip() and w.strip() not in CTA_COLORS and w.strip() not in BUTTON_OPTION_WORDS]
        if unknown:
            problems.append(f"버튼 옵션 {', '.join(repr(w) for w in unknown)}는 모르는 말이라 무시됨 — 쓸 수 있는 옵션: "
                            f"{'·'.join(CTA_COLORS)} / 왼쪽 / 같은 창 / 제휴")
    return problems


def button_markup(url, text, color_name="파랑", center=True, sponsored=False, new_tab=True):
    """본문 칸에 넣을 버튼 한 줄 — 기본값(파랑·가운데·새 창)이 아닌 옵션만 붙인다."""
    opts = ([color_name] if color_name != "파랑" else []) + ([] if center else ["왼쪽"]) \
        + ([] if new_tab else ["같은 창"]) + (["제휴"] if sponsored else [])
    return f"[버튼: {text} | {url}" + "".join(f" | {o}" for o in opts) + "]"


def _cta_rel(sponsored, new_tab):
    rel = ["sponsored", "nofollow"] if sponsored else []
    if new_tab:
        rel.append("noopener")
    return " ".join(rel)


def cta_html(url, text, lead="", color=CTA_COLORS["파랑"], center=True, sponsored=False, new_tab=True, note=""):
    """티스토리 HTML 모드 등 일반 HTML용 CTA 버튼."""
    align = "center" if center else "left"
    target = ' target="_blank"' if new_tab else ""
    rel = _cta_rel(sponsored, new_tab)
    rel = f' rel="{rel}"' if rel else ""
    parts = ['<div style="text-align:%s;margin:28px 0;">' % align]
    if lead:
        parts.append(f'<p style="margin:0 0 12px;">{html.escape(lead)}</p>')
    parts.append(f'<a href="{html.escape(url)}"{target}{rel} style="display:inline-block;padding:12px 28px;'
                 f'border-radius:8px;background:{color};color:#ffffff;text-decoration:none;font-weight:bold;'
                 f'font-size:17px;">{html.escape(text)}</a>')
    if note:
        parts.append(f'<p style="margin:10px 0 0;color:#888;font-size:13px;">{html.escape(note)}</p>')
    parts.append("</div>")
    return safe_tilde("".join(parts))


def cta_gutenberg(url, text, lead="", color=CTA_COLORS["파랑"], center=True, sponsored=False, new_tab=True, note=""):
    """워드프레스 블록 에디터(코드 편집기)용 CTA 버튼 — 워드프레스가 직접 만드는 형식 그대로 (블록 오류 없음)."""
    out = []
    p_attr = ' {"align":"center"}' if center else ""
    p_cls = ' class="has-text-align-center"' if center else ""
    if lead:
        out.append(f"<!-- wp:paragraph{p_attr} -->\n<p{p_cls}>{html.escape(lead)}</p>\n<!-- /wp:paragraph -->")
    style = ('{"style":{"color":{"background":"%s","text":"#ffffff"},"border":{"radius":"8px"},'
             '"typography":{"fontSize":"17px"},"spacing":{"padding":{"top":"12px","bottom":"12px",'
             '"left":"28px","right":"28px"}}}}' % color)
    target = ' target="_blank"' if new_tab else ""
    rel = _cta_rel(sponsored, new_tab)
    rel = f' rel="{rel}"' if rel else ""
    link = (f'<a class="wp-block-button__link has-text-color has-background has-custom-font-size wp-element-button" '
            f'href="{html.escape(url)}" style="border-radius:8px;color:#ffffff;background-color:{color};padding-top:12px;'
            f'padding-right:28px;padding-bottom:12px;padding-left:28px;font-size:17px"{target}{rel}>{html.escape(text)}</a>')
    layout = ' {"layout":{"type":"flex","justifyContent":"center"}}' if center else ""
    out.append(f"<!-- wp:buttons{layout} -->\n<div class=\"wp-block-buttons\"><!-- wp:button {style} -->\n"
               f"<div class=\"wp-block-button\">{link}</div>\n<!-- /wp:button --></div>\n<!-- /wp:buttons -->")
    if note:
        n_attr = ' {"align":"center","fontSize":"small"}' if center else ' {"fontSize":"small"}'
        n_cls = "has-text-align-center has-small-font-size" if center else "has-small-font-size"
        out.append(f'<!-- wp:paragraph{n_attr} -->\n<p class="{n_cls}">{html.escape(note)}</p>\n<!-- /wp:paragraph -->')
    return safe_tilde("\n\n".join(out))


TILDE_SAFE = "∼"  # U+223C 물결표 — 보기엔 ~ 와 같지만 에디터가 취소선 기호로 읽지 않음


def safe_tilde(html_text):
    """HTML의 글자 부분에서 ~ 를 ∼ 로 바꾼다 (태그 안의 주소·속성은 그대로).
    티스토리·워드프레스 에디터와 마크다운은 ~ 두 개 사이 글자를 취소선으로 바꿔서,
    '3~5회 … 1~2개'처럼 범위 표현이 한 문단에 두 번 나오면 그 사이 문장에 줄이 그어진다."""
    parts = re.split(r"(<[^>]*>)", html_text or "")
    return "".join(p if p.startswith("<") else p.replace("~", TILDE_SAFE) for p in parts)


_URL_TOKEN = re.compile(r"https?://\S+")


def safe_tilde_text(text):
    """원고 글자의 ~ 를 ∼ 로 바꾼다 (링크 주소 안의 ~ 는 그대로).
    본문 칸 글자를 복사해 워드프레스 일반 편집기에 붙여넣으면, 워드프레스가 마크다운으로 읽어
    '70~99 … 1~2번'의 ~ 두 개 사이를 취소선(<del>)으로 바꾸기 때문 (실제 변환 코드로 확인)."""
    if not text or "~" not in text:
        return text
    out, last = [], 0
    for m in _URL_TOKEN.finditer(text):
        out.append(text[last:m.start()].replace("~", TILDE_SAFE))
        out.append(m.group(0))
        last = m.end()
    out.append(text[last:].replace("~", TILDE_SAFE))
    return "".join(out)


def body_to_html(body, cards=None):
    """티스토리 HTML 모드에 붙여넣을 일반 HTML.
    소제목 → <h2>, 요약 박스·표·목록·원문 카드 포함. 아직 안 채운 항목은 노란 표시로 남김.
    cards: source_cards() 결과 — [원문 카드: N] 자리에 넣을 원문 정보"""
    cards = cards or {}
    out = []
    blocks = parse_body_blocks(body)
    anchors = _anchors(blocks)
    for idx, (kind, data) in enumerate(blocks):
        if kind == "card":
            if data in cards:
                out.append(_card_html(cards[data]))
            continue
        if kind == "toc":
            items = "".join(f'<li><a href="#{anchors[i]}">{html.escape(d)}</a></li>'
                            for i, (k, d) in enumerate(blocks) if k == "h2")
            out.append('<div style="background:#f8f9fb;padding:14px 20px;border-radius:8px;">'
                       f"<p><strong>{TOC_TITLE}</strong></p><ol>{items}</ol></div>")
            continue
        if kind == "h2" and idx in anchors:
            out.append(f'<h2 id="{anchors[idx]}">{html.escape(data)}</h2>')
            continue
        if kind == "p":
            out.append("<p>" + "<br>\n".join(_inline(x) for x in data) + "</p>")
        elif kind == "h2":
            out.append(f"<h2>{html.escape(data)}</h2>")
        elif kind in ("ul", "ol"):
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(x)}</li>" for x in data) + f"</{kind}>")
        elif kind == "table":
            cap = f"<p><strong>{html.escape(data['caption'])}</strong></p>\n" if data["caption"] else ""
            out.append(cap + _table_html(data))
        elif kind == "summary":
            out.append(
                '<div style="background:#f3f6fa;padding:16px 20px;border-radius:8px;">'
                f"<p><strong>{SUMMARY_TITLE}</strong></p><ul>"
                + "".join(f"<li>{_inline(x)}</li>" for x in data) + "</ul></div>"
            )
        elif kind == "link":
            title, url = data
            out.append(f"<p>{_link_line(title, url)}</p>")
        elif kind == "button":
            out.append(cta_html(data[1], data[0], **data[2]))
        elif kind == "image":
            url, alt = data
            out.append(f'<p><img src="{html.escape(url)}" alt="{html.escape(alt)}"></p>')
        elif kind == "refs":
            out.append(f"<h2>{REFS_TITLE}</h2>\n<ul>" + "".join(f"<li>{_ref_item(x)}</li>" for x in data) + "</ul>")
        elif kind == "author":
            out.append(
                '<div style="background:#f5f5f5;padding:16px 20px;border-radius:8px;">'
                f"<p><strong>{AUTHOR_TITLE}</strong></p>"
                + "".join(f"<p>{_inline(x)}</p>" for x in data) + "</div>"
            )
        elif kind == "notice":
            out.append(f'<p style="background:#fff3cd;padding:8px;">📌 {html.escape(data)}</p>')
    return safe_tilde("\n\n".join(out))


def _wp(name, inner, attrs=""):
    attrs = f" {attrs}" if attrs else ""
    return f"<!-- wp:{name}{attrs} -->\n{inner}\n<!-- /wp:{name} -->"


def _wp_list(kind, items):
    tag = "ul" if kind == "ul" else "ol"
    attrs = "" if kind == "ul" else '{"ordered":true}'
    lis = "\n\n".join(_wp("list-item", f"<li>{_inline(x)}</li>") for x in items)
    return _wp("list", f'<{tag} class="wp-block-list">{lis}</{tag}>', attrs)


def body_to_gutenberg(body, cards=None):
    """워드프레스 블록 에디터(구텐베르크)의 '코드 편집기'에 붙여넣을 블록 HTML.
    소제목·문단·목록·표·요약 박스·원문 카드가 각각 블록으로 바로 만들어진다.
    (워드프레스 공식 블록 라이브러리로 '정상 블록'으로 인식되는 형식인지 검증한 형식)"""
    cards = cards or {}
    out = []
    blocks = parse_body_blocks(body)
    anchors = _anchors(blocks)
    for idx, (kind, data) in enumerate(blocks):
        if kind == "card":
            if data in cards:
                out.append(_card_gutenberg(cards[data]))
            continue
        if kind == "toc":
            lis = "\n\n".join(_wp("list-item", f'<li><a href="#{anchors[i]}">{html.escape(d)}</a></li>')
                               for i, (k, d) in enumerate(blocks) if k == "h2")
            inner = (_wp("paragraph", f"<p><strong>{TOC_TITLE}</strong></p>") + "\n\n"
                     + _wp("list", f'<ol class="wp-block-list">{lis}</ol>', '{"ordered":true}'))
            out.append(_wp(
                "group",
                '<div class="wp-block-group has-background" style="background-color:#f8f9fb;'
                'padding-top:16px;padding-right:20px;padding-bottom:16px;padding-left:20px">'
                f"{inner}</div>",
                '{"style":{"color":{"background":"#f8f9fb"},"spacing":{"padding":{"top":"16px",'
                '"bottom":"16px","left":"20px","right":"20px"}}},"layout":{"type":"constrained"}}',
            ))
            continue
        if kind == "h2" and idx in anchors:
            out.append(_wp("heading", f'<h2 class="wp-block-heading" id="{anchors[idx]}">{html.escape(data)}</h2>'))
            continue
        if kind == "p":
            out.append(_wp("paragraph", "<p>" + "<br>".join(_inline(x) for x in data) + "</p>"))
        elif kind == "h2":
            out.append(_wp("heading", f'<h2 class="wp-block-heading">{html.escape(data)}</h2>'))
        elif kind in ("ul", "ol"):
            out.append(_wp_list(kind, data))
        elif kind == "table":
            if data["caption"]:
                out.append(_wp("paragraph", f"<p><strong>{html.escape(data['caption'])}</strong></p>"))
            out.append(_wp("table", f'<figure class="wp-block-table">{_table_html(data)}</figure>',
                           '{"hasFixedLayout":false}'))
        elif kind == "summary":
            inner = (_wp("paragraph", f"<p><strong>{SUMMARY_TITLE}</strong></p>") + "\n\n"
                     + _wp_list("ul", data))
            out.append(_wp(
                "group",
                '<div class="wp-block-group has-background" style="background-color:#f3f6fa;'
                'padding-top:20px;padding-right:20px;padding-bottom:20px;padding-left:20px">'
                f"{inner}</div>",
                '{"style":{"color":{"background":"#f3f6fa"},"spacing":{"padding":{"top":"20px",'
                '"bottom":"20px","left":"20px","right":"20px"}}},"layout":{"type":"constrained"}}',
            ))
        elif kind == "link":
            title, url = data
            out.append(_wp("paragraph", f"<p>{_link_line(title, url)}</p>"))
        elif kind == "button":
            out.append(cta_gutenberg(data[1], data[0], **data[2]))
        elif kind == "refs":
            out.append(_wp("heading", f'<h2 class="wp-block-heading">{REFS_TITLE}</h2>'))
            lis = "\n\n".join(_wp("list-item", f"<li>{_ref_item(x)}</li>") for x in data)
            out.append(_wp("list", f'<ul class="wp-block-list">{lis}</ul>'))
        elif kind == "author":
            inner = "\n\n".join(
                [_wp("paragraph", f"<p><strong>{AUTHOR_TITLE}</strong></p>")]
                + [_wp("paragraph", f"<p>{_inline(x)}</p>") for x in data]
            )
            out.append(_wp(
                "group",
                '<div class="wp-block-group has-background" style="background-color:#f5f5f5;'
                'padding-top:20px;padding-right:20px;padding-bottom:20px;padding-left:20px">'
                f"{inner}</div>",
                '{"style":{"color":{"background":"#f5f5f5"},"spacing":{"padding":{"top":"20px",'
                '"bottom":"20px","left":"20px","right":"20px"}}},"layout":{"type":"constrained"}}',
            ))
        elif kind == "image":
            url, alt = data
            out.append(_wp("image",
                           f'<figure class="wp-block-image"><img src="{html.escape(url)}" alt="{html.escape(alt)}"/></figure>'))
        elif kind == "notice":
            out.append(_wp("paragraph",
                           f'<p class="has-background" style="background-color:#fff3cd">📌 {html.escape(data)}</p>',
                           '{"style":{"color":{"background":"#fff3cd"}}}'))
    return safe_tilde("\n\n".join(out))


# ─────────────────────────────────────────────
# 남은 항목 채우기: [출처 필요]/[추가 필요]/[내부링크 제안]/[사진 제안] 등을
# 화면에서 직접 입력해 본문에 반영
# ─────────────────────────────────────────────
def find_placeholders(body):
    """본문에서 채워야 할 자리를 순서대로 찾는다.
    반환: [{"kind": source|add|link|visual, "label": 화면 표시용, "hint": 무엇이 필요한지,
            "context": 주변 문장, "alt": 사진 ALT(사진류만)}]"""
    items = []
    for m in PLACEHOLDER_RE.finditer(body):
        raw = m.group(0).strip()
        start = m.start()
        before = body[max(0, start - 120):start].replace("\n", " ").strip()
        before = re.sub(r"\[[^\]]*\]", " ", before).strip()
        context = re.split(r"(?<=[.!?])\s+", before)[-1] if before else ""

        if raw.startswith("[내부링크 제안]"):
            title = raw[len("[내부링크 제안]"):].strip()
            items.append({"kind": "link", "label": "🔗 내부링크", "hint": title, "context": "", "alt": ""})
        elif raw.startswith(VISUAL_TAGS):
            tag = raw[:raw.index("]") + 1]
            alt_m = re.search(r'ALT:\s*"([^"]*)"', raw)
            items.append({"kind": "visual", "label": f"🖼️ {tag[1:-1]}", "hint": raw[len(tag):].strip(),
                          "context": "", "alt": alt_m.group(1) if alt_m else ""})
        elif raw.startswith("[검수"):
            hint = re.search(r"\[검수\s*[:：]?\s*([^\]]*)\]", raw)
            items.append({"kind": "review", "label": "🔎 검수 표시", "hint": hint.group(1).strip() if hint else "",
                          "context": context, "alt": ""})
        elif "[출처 필요" in raw:
            hint = re.search(r"\[출처 필요\s*[:：]?\s*([^\]]*)\]", raw)
            items.append({"kind": "source", "label": "📚 출처 필요", "hint": hint.group(1).strip() if hint else "",
                          "context": context, "alt": ""})
        else:
            hint = re.search(r"\[추가 필요\s*[:：]?\s*([^\]]*)\]", raw)
            items.append({"kind": "add", "label": "➕ 추가 필요", "hint": hint.group(1).strip() if hint else "",
                          "context": context, "alt": ""})
    return items


def apply_placeholders(body, fills):
    """find_placeholders() 순서대로 fills[i] = {"text": 입력값, "delete": bool}를 반영한다.
    - 입력값이 없고 삭제도 아니면 그 자리는 그대로 남긴다.
    - 출처: 입력이 '('로 시작하면 문장 끝 마침표 앞에 붙이고(예: '…있다 (Cell, 2016).'),
      아니면 그 문장 뒤에 새 문장으로 붙인다.
    - 내부링크: 주소(URL)를 넣으면 [링크: 제목 | 주소]로 바뀌어 HTML에서 링크가 된다.
    - 사진류: 이미지 주소(URL)를 넣으면 [이미지: 주소 | ALT]로 바뀌어 HTML에서 이미지가 된다.
    반환: (새 본문, 사용자가 입력한 텍스트 목록)"""
    items = find_placeholders(body)
    counter = {"i": 0}
    added_texts = []

    def repl(m):
        i = counter["i"]
        counter["i"] += 1
        item = items[i] if i < len(items) else None
        fill = fills.get(i, {}) if item else {}
        text = (fill.get("text") or "").strip()
        raw = m.group(0)
        punct = m.group(1) or ""

        if not item or (not text and not fill.get("delete")):
            return raw
        if fill.get("delete"):
            return punct
        added_texts.append(text)

        if item["kind"] == "source":
            if text.startswith("("):
                return f" {text}{punct}" if punct else f" {text}"
            return f"{punct} {text}" if punct else f" {text}"
        if item["kind"] in ("add", "review"):
            return text
        if item["kind"] == "link":
            if not re.match(r"https?://", text):
                return raw
            return f"[링크: {item['hint']} | {text}]"
        if item["kind"] == "visual":
            if not re.match(r"https?://", text):
                return raw
            return f"[이미지: {text} | {item['alt'] or item['hint'][:60]}]"
        return raw

    new_body = PLACEHOLDER_RE.sub(repl, body)
    new_body = re.sub(r"[ \t]{2,}", " ", new_body)
    new_body = re.sub(r"\n{3,}", "\n\n", new_body).strip()
    return new_body, added_texts


def compose_draft(meta):
    """parse_draft_metadata() 형태의 dict를 다시 원고 텍스트로 합친다 (화면에서 고친 내용 저장용)."""
    return "\n".join([
        f"[제목] {meta.get('title', '')}",
        *[f"[제목 후보] {t.strip()}" for t in meta.get("title_candidates", "").split(" / ") if t.strip()],
        f"[카테고리] {meta.get('category', '')}",
        f"[메타설명] {meta.get('meta_description', '')}",
        f"[주소] {meta.get('slug', '')}",
        *([f"[초점 키프레이즈] {meta['focus_keyphrase'].strip()}"] if (meta.get("focus_keyphrase") or "").strip() else []),
        "",
        meta.get("body", "").strip(),
        "",
        f"[태그] {meta.get('tags', '')}",
    ])


# ─────────────────────────────────────────────
# 원고 파일 저장/불러오기 (drafts/ 폴더)
# ─────────────────────────────────────────────
def write_draft_file(path, topic, platform, keyword, draft, inputs=None, backup=False):
    """원고를 .txt로 저장하고, 입력값(사실·출처·의견·메모)은 같은 이름의 .json에 함께 저장한다.
    backup=True면 덮어쓰기 전 이전 버전을 drafts/history/에 남긴다."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    if backup and os.path.exists(path):
        os.makedirs(os.path.join(folder, "history"), exist_ok=True)
        stem = os.path.basename(path)[:-len(".txt")]
        shutil.copy(path, os.path.join(folder, "history", f"{stem}_이전_{datetime.now():%H%M%S}.txt"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"주제: {topic}\n플랫폼: {platform}\n타깃 키워드: {keyword}\n\n{safe_tilde_text(draft)}")
    if inputs is not None:
        with open(path[:-len(".txt")] + ".json", "w", encoding="utf-8") as f:
            json.dump(inputs, f, ensure_ascii=False, indent=2)


def read_draft_file(path):
    """write_draft_file()로 저장한 원고를 읽는다.
    반환: {"topic", "platform", "keyword", "draft", "inputs"}"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    header, _, draft = text.partition("\n\n")
    info = {"topic": "", "platform": "", "keyword": ""}
    for line in header.split("\n"):
        for label, key in (("주제:", "topic"), ("플랫폼:", "platform"), ("타깃 키워드:", "keyword")):
            if line.startswith(label):
                info[key] = line[len(label):].strip()
    inputs = {}
    sidecar = path[:-len(".txt")] + ".json"
    if os.path.exists(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                inputs = json.load(f)
        except (OSError, ValueError):
            inputs = {}
    return {**info, "draft": draft.strip(), "inputs": inputs}


def list_saved_drafts(drafts_dir=DRAFTS_DIR, limit=100):
    """저장된 원고 목록 (최신순). 반환: [{"path", "label"}]"""
    if not os.path.isdir(drafts_dir):
        return []
    result = []
    for name in sorted((f for f in os.listdir(drafts_dir) if f.endswith(".txt")), reverse=True):
        path = os.path.join(drafts_dir, name)
        try:
            info = read_draft_file(path)
        except (OSError, UnicodeDecodeError):
            continue
        title = parse_draft_metadata(info["draft"]).get("title") or info["topic"] or "(제목 없음)"
        m = re.match(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})", name)
        when = f"{m.group(2)}/{m.group(3)} {m.group(4)}:{m.group(5)}" if m else ""
        result.append({"path": path, "label": f"{when} · {info['platform'] or '?'} · {title}"})
        if len(result) >= limit:
            break
    return result


# ─────────────────────────────────────────────
# 내 문체 샘플 / 입력 자동 저장
# ─────────────────────────────────────────────
STYLE_SAMPLE_PATH = os.path.join(DATA_DIR, "my_style.txt")
STYLE_SAMPLE_MAX = 3000
AUTOSAVE_PATH = os.path.join(DRAFTS_DIR, "_autosave.json")


def load_style_sample():
    try:
        with open(STYLE_SAMPLE_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_style_sample(text):
    with open(STYLE_SAMPLE_PATH, "w", encoding="utf-8") as f:
        f.write((text or "").strip()[:STYLE_SAMPLE_MAX])


def load_autosave():
    try:
        with open(AUTOSAVE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_autosave(data):
    os.makedirs(os.path.dirname(AUTOSAVE_PATH), exist_ok=True)
    tmp = AUTOSAVE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, AUTOSAVE_PATH)


# ─────────────────────────────────────────────
# 사이트 설정 (저자 소개·카테고리 목록) — 두 PC가 같이 쓰도록 데이터 폴더에 저장
# ─────────────────────────────────────────────
SETTINGS_PATH = os.path.join(DATA_DIR, "site_settings.json")
SETTINGS_DEFAULTS = {
    "author_bio": "",        # 저자 소개 (2~4줄)
    "disclosure": "",        # 이해관계 고지 (예: 업체와 금전적 관계 없음)
    "disclose_ai": False,    # AI 도구 도움 사실을 글 끝에 밝힐지 (의무 아님 — 기본은 끔)
    "categories": [],        # 내 블로그 카테고리 목록 (비우면 AI가 자유롭게)
    "site_url": "",          # 내 블로그 주소 — 링크가 내부(같은 창)/외부(새 창)인지 가리는 기준
}


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return {k: data.get(k, v) for k, v in SETTINGS_DEFAULTS.items()}


def save_settings(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({k: data.get(k, v) for k, v in SETTINGS_DEFAULTS.items()}, f, ensure_ascii=False, indent=2)


def load_past_tags(platform, drafts_dir=DRAFTS_DIR, limit=30):
    """같은 플랫폼 지난 원고에서 많이 쓴 태그 순으로 (태그 재사용 → 얇은 태그 페이지 방지)."""
    counts = {}
    if not os.path.isdir(drafts_dir):
        return []
    for name in os.listdir(drafts_dir):
        if not name.endswith(".txt"):
            continue
        try:
            info = read_draft_file(os.path.join(drafts_dir, name))
        except (OSError, UnicodeDecodeError):
            continue
        if info["platform"] != platform:
            continue
        for tag in re.split(r"[,，]", parse_draft_metadata(info["draft"])["tags"]):
            tag = tag.strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:limit]


def extract_references(inputs):
    """입력 재료에서 '참고 자료' 목록을 만든다. 반환: ['이름 | 주소' 또는 '이름']"""
    refs = []
    if inputs.get("mode") == "materials":
        for block in inputs.get("sources", []):
            header, _, rest = block.partition("\n")
            label = re.sub(r"^\[자료 \d+\]\s*", "", header).strip()
            source_line = next((l for l in rest.split("\n") if l.strip().startswith("출처:")), "")
            name = source_line.split(":", 1)[1].strip() if source_line else label
            name = re.sub(r"\s*/\s*", " · ", name)
            refs.append(f"{name} | {label}" if re.match(r"https?://", label) else name)
    else:
        for line in inputs.get("sources", []):
            url = re.search(r"원문:\s*(https?://\S+)", line)
            name = re.split(r"\s+—\s+", line)[0].strip()
            if re.match(r"https?://", name):
                continue
            refs.append(f"{name[:80]} | {url.group(1)}" if url else name[:80])
    seen, unique = set(), []
    for r in refs:
        if r and r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def publish_tail(inputs, settings, written=""):
    """발행용 HTML 끝에 붙일 '참고 자료' + '글쓴이' 블록 (본문 칸에는 넣지 않고 출력할 때만 붙임)."""
    parts = []
    refs = extract_references(inputs)
    if refs:
        parts.append("[참고 자료]\n" + "\n".join(f"- {r}" for r in refs) + "\n[참고 자료 끝]")
    lines = [l.strip() for l in settings.get("author_bio", "").split("\n") if l.strip()]
    if lines:
        basis = "공개 자료" if inputs.get("mode") == "materials" else "공개 자료와 필자의 실무 경험"
        note = f"이 글은 {written + ' 기준 ' if written else ''}{basis}를 바탕으로 작성했습니다."
        if settings.get("disclose_ai"):
            note += " 초안 정리에 AI 도구의 도움을 받았고, 내용 확인과 최종 판단은 필자가 했습니다."
        lines.append(note)
        if settings.get("disclosure", "").strip():
            lines.append(settings["disclosure"].strip())
        parts.append("[저자 소개]\n" + "\n".join(lines) + "\n[저자 소개 끝]")
    return safe_tilde("\n\n".join(parts))



def source_cards(inputs):
    """원문 링크가 있는 출처를 '원문 카드' 데이터로 만든다 (번호 → 정보).
    번호: 자료로 쓰기 = [자료 N]의 N, 메모로 쓰기 = 출처 칸의 줄 순서(1부터).
    카드 내용(주소·매체·제목)은 AI가 아니라 이 프로그램이 출처에서 그대로 가져온다 — 링크를 지어낼 수 없게."""
    cards = {}
    if inputs.get("mode") == "materials":
        for block in inputs.get("sources", []):
            header, _, rest = block.partition("\n")
            m = re.match(r"^\[자료 (\d+)\]\s*(\S+)", header)
            if not m or not re.match(r"https?://", m.group(2)):
                continue
            src = next((l for l in rest.split("\n") if l.strip().startswith("출처:")), "")
            fields = [f.strip() for f in src.split(":", 1)[1].split("/")] if src else []
            first_fact = next((l.strip()[2:].strip() for l in rest.split("\n") if l.strip().startswith("- ")), "")
            cards[int(m.group(1))] = {
                "url": m.group(2),
                "site": fields[0] if fields else _domain(m.group(2)),
                "title": fields[1] if len(fields) > 1 else (fields[0] if fields else m.group(2)),
                "date": fields[2] if len(fields) > 2 else "",
                "desc": first_fact[:120],
            }
    else:
        for i, line in enumerate(inputs.get("sources", []), start=1):
            url = re.search(r"원문:\s*(https?://\S+)", line)
            if not url:
                continue
            parts = [p.strip() for p in re.split(r"\s+—\s+", line) if not p.strip().startswith("원문:")]
            cards[i] = {
                "url": url.group(1),
                "site": _domain(url.group(1)),
                "title": (parts[0] if parts else url.group(1))[:80],
                "date": "",
                "desc": (parts[1] if len(parts) > 1 else "")[:120],
            }
    return cards


def _domain(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else url


def card_numbers(body):
    """본문에 들어간 [원문 카드: N] 번호들."""
    return [int(m.group(1)) for m in (_CARD_RE.match(l.strip()) for l in body.split("\n")) if m]


# ─────────────────────────────────────────────
# 메모에 넣는 표 (엑셀 복사·직접 작성·HTML 표 → 본문 [표] 표기법)
# ─────────────────────────────────────────────
TABLE_INPUT_MAX = 20000


class _HTMLTableParser(HTMLParser):
    """HTML 안의 <table>들을 [{"caption", "rows"}]로 뽑는다 (글자만, 태그·스타일은 버림)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._table, self._row, self._cell, self._caption = [], None, None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = {"caption": "", "rows": []}
        elif self._table is None:
            return
        elif tag == "caption":
            self._caption = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if self._table is None:
            return
        if tag == "caption" and self._caption is not None:
            self._table["caption"] = " ".join("".join(self._caption).split())
            self._caption = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table":
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._caption is not None:
            self._caption.append(data)


def _clean_cell(text):
    return " ".join(str(text).replace("|", "/").split())


def _split_row(line):
    if "\t" in line:
        return line.split("\t")
    if "|" in line:
        cells = line.strip().strip("|").split("|")
        return None if all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells) else cells  # 마크다운 구분줄
    return None


def parse_table_input(text):
    """메모 칸에 넣은 표를 읽는다. 반환: (표 목록 [{"caption", "rows"}], 문제 안내 목록)
    - HTML 표(<table>…</table>): 칸 글자만 가져옴
    - 엑셀·구글시트에서 복사한 표(칸이 탭으로 나뉨)
    - 직접 쓴 표: 칸을 | 로 구분 (마크다운 표도 됨)
    표가 여러 개면 빈 줄로 나누거나 각 표 위에 '[표] 표 제목' 줄을 둬. 칸이 아닌 첫 줄은 표 제목으로 씀."""
    text = (text or "").strip()
    if not text:
        return [], []
    if re.search(r"<table\b", text, re.IGNORECASE):
        parser = _HTMLTableParser()
        parser.feed(text)
        raw_tables = parser.tables
    else:
        raw_tables, current = [], None
        for line in text.split("\n"):
            s = line.strip()
            if s.startswith("[표 끝]"):
                current = None
                continue
            if not s:
                if current and current["rows"]:
                    current = None
                continue
            if s.startswith("[표]"):
                current = {"caption": s[len("[표]"):].strip(), "rows": []}
                raw_tables.append(current)
                continue
            cells = _split_row(line.rstrip("\r"))
            if cells is None:
                if "|" in s or "\t" in line:
                    continue  # 마크다운 구분줄
                if current is None or current["rows"]:
                    current = {"caption": s, "rows": []}
                    raw_tables.append(current)
                else:
                    current["caption"] = (current["caption"] + " " + s).strip()
                continue
            if current is None:
                current = {"caption": "", "rows": []}
                raw_tables.append(current)
            current["rows"].append(cells)

    tables, problems = [], []
    for i, t in enumerate(raw_tables, 1):
        rows = [[_clean_cell(c) for c in r] for r in t["rows"]]
        rows = [r for r in rows if any(r)]
        width = max((len(r) for r in rows), default=0)
        if len(rows) < 2 or width < 2:
            if rows or t["caption"]:
                problems.append(f"표 {i}({t['caption'] or '제목 없음'})는 칸을 못 읽었어 — 머리글 포함 2줄 이상, "
                                "칸 2개 이상이어야 해 (칸은 탭이나 | 로 구분)")
            continue
        rows = [r + [""] * (width - len(r)) for r in rows]
        tables.append({"caption": _clean_cell(t["caption"]), "rows": rows})
    return tables, problems


def tables_to_markup(tables):
    """parse_table_input 결과를 본문 표기법([표] … [표 끝]) 문자열 목록으로."""
    return ["\n".join([f"[표] {t['caption']}".rstrip()] + [" | ".join(r) for r in t["rows"]] + ["[표 끝]"])
            for t in tables]


def normalize_own_tables(text):
    """내가 쓴 원고 안에 붙여넣은 표를 [표] … [표 끝] 표기로 바꾼다 (그 자리 그대로).
    - HTML 표(<table>…</table>)
    - 엑셀·구글시트에서 복사한 표 (칸이 탭으로 나뉜 줄이 2줄 이상 연속)
    - | 로 칸을 나눈 줄이 2줄 이상 연속 (마크다운 표 포함)
    이미 [표] … [표 끝]으로 쓴 표, [링크: …]·[버튼: …] 같은 표시 줄은 건드리지 않는다.
    반환: (바뀐 원고, 바꾼 표 개수)"""
    count = 0

    def html_table(m):
        nonlocal count
        tables, _ = parse_table_input(m.group(0))
        if not tables:
            return m.group(0)
        count += len(tables)
        return "\n\n" + "\n\n".join(tables_to_markup(tables)) + "\n\n"

    text = re.sub(r"<table\b.*?</table>", html_table, text or "", flags=re.IGNORECASE | re.DOTALL)

    def row_of(line):
        s = line.strip()
        if not s or (s.startswith("[") and not s.startswith("[[")):
            return None
        if "\t" in line:
            cells = [c.strip() for c in line.strip("\r\n").split("\t")]
        elif "|" in visible_text(s):
            cells = _split_cells(s.strip("|"))
        else:
            return None
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):  # 마크다운 구분줄
            return []
        return cells if sum(1 for c in cells if c) >= 2 else None

    out, run, in_box = [], [], False

    def flush_run():
        nonlocal count
        rows = [r for r in run if r]
        if len(rows) >= 2:
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            out.extend(["", "[표]", *(" | ".join(c.replace("|", "/") if not INLINE_LINK_RE.search(c) else c
                                                   for c in r) for r in rows), "[표 끝]", ""])
            count += 1
        else:
            out.extend(raw_run)
        run.clear()
        raw_run.clear()

    raw_run = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[표]"):
            in_box = True
        if in_box:
            if run:
                flush_run()
            out.append(line)
            if s.startswith("[표 끝]"):
                in_box = False
            continue
        cells = row_of(line)
        if cells is not None:
            run.append(cells)
            raw_run.append(line)
            continue
        if run:
            flush_run()
        out.append(line)
    if run:
        flush_run()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), count
