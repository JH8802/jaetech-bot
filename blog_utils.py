import html
import os


def extract_text(message):
    """Claude 응답에서 실제 텍스트만 뽑아낸다.

    확장 사고(thinking)가 켜져 있으면 content[0]이 텍스트가 아닐 수 있어서,
    타입으로 찾아야 한다 (content[0]을 무조건 텍스트로 가정하면 안 됨).
    """
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


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


def body_to_html(body):
    """본문(태그 포함 일반 텍스트)을 티스토리 HTML 모드 / 워드프레스 코드
    편집기에 바로 붙여넣을 HTML로 바꾼다.
    - [소제목] → <h2> (구글이 읽는 제목 구조가 확실하게 들어감)
    - 문단 → <p>
    - [사진/그래프/지도 제안], [내부링크 제안] → 눈에 띄는 안내 문단으로 남김
      (실제 사진 업로드·링크 연결은 직접 해야 하므로 지우지 않고 표시)
    """
    blocks = []
    paragraph = []

    def flush():
        if paragraph:
            blocks.append("<p>" + "<br>\n".join(paragraph) + "</p>")
            paragraph.clear()

    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("[소제목]"):
            flush()
            blocks.append(f"<h2>{html.escape(stripped[len('[소제목]'):].strip())}</h2>")
        elif stripped.startswith(VISUAL_TAGS) or stripped.startswith("[내부링크 제안]"):
            flush()
            blocks.append(
                '<p style="background:#fff3cd;padding:8px;">'
                f"📌 {html.escape(stripped)}</p>"
            )
        else:
            paragraph.append(html.escape(stripped))
    flush()
    return "\n\n".join(blocks)
