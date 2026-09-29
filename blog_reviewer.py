import anthropic
from blog_utils import extract_text
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

# review_draft()가 반환하는 키 -> 화면에 보여줄 라벨 (blog_write.py, blog_app.py 공용)
AI_REVIEW_LABELS = {
    "sentence_rhythm": "문장 길이 변주",
    "opinion": "저자 의견",
    "specificity": "사실 구체성",
    "differentiation": "차별화(뻔한 내용 여부)",
    "keyword_clarity": "SEO 키워드 명확성",
}


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

    if "[제목]" not in draft:
        issues.append("[제목] 태그가 없음 — 제목 없이 본문만 생성된 것으로 보임")
    if "[태그]" not in draft:
        issues.append("[태그] 태그가 없음 — 발행 시 넣을 키워드 태그가 없음")

    return issues


def review_draft(draft):
    """AI 기반 점검 (문장 리듬 / 저자 의견 / 사실 구체성 / 차별화 / SEO 키워드) — Haiku로 저비용 호출."""
    prompt = f"""아래는 블로그 초안이야. 다음 5개 기준으로만 점검해줘.
문제 되는 부분은 원문 문장을 그대로 짧게 인용해서 지적하고,
문제 없으면 정확히 "없음"이라고만 답해.

1. sentence_rhythm: 문장 길이가 단조로운가 (대부분 비슷한 길이인가)
2. opinion: 저자의 의견/판단 없이 중립적 나열에 그치는가
3. specificity: 사실/사례가 뭉뚱그려져 있고 구체성이 떨어지는가
4. differentiation: 이 주제를 검색하면 어디서나 나올 법한 뻔하고 일반적인
   설명/사례에 그치는가 (직접 겪은 일이나 실무자만 아는 디테일이 아니라
   교과서적/통념적 설명 위주인가). 뻔한 부분이 있으면 그 문장을 인용해서
   지적하고, 이 글만의 구체적 시각·경험이 충분하면 "없음"
5. keyword_clarity: [제목]과 본문 첫 문단만 보고 "이 글이 정확히 무엇에
   대한 글인지" 검색하는 사람 입장에서 바로 알 수 있는가. 제목이나
   도입부가 모호하거나 핵심 키워드 없이 겉돈다면 지적하고, 명확하면 "없음"
   (키워드를 억지로 많이 넣으라는 뜻이 아니라, 명확성 문제만 봐줘)

반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"sentence_rhythm": "...", "opinion": "...", "specificity": "...", "differentiation": "...", "keyword_clarity": "..."}}

초안:
{draft}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        result = extract_text(message).strip()
        result = result.replace("```json", "").replace("```", "").strip()
        return json.loads(result)
    except Exception as e:
        print(f"⚠️ AI 점검 실패 (건너뜀): {e}")
        return {}
