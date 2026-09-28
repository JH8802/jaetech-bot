def extract_text(message):
    """Claude 응답에서 실제 텍스트만 뽑아낸다.

    확장 사고(thinking)가 켜져 있으면 content[0]이 텍스트가 아닐 수 있어서,
    타입으로 찾아야 한다 (content[0]을 무조건 텍스트로 가정하면 안 됨).
    """
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""
