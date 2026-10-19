import html
import json
import os
import re
import shutil
from datetime import datetime


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
            meta[matched_key] = stripped[len(tag):].strip()
        else:
            body_lines.append(line)

    meta["body"] = "\n".join(body_lines).strip()
    return meta


def has_keyword(text, keyword):
    """띄어쓰기 차이는 무시하고, 키워드의 단어가 모두 들어 있으면 포함으로 본다
    (예: '유산균 보장균수' → '유산균의 보장균수'도 통과)."""
    flat = text.replace(" ", "").lower()
    return all(word.lower() in flat for word in keyword.split())


def _read_past_drafts(platform, drafts_dir="drafts"):
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


def load_past_titles(platform, drafts_dir="drafts", limit=30):
    """같은 플랫폼 지난 초안의 [제목]만 최신순·중복 없이 (내부 링크 추천용)."""
    titles = []
    for _, title, _ in _read_past_drafts(platform, drafts_dir):
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def find_keyword_overlap(platform, keyword, exclude=(), drafts_dir="drafts"):
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
    r"|\[추가 필요[^\]\n]*\]",
    re.MULTILINE,
)
_INLINE_TAG_RE = re.compile(r"\[(?:출처 필요|추가 필요)[^\]\n]*\]")
_LINK_LINE_RE = re.compile(r"^\[링크:\s*(.*?)\s*\|\s*(https?://\S+)\s*\]$")
_IMAGE_LINE_RE = re.compile(r"^\[이미지:\s*(https?://\S+)\s*\|\s*(.*?)\s*\]$")


def body_to_html(body):
    """본문(태그 포함 일반 텍스트)을 티스토리 HTML 모드 / 워드프레스 코드
    편집기에 바로 붙여넣을 HTML로 바꾼다.
    - [소제목] → <h2> (구글이 읽는 제목 구조가 확실하게 들어감)
    - 문단 → <p>
    - [링크: 제목 | 주소] → 관련 글 링크, [이미지: 주소 | ALT] → 이미지
    - 아직 안 채운 [사진/그래프/지도 제안], [내부링크 제안], [추가 필요] → 노란 안내 문단
    - 문장 안의 아직 안 채운 [출처 필요]/[추가 필요] → 노란 형광펜 표시
    """
    blocks = []
    paragraph = []

    def flush():
        if paragraph:
            blocks.append("<p>" + "<br>\n".join(paragraph) + "</p>")
            paragraph.clear()

    def mark_inline(text):
        return _INLINE_TAG_RE.sub(lambda m: f'<mark>{m.group(0)}</mark>', text)

    for line in body.split("\n"):
        stripped = line.strip()
        link = _LINK_LINE_RE.match(stripped)
        image = _IMAGE_LINE_RE.match(stripped)
        if not stripped:
            flush()
        elif stripped.startswith("[소제목]"):
            flush()
            blocks.append(f"<h2>{html.escape(stripped[len('[소제목]'):].strip())}</h2>")
        elif link:
            flush()
            title, url = link.groups()
            blocks.append(f'<p>👉 함께 보면 좋은 글: <a href="{html.escape(url)}">{html.escape(title)}</a></p>')
        elif image:
            flush()
            url, alt = image.groups()
            blocks.append(f'<p><img src="{html.escape(url)}" alt="{html.escape(alt)}"></p>')
        elif stripped.startswith(VISUAL_TAGS) or stripped.startswith(("[내부링크 제안]", "[추가 필요")):
            flush()
            blocks.append(
                '<p style="background:#fff3cd;padding:8px;">'
                f"📌 {html.escape(stripped)}</p>"
            )
        else:
            paragraph.append(mark_inline(html.escape(stripped)))
    flush()
    return "\n\n".join(blocks)


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
        if item["kind"] == "add":
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
        f"[카테고리] {meta.get('category', '')}",
        f"[메타설명] {meta.get('meta_description', '')}",
        f"[주소] {meta.get('slug', '')}",
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
        f.write(f"주제: {topic}\n플랫폼: {platform}\n타깃 키워드: {keyword}\n\n{draft}")
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


def list_saved_drafts(drafts_dir="drafts", limit=100):
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
STYLE_SAMPLE_PATH = "my_style.txt"
STYLE_SAMPLE_MAX = 3000
AUTOSAVE_PATH = os.path.join("drafts", "_autosave.json")


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
