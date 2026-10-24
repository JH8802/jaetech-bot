"""투자 생각 글 가드레일 강제: 프롬프트 지시만 믿지 않고, 코드가 마지막에 한 번 더 지킵니다.

1) 위반 표현(매수·매도 권유, 수익 보장, 전망 단정 - adcheck.INVEST_RULES)이 남으면 AI에게 그 문장만 고치게 한 번 요청하고(app.py),
2) 그래도 남은 문장은 코드가 지웁니다(remove_violations).
3) '개인 생각이며 투자 판단과 책임은 각자에게 있다'는 안내 문장이 없으면 코드가 넣습니다(ensure_disclaimer).
"""
import random
import re

import adcheck
from postprocess import ONE_LINER_RE, SOURCE_HEAD, find_hashtag_index, is_special_paragraph, normalize_tags, split_paragraphs, split_sentences, strip_tags

# 코드가 넣는 안내 문장(AI가 직접 쓰지 않았을 때만). 매번 같은 문장이면 틀에 박혀 보여서 몇 가지 중에 고름
DISCLAIMERS = [
    "이 글은 제 개인적인 생각을 적은 기록이에요.\n특정 종목의 매수나 매도를 권하는 글이 아니에요.\n투자 판단과 책임은 각자에게 있어요.",
    "어디까지나 제 개인 생각이고, 무언가를 사거나 팔라는 이야기는 아니에요.\n투자 판단과 책임은 각자의 몫이라는 것만 기억해 주세요.",
    "제 일기 같은 글이라 정답은 아니에요.\n매수·매도를 권하는 글이 아니고, 투자 판단과 책임은 각자에게 있어요.",
]
DISCLAIMER = DISCLAIMERS[0]
# 말투 샘플 어미가 한다체·합니다체일 때 쓰는 안내 문장
DISCLAIMERS_BY_REGISTER = {
    "plain": [
        "이 글은 내 개인적인 생각을 적은 기록이다.\n특정 종목의 매수나 매도를 권하는 글이 아니다.\n투자 판단과 책임은 각자에게 있다.",
        "어디까지나 내 개인 생각일 뿐, 무언가를 사거나 팔라는 이야기는 아니다.\n투자 판단과 책임은 각자의 몫이다.",
        "정답이 아니라 내 투자 일기다.\n매수·매도를 권하는 글이 아니고, 투자 판단과 책임은 각자에게 있다.",
    ],
    "formal": [
        "이 글은 제 개인적인 생각을 적은 기록입니다.\n특정 종목의 매수나 매도를 권하는 글이 아닙니다.\n투자 판단과 책임은 각자에게 있습니다.",
        "어디까지나 제 개인 생각이며, 무언가를 사거나 팔라는 이야기는 아닙니다.\n투자 판단과 책임은 각자의 몫입니다.",
    ],
}
DISCLAIMER_RE = re.compile(r"투자\s*(?:판단|결정)[^\n.]{0,20}(?:책임|본인|각자|스스로)|(?:매수|매도|투자)[^\n.]{0,12}(?:권유|추천|권하)[^\n.]{0,8}(?:글|것)이?\s*아니")


def violations(body: str, title: str = "") -> list[dict]:
    """참고(부정·설명 맥락)를 뺀 위반 표현 목록"""
    return [h for h in adcheck.scan(title, body, "invest") if not h["soft"]]


def _sentence_bad(sent: str) -> bool:
    return bool(violations(strip_tags(sent)))


def remove_violations(body: str) -> tuple[str, list[str]]:
    """위반 표현이 든 문장을 지웁니다. 지운 문장 목록도 돌려줍니다(화면 안내용)."""
    out, removed = [], []
    for par in split_paragraphs(body):
        if is_special_paragraph(par):
            out.append(par)
            continue
        keep = []
        for sent in split_sentences(par):
            if _sentence_bad(sent):
                removed.append(strip_tags(sent))
            else:
                keep.append(sent)
        if keep:
            out.append("\n".join(keep))
    return normalize_tags("\n\n".join(out)), removed


def ensure_disclaimer(body: str, register: str = "") -> tuple[str, bool]:
    """안내 문장이 없으면 '한 줄 정리' 바로 앞(없으면 참고 기사·해시태그 앞)에 넣습니다."""
    if DISCLAIMER_RE.search(strip_tags(body)):
        return body, False
    paras = split_paragraphs(body)
    end = find_hashtag_index(paras)
    end = end if end is not None else len(paras)
    src = next((i for i in range(end) if strip_tags(paras[i]).startswith(SOURCE_HEAD)), None)
    end = src if src is not None else end
    one = next((i for i in range(end - 1, -1, -1) if ONE_LINER_RE.match(strip_tags(paras[i]))), None)
    if one is None and end > 0 and not is_special_paragraph(paras[end - 1]):
        one = end - 1  # 라벨 없이 끝나는 흐름: 마지막 본문 문단(맺음) 바로 앞
    paras.insert(one if one is not None else end, random.choice(DISCLAIMERS_BY_REGISTER.get(register, DISCLAIMERS)))
    return "\n\n".join(paras), True
