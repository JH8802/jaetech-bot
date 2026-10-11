"""표시·광고 표현 점검 (건강기능식품·식품 정보글용 보조 도구).

완성된 글의 제목·본문·해시태그에서 식품 표시·광고 심사에서 문제가 될 수 있는 표현을 목록 기반으로 찾아 줍니다.
- 법률 판단이 아니라 '사람이 한 번 더 보라'는 표시입니다. 최종 판단은 식약처 기준과 본인 검토로 하세요.
- 아래 RULES 가 점검 목록입니다. 업무 기준에 맞게 자유롭게 추가·삭제하세요. (정규식, 한글 그대로 적으면 됩니다)
- '높음': 질병의 치료·예방 등을 표방하는 것으로 읽힐 수 있는 표현
  '주의': 기능성을 단정·암시하거나 과장·보증으로 읽힐 수 있는 표현(인정된 기능성 범위인지 확인)
- 같은 문장에 '않, 아닙, 아니, 어렵, 단정, 금지, 제한, 내세우, 표방, 주장, 광고, 문구, 표현, 불분명, 충분하지, 부족'처럼
  부정·설명 맥락이 있으면 '참고'로 내려서 점검 결과(통과/주의)에는 세지 않습니다.
  예) "효과를 약속하는 글은 아닙니다" → 참고
"""
import re

from postprocess import HEADING_RE, MAP_LINE_MARK, find_hashtag_index, split_paragraphs, strip_tags

# (수준, 분류, [정규식...])
RULES = [
    ("high", "질병 치료·예방 표방", [
        r"치료", r"치유", r"완치", r"처방", r"진단", r"항암", r"예방", r"재발",
    ]),
    ("warn", "효능·기능 단정·암시", [
        r"효능", r"효과", r"개선", r"완화", r"항산화", r"노화\s*(?:방지|억제|지연)", r"안티\s*에이징", r"회춘", r"젊어",
        r"해독", r"디톡스", r"독소\s*배출", r"체지방", r"다이어트", r"혈행", r"혈관\s*청소",
        r"면역(?:력)?\s*(?:강화|증진|향상|높)", r"염증", r"통증", r"피로\s*회복", r"기억력", r"활력",
        r"도움이\s*(?:됩|된|되)", r"도움을\s*(?:줍|준|주)", r"좋아(?:집|져|진)", r"탁월", r"특효",
    ]),
    ("warn", "과장·보증", [
        r"100\s*%", r"부작용\s*(?:이\s*)?없", r"만병", r"기적", r"즉시", r"즉각", r"완벽", r"최고", r"1\s*위",
        r"국내\s*유일", r"임상\s*(?:시험\s*)?(?:으로\s*)?(?:입증|검증)", r"의사\s*추천", r"전문가\s*추천",
    ]),
]

# 이 말이 같은 문장에 있으면 '표현을 소개·부정하는 문장'으로 보고 참고로 내립니다.
SOFT_RE = re.compile(r"(않|아닙|아니|어렵|단정|금지|제한|내세우|표방|주장|광고|문구|표현|불분명|충분하지|부족)")

_COMPILED = [(lv, cat, re.compile("|".join(f"(?:{p})" for p in pats))) for lv, cat, pats in RULES]
_SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")


def _units(title: str, body: str):
    """(위치, 문장) 목록: 제목 / 본문 문장 / 해시태그 하나하나"""
    if title:
        yield "제목", title
    paras = split_paragraphs(strip_tags(body))
    tag_i = find_hashtag_index(paras)
    for i, par in enumerate(paras):
        if re.fullmatch(r"<\s*사진\s*\d+\s*>", par) or MAP_LINE_MARK in par:
            continue
        if i == tag_i:
            for t in re.findall(r"#[^\s#]+", par):
                yield "해시태그", t
            continue
        where = "소제목" if HEADING_RE.match(par) else "본문"
        for s in _SENT_SPLIT.split(par):
            if s.strip():
                yield where, s.strip()


def scan(title: str, body: str) -> list[dict]:
    """표시·광고 주의 표현을 찾아 [{level, category, match, where, sentence, soft}] 로 돌려줍니다."""
    hits, seen = [], set()
    for where, sent in _units(title, body):
        taken: list[tuple[int, int]] = []  # 앞선(더 위험한) 규칙과 겹치는 위치는 건너뜀
        soft = where != "해시태그" and bool(SOFT_RE.search(sent))
        for level, cat, rx in _COMPILED:
            for m in rx.finditer(sent):
                span = m.span()
                if any(span[0] < e and s < span[1] for s, e in taken):
                    continue
                taken.append(span)
                key = (m.group(0), sent)
                if key in seen:
                    continue
                seen.add(key)
                snippet = sent if len(sent) <= 90 else "…" + sent[max(0, m.start() - 40): m.end() + 40] + "…"
                hits.append({"level": level, "category": cat, "match": m.group(0), "where": where, "sentence": snippet, "soft": soft})
    return hits


def summarize(hits: list[dict]) -> dict:
    hard = [h for h in hits if not h["soft"]]
    return {
        "high": sum(h["level"] == "high" for h in hard),
        "warn": sum(h["level"] == "warn" for h in hard),
        "soft": len(hits) - len(hard),
        "hard_terms": list(dict.fromkeys(h["match"] for h in hard)),
    }
