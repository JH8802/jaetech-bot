"""Claude 호출 모음. API 키는 서버(.env)에서만 읽습니다.

BLOGDEX_MOCK=1 이면 API를 부르지 않고 샘플 원고를 돌려줍니다. (화면·서버 점검용, 비용 0원)
"""
import os
import re
import time

import anthropic
from dotenv import load_dotenv

load_dotenv()

# 모델은 .env 의 BLOGDEX_MODEL 로 바꿉니다. 비용을 줄이려면 claude-sonnet-5-5 등.
MODEL = os.getenv("BLOGDEX_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("BLOGDEX_EFFORT", "medium")  # low | medium | high
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 1백만 토큰당 달러 (입력, 출력). 2026-10 기준 공시 가격이며 바뀔 수 있습니다.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    p = PRICES.get(model)
    return None if not p else round((input_tokens * p[0] + output_tokens * p[1]) / 1_000_000, 4)


def _fill_usage(usage: dict | None, final) -> None:
    if usage is None:
        return
    u = getattr(final, "usage", None)
    model = getattr(final, "model", MODEL) or MODEL
    inp, out = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
    usage.update(model=model, input_tokens=inp, output_tokens=out, cost_usd=estimate_cost(model, inp, out))


def is_mock() -> bool:
    return os.getenv("BLOGDEX_MOCK") == "1"


class RefusedError(Exception):
    pass


class TruncatedError(Exception):
    pass


_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았어요. 루트의 .env 파일을 확인하세요.")
        _client = anthropic.Anthropic()
    return _client


def _use_fallbacks() -> bool:
    return MODEL in FALLBACK_MODELS and os.getenv("BLOGDEX_FALLBACKS", "1") == "1"


def _kwargs(system: str, user: str, max_tokens: int, effort: str) -> dict:
    return dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
    )


def stream_text(system: str, user: str, max_tokens: int = 16000, effort: str | None = None, usage: dict | None = None):
    """Claude가 쓰는 글을 조각(text)으로 흘려보냅니다. 끝나면 거절·잘림 여부를 확인하고 usage 에 토큰 수를 채웁니다."""
    if is_mock():
        yield from _mock_stream(system, user)
        if usage is not None:
            usage.update(model="mock", input_tokens=0, output_tokens=0, cost_usd=0.0)
        return
    kwargs = _kwargs(system, user, max_tokens, effort or EFFORT)
    client = get_client()
    if _use_fallbacks():
        ctx = client.beta.messages.stream(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
    else:
        ctx = client.messages.stream(**kwargs)
    with ctx as stream:
        for text in stream.text_stream:
            yield text
        final = stream.get_final_message()
    _fill_usage(usage, final)
    if final.stop_reason == "refusal":
        raise RefusedError("이 주제는 AI가 작성을 거절했어요. 주제나 표현을 바꿔서 다시 시도해 주세요.")
    if final.stop_reason == "max_tokens":
        raise TruncatedError("원고가 너무 길어 중간에 끊겼어요. 다시 시도해 주세요.")


def ask_text(system: str, user: str, max_tokens: int = 1024, effort: str = "low") -> str:
    """짧은 응답(제목 후보 등)을 한 번에 받습니다."""
    if is_mock():
        return "\n".join(_mock_titles(user))
    kwargs = _kwargs(system, user, max_tokens, effort)
    client = get_client()
    if _use_fallbacks():
        resp = client.beta.messages.create(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RefusedError("이 주제는 AI가 작성을 거절했어요. 주제나 표현을 바꿔서 다시 시도해 주세요.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("AI 응답이 비어 있어요. 다시 시도해 주세요.")
    return text


# ---------- 샘플(MOCK) ----------
def _mock_titles(user: str) -> list[str]:
    m = re.search(r"주제/키워드: (.+)", user)
    kw = (m.group(1).strip() if m else "키워드")[:20]
    return [f"{kw} 후보 제목 {i}" for i in range(1, 6)]


def _mock_stream(system: str, user: str):
    title = (re.search(r"\[글 제목\]\n(.+)", user) or [None, "샘플"])[1]
    food = "맛집글" in system
    kw = (re.search(r"\[핵심 키워드\]\n(.+)", user) or [None, title])[1].split(",")[0].strip()
    memo_m = re.search(r"\[작성자 메모[^\]]*\]\n(.+?)(?:\n\n|$)", user, re.S)
    memo = memo_m.group(1).strip() if memo_m and memo_m.group(1).strip() != "(없음)" else "샘플 메모"
    if food:
        text = (
            f"{kw}에 다녀왔어요. {{{{highlight}}}}메모에 적어 주신 내용을 중심으로 썼습니다.{{{{/highlight}}}} 저는 {memo[:30]}라고 느꼈어요.\n\n"
            "퇴근길에 들렀는데, 줄이 길지 않아서 바로 앉았습니다. 자리는 좁은 편이었죠.\n\n"
            "1. 가게 위치와 분위기\n\n"
            f"{kw}은 역에서 걸어서 5분쯤 걸립니다. {{{{bold}}}}간판이 눈에 잘 띄어서{{{{/bold}}}} 찾기 쉬웠어요.\n\n"
            "안쪽은 조명이 낮았고, 테이블 간격이 좁아서 옆자리 이야기가 들렸습니다.\n\n"
            "2. 주문한 메뉴\n\n"
            f"{{{{color}}}}메모에 적힌 메뉴를 기준으로 썼어요.{{{{/color}}}} 가격은 [확인 필요: 가격]입니다.\n\n"
            "3. 다른 메뉴와 추천 조합\n\n"
            "다음에는 다른 메뉴도 먹어 보려고 합니다. 혼자 가기에는 조금 부담스러운 양이었어요.\n\n"
            "4. 다시 갈 만한가?\n\n"
            f"{{{{highlight}}}}다시 갈 의향이 있습니다.{{{{/highlight}}}} {{{{bold}}}}평일 저녁{{{{/bold}}}}에 가면 더 여유로울 것 같아요.\n\n"
        )
        tags = [f"#{kw.replace(' ', '')}", f"#{kw.split()[0]}"] + [f"#맛집태그{i}" for i in range(1, 27)]
    else:
        text = (
            f"{kw}을 고를 때는 {{{{bold}}}}기준부터{{{{/bold}}}} 정해야 합니다. {{{{highlight}}}}먼저 확인할 것은 표시 사항입니다.{{{{/highlight}}}}\n\n"
            "이 글에서는 확인 순서를 차례로 정리합니다. 메모에 적은 경험도 함께 반영했습니다.\n\n"
            "1. 먼저 알아둘 개념\n\n개념을 짧게 설명합니다. 다만 단정하지는 않습니다.\n\n"
            "2. 확인하는 방법\n\n"
            "{{color}}표시 사항을 직접 확인해야 합니다.{{/color}} 출처를 모르면 [확인 필요: 출처]로 남깁니다.\n\n"
            "3. 주의할 점\n\n광고 문구만 보고 판단하지 않습니다.\n\n"
            "4. 실천 방법\n\n오늘 바로 확인할 수 있는 순서를 정리했습니다.\n\n"
            "{{highlight}}정리하면 표시를 먼저 보는 것이 기준입니다.{{/highlight}}\n\n읽어 주셔서 감사합니다.\n\n"
        )
        tags = [f"#{kw.replace(' ', '')}"] + [f"#정보태그{i}" for i in range(1, 28)]
    full = text + " ".join(tags)
    for i in range(0, len(full), 7):
        time.sleep(0)
        yield full[i:i + 7]
