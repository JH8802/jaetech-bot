import anthropic
from blog_style_guide import STYLE_GUIDE
from blog_utils import extract_text
from dotenv import load_dotenv
import os
import random

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY:
    raise ValueError("❌ .env 파일에 ANTHROPIC_API_KEY가 없습니다.")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# 매번 이 중 하나를 무작위로 지정 — "요즘 ~보면 ~가 많이 보인다"류
# 트렌드 관찰형 오프닝으로 매번 수렴하는 걸 막기 위함 (실사용 중 발견된 패턴)
OPENING_STYLES = [
    "구체적인 질문 하나를 툭 던지며 시작 (예: '~가 진짜 효과가 있을까?')",
    "최근 겪은 구체적인 장면·상황 하나를 묘사하며 시작 (예: 특정 문의/사례 하나)",
    "저자의 단정적인 주장이나 의견을 먼저 던지고 시작 (예: '나는 ~라고 본다')",
    "숫자나 구체적 수치를 먼저 제시하며 시작",
    "흔한 오해나 잘못된 통념을 하나 짚으며 시작 (예: '다들 ~라고 알고 있는데')",
]

# 플랫폼별로 실제로 다르게 써야 하는 이유가 있는 부분만 반영.
# (네이버: 개인 서사·체류시간이 C-Rank/D.I.A에 중요. 워드프레스: 구조화된
#  헤딩이 실제 HTML 제목 태그로 변환돼 검색엔진이 직접 읽음. 티스토리는
#  네이버와 비슷한 개인 블로그 톤이되, 구글에도 크롤링되는 편이라 그 중간.)
PLATFORM_STYLE_HINTS = {
    "네이버 블로그": (
        "이 글은 네이버 블로그용이야. 개인적인 경험과 의견 중심의 대화체로,"
        " 소제목은 2~3개로 최소화하고 자연스러운 흐름을 우선해."
        " 사진 제안은 2~3개 정도 적극적으로 넣어줘"
        "(네이버는 이미지와 체류시간을 중요한 품질 신호로 봄)."
    ),
    "티스토리": (
        "이 글은 티스토리용이야. 네이버보다 정보 밀도를 조금 더 높이고,"
        " 소제목을 3~4개로 좀 더 명확하게 구분해줘. 개인 블로그 톤은 유지하되,"
        " 검색엔진(구글)에도 크롤링된다는 걸 염두에 둬."
    ),
    "워드프레스": (
        "이 글은 워드프레스용이야. 소제목 3~5개로 명확하게 구조화하고,"
        " 각 소제목이 검색 의도에 바로 답하는 형태로 써줘. 개인 서사보다"
        " 정보·가치 전달을 우선해. 소제목이 실제 HTML 제목 태그(H2/H3)로"
        " 변환된다는 걸 염두에 두고 논리적 순서로 배치해."
    ),
}


def draft_post(topic, key_points, personal_take="", platform="네이버 블로그"):
    """
    블로그 글 초안을 생성한다.

    topic: 글 주제 (한 줄)
    key_points: 실제 사실/숫자/경험 리스트 (list[str]) — 본인이 직접 채워야 함.
                AI가 지어내지 않도록 여기 없는 내용은 쓰지 않는다.
    personal_take: 저자의 의견/판단 (선택, 없으면 사실 전달 위주로 작성)
    platform: "네이버 블로그" / "티스토리" / "워드프레스" — 톤·소제목 밀도·
              사진 제안 개수가 이에 맞춰 달라진다.
    """
    if not key_points:
        raise ValueError("key_points가 비어 있습니다. 구체적 사실/숫자/경험을 최소 1개 이상 넣어주세요.")

    points_text = "\n".join(f"- {p}" for p in key_points)
    opening_style = random.choice(OPENING_STYLES)
    style_hint = PLATFORM_STYLE_HINTS.get(platform, PLATFORM_STYLE_HINTS["네이버 블로그"])

    prompt = f"""아래 정보로 블로그 글 초안을 써줘.

주제: {topic}

제공된 사실/숫자/경험 (이것만 사용하고, 새로 지어내지 마):
{points_text}

저자의 의견/입장: {personal_take or "(별도 입력 없음 — 사실 전달 위주로 작성)"}

플랫폼: {style_hint}

분량: 1500~2000자 내외 (제목·카테고리·메타설명·태그는 별도)
형식: 마크다운 기호(#, * 등)는 쓰지 마. 아래 순서를 반드시 지켜줘:

1. 맨 첫 줄에 [제목] 검색으로 찾아올 만한 핵심어를 자연스럽게 포함한 제목.
   20~30자 내외, 낚시성 과장 문구 금지, 키워드를 억지로 반복하지 말고
   한 번 명확하게 넣어줘.
2. 그다음 줄에 [카테고리] 이 글에 어울리는 블로그 카테고리명 1개
   (예: 건강기능식품, 재테크/투자 등 — 너무 잘게 쪼개지 않은 상식적인 수준).
3. 그다음 줄에 [메타설명] 검색결과 스니펫에 쓸 요약 1~2문장, 120~155자
   내외. 제목이랑 내용이 겹치지 않게, 클릭하고 싶어지게 핵심만.
4. 본문 — 첫 문단에 핵심 주제(키워드)가 자연스럽게 드러나야 해
   (검색엔진이 이 글이 뭘 다루는지 바로 알 수 있게. 단, 키워드를
   부자연스럽게 욱여넣지는 마).
   도입부 스타일: {opening_style}
   "요즘 홈쇼핑을 보면/둘러보면 ~가 많이 보인다" 식의 트렌드 관찰형
   오프닝은 이미 여러 번 써서 패턴이 됐으니 이번엔 절대 쓰지 마.
   - 소제목이 들어가는 줄은 맨 앞에 [소제목]을 붙여줘
     (예: [소제목] 균주명 없는 표시, 뭐가 문제인가). 개수는 위 "플랫폼"
     지침에 나온 개수를 따르고, 자연스러운 자리에만.
   - 사진/그래프/지도를 넣으면 좋을 자리에는 그 지점에 독립된 줄로
     아래처럼 제안해줘:
     [사진 제안] 어떤 사진이 좋을지 짧은 설명 / ALT: "자연스러운 대체 텍스트"
     [그래프 제안] 어떤 데이터를 시각화하면 좋을지 / ALT: "자연스러운 대체 텍스트"
     [지도 제안] 어떤 장소/위치가 좋을지 / ALT: "자연스러운 대체 텍스트"
     실제로 어울리는 자리에만 넣고, 없으면 억지로 만들지 마. [그래프 제안]은
     위에 제공된 숫자가 있을 때만 하고, 없는 데이터를 지어내지 마.
     ALT 텍스트는 이미지에 실제로 뭐가 보이는지 설명하는 식으로 쓰고,
     키워드 나열하지 마.
5. 맨 마지막 줄에 [태그] 관련 키워드 3~5개를 쉼표로 구분해서
   (# 기호 없이, 예: 유산균, 건강기능식품, 표시광고)"""

    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
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
