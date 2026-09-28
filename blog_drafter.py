import anthropic
from blog_style_guide import STYLE_GUIDE
from blog_utils import extract_text
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
형식: 마크다운 기호(#, * 등)는 쓰지 마. 대신:
- 소제목이 들어가는 줄은 맨 앞에 [소제목]을 붙여줘
  (예: [소제목] 균주명 없는 표시, 뭐가 문제인가). 소제목은 2~4개, 자연스러운 자리에만.
- 사진/그래프/지도를 넣으면 좋을 자리에는 그 지점에 독립된 줄로 아래처럼 제안해줘:
  [사진 제안] 어떤 사진이 좋을지 짧은 설명 / ALT: "자연스러운 대체 텍스트"
  [그래프 제안] 어떤 데이터를 시각화하면 좋을지 / ALT: "자연스러운 대체 텍스트"
  [지도 제안] 어떤 장소/위치가 좋을지 / ALT: "자연스러운 대체 텍스트"
  실제로 어울리는 자리에만 넣고, 없으면 억지로 만들지 마. [그래프 제안]은
  위에 제공된 숫자가 있을 때만 하고, 없는 데이터를 지어내지 마.
  ALT 텍스트는 이미지에 실제로 뭐가 보이는지 설명하는 식으로 쓰고, 키워드 나열하지 마."""

    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=STYLE_GUIDE,
        messages=[{"role": "user", "content": prompt}]
    )
    return extract_text(message).strip()


def suggest_questions(topic):
    """주제에 맞는 브레인스토밍 질문을 만들어준다 (Haiku, 저비용)."""
    prompt = f"""블로그 주제: {topic}

이 주제로 글을 쓰려는 사람이 자기가 이미 알고 있는 실제 경험/숫자/사례를
떠올릴 수 있도록 돕는 질문을 4~5개 만들어줘. 일반론을 묻지 말고,
그 사람의 구체적인 기억이나 의견을 끄집어내는 질문이어야 해.
그중 최소 1개는 "이 주제에 대해 사람들이 흔히 하는 뻔한 얘기랑, 본인만
다르게 보거나 남들은 잘 모르는 지점이 뭔지" 를 묻는 질문으로 넣어줘 —
이미 다른 글에도 똑같이 나오는 뻔한 내용이 되지 않게 하려는 거야.

한 줄에 질문 하나씩, 번호나 설명 없이 질문 문장만 출력해."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        lines = extract_text(message).strip().split("\n")
        return [line.strip("-• ").strip() for line in lines if line.strip()]
    except Exception as e:
        print(f"⚠️ 질문 생성 실패 (건너뜀): {e}")
        return []
