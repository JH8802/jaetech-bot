import anthropic
from blog_style_guide import STYLE_GUIDE
from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY:
    raise ValueError("❌ .env 파일에 ANTHROPIC_API_KEY가 없습니다.")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def draft_post(topic, key_points, personal_take=""):
    """
    블로그 글 초안을 생성한다.

    topic: 글 주제 (한 줄)
    key_points: 실제 사실/숫자/경험 리스트 (list[str]) — 본인이 직접 채워야 함.
                AI가 지어내지 않도록 여기 없는 내용은 쓰지 않는다.
    personal_take: 저자의 의견/판단 (선택, 없으면 사실 전달 위주로 작성)
    """
    if not key_points:
        raise ValueError("key_points가 비어 있습니다. 구체적 사실/숫자/경험을 최소 1개 이상 넣어주세요.")

    points_text = "\n".join(f"- {p}" for p in key_points)

    prompt = f"""아래 정보로 블로그 글 초안을 써줘.

주제: {topic}

제공된 사실/숫자/경험 (이것만 사용하고, 새로 지어내지 마):
{points_text}

저자의 의견/입장: {personal_take or "(별도 입력 없음 — 사실 전달 위주로 작성)"}

분량: 1500~2000자 내외
형식: 마크다운 기호(#, * 등) 없이 일반 텍스트로, 소제목은 최소화"""

    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=STYLE_GUIDE,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()
