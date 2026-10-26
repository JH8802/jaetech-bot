"""숫자 대조표 — 초안에 나온 숫자가 내가 준 재료(경험 메모·출처·의견·다듬기 메모·직접 입력)
어디에 있는지 확인한다. 재료 어디에도 없는 숫자는 AI가 지어냈거나 잘못 옮긴 것일 수 있다.

API를 쓰지 않는 규칙 기반이라 비용 0원. 한계:
- 숫자만 본다 (기관명·사람 이름 같은 고유명사는 확인하지 않음)
- '1', '2'처럼 흔한 작은 숫자는 재료 어딘가에 거의 항상 있어서 확인됨으로 나올 수 있음
- 단위 환산(예: 35억900만 달러 → 약 5조원)은 재료에 없으면 '확인 필요'로 나옴
"""
import re
from datetime import datetime

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_TAG_RE = re.compile(r"\[[^\]]*\]")


def _norm(num):
    return num.replace(",", "")


def _numbers_in(text):
    return {_norm(m.group(0)) for m in _NUM_RE.finditer(text or "")}


def check_numbers(body, references):
    """body의 숫자마다 references(이름 → 텍스트) 중 어디에 있는지 찾는다.

    반환: [{"number", "context", "found_in": [재료 이름...], "count"}] (본문 등장 순서)
    - 대괄호 안([사진 제안 …], [링크: …] 등)과 대괄호로 시작하는 줄은 건너뜀
    - "2026년 10월 기준"처럼 오늘 날짜로 붙는 기준일은 건너뜀
    """
    ref_numbers = {name: _numbers_in(_norm(text)) for name, text in references.items() if text}
    now = datetime.now()
    today_tokens = {str(now.year), str(now.month)}

    results = {}
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        clean = _TAG_RE.sub(" ", stripped)
        for m in _NUM_RE.finditer(clean):
            num = _norm(m.group(0))
            after = clean[m.end():m.end() + 12]
            if num in today_tokens and "기준" in after:
                continue
            if num in results:
                results[num]["count"] += 1
                continue
            start, end = max(0, m.start() - 18), min(len(clean), m.end() + 18)
            results[num] = {
                "number": m.group(0),
                "context": ("…" if start else "") + clean[start:end] + ("…" if end < len(clean) else ""),
                "found_in": [name for name, nums in ref_numbers.items() if num in nums],
                "count": 1,
            }
    return list(results.values())


def build_references(inputs):
    """세션/저장 파일의 inputs dict에서 대조용 재료 묶음을 만든다."""
    return {
        "경험 메모": "\n".join(inputs.get("key_points", [])),
        "출처": "\n".join(inputs.get("sources", [])),
        "의견": inputs.get("personal_take", ""),
        "다듬기 메모": "\n".join(inputs.get("notes", [])),
        "직접 입력": "\n".join(inputs.get("user_additions", [])),
    }


def unverified(rows):
    return [r for r in rows if not r["found_in"]]


# ─────────────────────────────────────────────
# 원문 문장 복사 검사 (자료로 쓰기 모드) — 저작권·복붙 방지
# ─────────────────────────────────────────────
COPY_NGRAM = 6  # 어절(띄어쓰기 단위) 6개가 연속으로 원문과 같으면 '거의 그대로 옮김'으로 봄


def _words(text):
    return re.findall(r"[0-9A-Za-z가-힣]+", text or "")


def find_copied_sentences(body, raw_texts, n=COPY_NGRAM):
    """본문 문장 중 자료 원문(웹페이지 글)과 어절 n개 이상 연속으로 같은 문장을 찾는다.
    raw_texts: {자료 이름: 원문 글자}. 반환: [{"sentence", "source"}]"""
    shingles = {}
    for name, text in (raw_texts or {}).items():
        words = _words(text)
        for i in range(len(words) - n + 1):
            shingles.setdefault(" ".join(words[i:i + n]), name)
    if not shingles:
        return []

    found = []
    clean = _TAG_RE.sub(" ", body)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", clean):
        words = _words(sentence)
        for i in range(len(words) - n + 1):
            source = shingles.get(" ".join(words[i:i + n]))
            if source:
                found.append({"sentence": sentence.strip()[:120], "source": source})
                break
    return found
