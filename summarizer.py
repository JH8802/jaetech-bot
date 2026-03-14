import anthropic
from config import SECURITIES
from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY:
    raise ValueError("❌ .env 파일에 ANTHROPIC_API_KEY가 없습니다.")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# 요약 불가 키워드
INVALID_KEYWORDS = [
    "죄송하지만", "링크를 클릭할 수 없", "확인할 수 없습니다",
    "본문 텍스트를 직접", "내용을 공유해주시면", "기사 내용을 공유"
]


def is_valid_text(text):
    if not text or len(text.strip()) < 20:
        return False
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    non_link_lines = [l for l in lines if not l.startswith('http') and not l.startswith('#')]
    if len(non_link_lines) == 0:
        return False
    return True


def is_important(channel, text):
    if not is_valid_text(text):
        return False

    prompt = f"""
아래는 텔레그램 재테크 채널 '{channel}'의 메시지야.
이 메시지가 주식/ETF/부동산/암호화폐 투자자에게 중요한 정보인지 판단해줘.

중요한 경우: 시장 동향, 실적 발표, 정책 변화, 투자 기회 등
중요하지 않은 경우: 단순 광고, 안부 인사, 의미없는 링크, 해시태그만 있는 경우

반드시 "YES" 또는 "NO" 중 하나만 대답해줘.

메시지:
{text}
"""
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text.strip().upper()
        return "YES" in result
    except Exception as e:
        print(f"❌ 중요도 판단 API 오류: {e}")
        return False


def summarize(channel, text):
    if not is_valid_text(text):
        return None

    prompt = f"""
아래는 텔레그램 재테크 채널 '{channel}'에서 가져온 글이야.
아래 형식으로 요약해줘.
만약 링크만 있거나 요약할 내용이 없으면 반드시 "SKIP" 이라고만 답해줘.

📌 [핵심 제목 한 줄]

📝 내용:
- 구체적인 숫자와 수치를 포함해서 2~3줄로 요약 (%, YoY, QoQ, 조원 등 구체적 수치 필수)
- 시장 예상치 대비 상회/하회 여부가 있으면 반드시 포함
- 숫자가 없으면 최대한 구체적인 표현으로 작성

💡 투자 포인트:
- 투자자 관점에서 중요한 점 1~2가지

🔍 관련 종목 (참고용):
- 뉴스와 관련된 국내 대표 종목 1~2개와 종목코드 포함 (예: 삼성전자 005930)
- 관련 종목이 없으면 생략

원문:
{text}
"""
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text
    except Exception as e:
        print(f"❌ 요약 API 오류: {e}")
        return None

    # 요약 불가 응답 필터링
    if not result or len(result.strip()) < 10:
        return None
    if "SKIP" in result.strip().upper()[:10]:
        return None
    for keyword in INVALID_KEYWORDS:
        if keyword in result:
            return None

    if channel not in SECURITIES:
        result += f"\n\n🔗 출처: https://t.me/{channel}"
    result += "\n\n⚠️ 본 내용은 투자 참고용이며 투자 권유가 아닙니다."
    return result
