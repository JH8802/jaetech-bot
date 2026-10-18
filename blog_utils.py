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


def load_past_titles(platform, drafts_dir="drafts", limit=30):
    """drafts/ 폴더의 지난 초안 중 같은 플랫폼 글의 [제목]만 최신순으로 뽑는다
    (내부 링크 추천용). 다른 플랫폼 글은 다른 블로그라 링크 대상이 아니므로 제외.
    """
    if not os.path.isdir(drafts_dir):
        return []

    files = sorted((f for f in os.listdir(drafts_dir) if f.endswith(".txt")), reverse=True)
    titles = []
    for name in files:
        try:
            with open(os.path.join(drafts_dir, name), encoding="utf-8") as f:
                lines = [line.strip() for line in f]
        except (OSError, UnicodeDecodeError):
            continue

        if f"플랫폼: {platform}" not in lines[:3]:
            continue
        title = next((l[len("[제목]"):].strip() for l in lines if l.startswith("[제목]")), "")
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles
