import anthropic
from dotenv import load_dotenv
import os
import json

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY:
    raise ValueError("❌ .env 파일에 ANTHROPIC_API_KEY가 없습니다.")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# 한 번이라도 나오면 바로 지적하는 표현
HARD_BAN = [
    "안녕하세요", "여러분 안녕", "알아보겠습니다", "알아보았습니다",
    "도움이 되셨", "다음에도 유용한", "결론적으로", "정리하자면",
]

# 반복될 때만 문제로 보는 표현 (한두 번은 자연스러움)
REPEAT_WATCH = ["또한", "특히", "이처럼"]
REPEAT_THRESHOLD = 2


def scan_cliches(draft):
    """규칙 기반 점검 — API 호출 없이 즉시, 무료로 실행됨."""
    issues = []
    for phrase in HARD_BAN:
        if phrase in draft:
            issues.append(f"금지 표현 발견: '{phrase}'")
    for phrase in REPEAT_WATCH:
        count = draft.count(phrase)
        if count > REPEAT_THRESHOLD:
            issues.append(f"'{phrase}' {count}번 반복 사용 (2번 이하로 줄이기)")
    return issues


def scan_structure(draft):
    """규칙 기반 구조 점검 — 가독성 + 사진/그래프/지도 제안 존재 여부."""
    issues = []

    paragraphs = [p for p in draft.split("\n\n") if p.strip() and not p.strip().startswith("[")]
    long_paragraphs = [p for p in paragraphs if len(p) > 400]
    if long_paragraphs:
        issues.append(f"긴 문단 {len(long_paragraphs)}개 (400자 초과 — 나누면 가독성 좋아짐)")

    if len(draft) < 1000:
        issues.append(f"본문이 짧음 ({len(draft)}자) — 짧은 글은 저품질 신호로 취급될 수 있음")

    visual_markers = sum(draft.count(tag) for tag in ("[사진 제안]", "[그래프 제안]", "[지도 제안]"))
    if visual_markers == 0:
        issues.append("사진/그래프/지도 제안이 하나도 없음 — 이미지 없는 글은 불리하다고 알려져 있음")

    return issues


def review_draft(draft):
    """AI 기반 점검 (문장 리듬 / 저자 의견 / 사실 구체성) — Haiku로 저비용 호출."""
    prompt = f"""아래는 블로그 초안이야. 다음 3개 기준으로만 점검해줘.
문제 되는 부분은 원문 문장을 그대로 짧게 인용해서 지적하고,
문제 없으면 정확히 "없음"이라고만 답해.

1. sentence_rhythm: 문장 길이가 단조로운가 (대부분 비슷한 길이인가)
2. opinion: 저자의 의견/판단 없이 중립적 나열에 그치는가
3. specificity: 사실/사례가 뭉뚱그려져 있고 구체성이 떨어지는가

반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"sentence_rhythm": "...", "opinion": "...", "specificity": "..."}}

초안:
{draft}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text.strip()
        result = result.replace("```json", "").replace("```", "").strip()
        return json.loads(result)
    except Exception as e:
        print(f"⚠️ AI 점검 실패 (건너뜀): {e}")
        return {}
