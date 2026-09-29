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
    "[태그]": "tags",
}


def parse_draft_metadata(draft):
    """draft_post()가 만든 텍스트에서 [제목]/[카테고리]/[메타설명]/[태그]
    줄을 뽑아내고, 나머지는 본문으로 분리한다.

    반환: {"title": str, "category": str, "meta_description": str,
           "tags": str, "body": str}
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
