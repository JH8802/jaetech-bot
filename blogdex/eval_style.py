"""원고 품질 점검: 검색 최적화와 '사람이 쓴 느낌'을 숫자로 잽니다.

기준 근거는 DESIGN.md §2.13(원본 3건 분석)과 §4.10(작문 사양).
통과/주의는 '권장 기준'이며 글을 막지 않습니다. 주의 항목은 다시 쓰기 요청에 쓰입니다.
"""
import itertools
import re
import statistics as st

from postprocess import HEADING_RE, MAP_LINE_MARK, count_chars, find_hashtag_index, split_paragraphs, strip_tags

GENERIC_WORDS = ["편안", "무난", "자연스럽", "부담", "좋았", "좋겠", "차분", "다양한", "효과적", "전반적으로"]
FIRST_PERSON_RE = re.compile(r"^(저는|저도|제가|저의)")
JOSA_RE = re.compile(r"(으로|에서|까지|부터|이랑|에게|은|는|이|가|을|를|에|도|로|과|와|의|만)$")
STOP_TOKENS = {"그리고", "하지만", "그런데", "너무", "정말", "진짜", "그냥", "조금", "많이", "있었", "했다", "했어"}


def _body_parts(body: str):
    paras = split_paragraphs(strip_tags(body))
    tag_i = find_hashtag_index(paras)
    tags = paras.pop(tag_i) if tag_i is not None else ""
    heads = [p for p in paras if HEADING_RE.match(p)]
    text_paras = [p for p in paras if not HEADING_RE.match(p) and MAP_LINE_MARK not in p
                  and not re.fullmatch(r"(<)?사진 ?\d+(>)?", p)]
    return text_paras, heads, tags


def _sentences(par: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", par.strip()) if s.strip()]


def _ending(s: str) -> str:
    core = s.rstrip(".?!")
    if core.endswith("니다"):
        return "formal"
    if re.search(r"(더라고요|거든요|잖아요|겠죠|죠|네요)$", core):
        return "colloquial"
    if core.endswith("요"):
        return "polite"
    return "other"


def _check(key, label, value, target, ok, advice):
    return {"key": key, "label": label, "value": value, "target": target, "ok": bool(ok), "advice": advice}


def _memo_coverage(memo: str, body_plain: str) -> tuple[float, int]:
    tokens = []
    for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", memo):
        stem = JOSA_RE.sub("", t) if re.search(r"[가-힣]", t) else t
        if len(stem) >= 2 and stem not in STOP_TOKENS and stem not in tokens:
            tokens.append(stem)
    tokens = sorted(tokens, key=len, reverse=True)[:20]
    if not tokens:
        return 1.0, 0
    hit = sum(1 for t in tokens if t in body_plain)
    return hit / len(tokens), len(tokens)


def evaluate(kind: str, body: str, keywords: list[str], memo: str = "") -> dict:
    paras, heads, tags = _body_parts(body)
    text = "\n".join(paras)
    plain_len = len(re.sub(r"\s", "", text))
    sents = [s for p in paras for s in _sentences(p)]
    checks = []

    # 1) 첫 문단에 핵심 키워드
    first = paras[0] if paras else ""
    kw_in_first = any(k and k in first for k in keywords)
    checks.append(_check("first_para", "첫 문단에 핵심 키워드", "있음" if kw_in_first else "없음", "있음", kw_in_first or not keywords,
                         "핵심 키워드(%s)를 첫 문단 안에 넣을 것" % ", ".join(keywords[:3])))

    # 2) 키워드 밀도(단어 단위, 1,000자당)
    tokens = []
    for k in keywords[:2]:
        for t in k.split():
            if len(t) >= 2 and t not in tokens:
                tokens.append(t)
    if tokens and plain_len:
        dens = [text.count(t) * 1000 / plain_len for t in tokens]
        avg = sum(dens) / len(dens)
        total_mentions = sum(text.count(k) for k in keywords if k) * 1000 / plain_len
        ok = 1.5 <= avg <= 9.0 and total_mentions <= 25
        checks.append(_check("kw_density", "핵심 키워드 밀도(1,000자당)", f"{avg:.1f}회", "1.5~9회", ok,
                             "핵심 키워드 사용이 %s. 1,000자당 3~6회 수준으로 자연스럽게 조절할 것" % ("부족" if avg < 1.5 else "과다")))

    # 3) 문장 길이 변화
    if sents:
        lens = [len(s) for s in sents]
        mean, sd = st.mean(lens), st.pstdev(lens)
        short = sum(l < 25 for l in lens) / len(lens)
        # 원본 3건: 평균 46~53자, 편차 12~15, 짧은 문장 0~4%. 원본 수준은 통과하고 그보다 단조로우면 주의.
        ok = 28 <= mean <= 60 and sd >= 12
        checks.append(_check("sent_len", "문장 길이 변화", f"평균 {mean:.0f}자 · 편차 {sd:.1f} · 짧은 문장 {short:.0%}",
                             "평균 28~60 · 편차 12 이상", ok,
                             "문장 길이가 균일함. 20자 안팎의 짧은 문장을 20%쯤 섞고 긴 문장은 줄일 것"))

    # 4) 종결어미 / 1인칭
    if sents:
        ends = [_ending(s) for s in sents]
        formal = ends.count("formal") / len(ends)
        casual = (ends.count("polite") + ends.count("colloquial")) / len(ends)
        first_p = sum(bool(FIRST_PERSON_RE.match(s)) for s in sents) / len(sents)
        if kind == "food":
            checks.append(_check("endings", "말투 섞임(합니다체 / 해요·구어)", f"{formal:.0%} / {casual:.0%}", "합니다체 30~70%", 0.30 <= formal <= 0.70 and casual >= 0.20,
                                 "합니다체를 약 50%, 해요체와 구어 어미(~더라고요, ~거든요, ~잖아요)를 약 50% 섞을 것"))
            checks.append(_check("first_person", "'저는'으로 시작하는 문장", f"{first_p:.0%}", "35% 이하", first_p <= 0.35,
                                 "'저는/저도'로 시작하는 문장을 25% 이하로 줄일 것"))
        else:
            checks.append(_check("endings", "말투(합니다체 비율)", f"{formal:.0%}", "85% 이상", formal >= 0.85,
                                 "정보글은 합니다체로 통일할 것"))

    # 5) 범용 표현
    if plain_len:
        gen = sum(text.count(w) for w in GENERIC_WORDS) * 1000 / plain_len
        checks.append(_check("generic", "범용 표현(편안·무난·부담 등)", f"{gen:.1f}회", "1,000자당 7회 이하", gen <= 7,
                             "편안·무난·자연스럽·부담·좋았 같은 범용 표현을 구체적 사실로 바꿀 것"))

    # 6) 중복 문장
    toks = [set(re.findall(r"[가-힣A-Za-z0-9]+", s)) for s in sents]
    dup = sum(1 for i, j in itertools.combinations(range(len(sents)), 2)
              if len(toks[i]) >= 5 and len(toks[j]) >= 5 and len(toks[i] & toks[j]) / len(toks[i] | toks[j]) >= 0.55)
    checks.append(_check("dup", "비슷한 문장 반복", f"{dup}쌍", "0쌍", dup == 0, "같은 내용을 다른 말로 반복한 문장을 하나로 합칠 것"))

    # 7) 해시태그
    n_tags = len(re.findall(r"#[^\s#]+", tags))
    uniq = len(set(re.findall(r"#[^\s#]+", tags)))
    checks.append(_check("hashtags", "해시태그 개수", f"{n_tags}개", "28~30개(중복 없음)", 28 <= n_tags <= 30 and uniq == n_tags,
                         "해시태그를 28~30개, 중복 없이 맞출 것"))

    # 8) 분량
    lo, hi = (1700, 2500) if kind == "food" else (2000, 3200)
    n = count_chars(body)
    checks.append(_check("length", "분량(공백 제외)", f"{n:,}자", f"{lo:,}~{hi:,}자", lo <= n <= hi,
                         "분량을 %s~%s자로 맞출 것(현재 %s자)" % (f"{lo:,}", f"{hi:,}", f"{n:,}")))

    # 9) 메모 반영(휴리스틱)
    if memo and memo.strip():
        cov, n_tok = _memo_coverage(memo, strip_tags(body))
        checks.append(_check("memo", "메모 내용 반영(추정)", f"{cov:.0%} ({n_tok}개 단어 기준)", "40% 이상", cov >= 0.4,
                             "작성자 메모의 구체 내용(메뉴, 가격, 감정)이 본문에 더 반영되게 할 것"))

    # 10) 발행 전 확인 필요 표시: AI가 지어내지 않고 남긴 자리. 다시 쓰기로 해결할 수 없어 직접 확인해야 하므로 advice 는 비움
    todo = len(re.findall(r"\[확인 필요[^\]]*\]", strip_tags(body)))
    checks.append(_check("todo", "발행 전 확인 필요 표시", f"{todo}곳", "0곳 (본문에서 직접 확인하고 지우기)", todo == 0, ""))

    issues = [c["advice"] for c in checks if not c["ok"] and c["advice"]]
    return {"checks": checks, "issues": issues, "ok_count": sum(c["ok"] for c in checks), "total": len(checks), "headings": len(heads)}
