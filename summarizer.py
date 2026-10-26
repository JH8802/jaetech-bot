import anthropic
from config import SECURITIES
from dotenv import load_dotenv
import os
import json
import re

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

# ========== 비용 안전장치 ==========
MAX_API_CALLS_PER_RUN = 200
api_call_count = 0


def reset_api_counter():
    global api_call_count
    api_call_count = 0


def check_api_limit():
    global api_call_count
    if api_call_count >= MAX_API_CALLS_PER_RUN:
        print(f"⚠️ API 호출 한도 도달 ({MAX_API_CALLS_PER_RUN}회). 남은 메시지는 건너뜁니다.")
        return False
    return True


def count_api_call():
    global api_call_count
    api_call_count += 1
# ================================


def is_valid_text(text):
    if not text or len(text.strip()) < 15:
        return False
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    non_tag_lines = [l for l in lines if not l.startswith('#')]
    if len(non_tag_lines) == 0:
        return False
    return True


def select_important(messages):
    """
    채널 성격별로 선별 기준을 다르게 적용.
    - 증권사 채널: 수치/공시 기반 엄격한 기준
    - 개인 투자자 채널: 인사이트 중심 완화된 기준
    """
    BATCH_SIZE = 20
    selected = []

    valid_messages = [msg for msg in messages if is_valid_text(msg["text"])]
    print(f"📋 유효 메시지: {len(messages)}개 중 {len(valid_messages)}개")

    # 증권사 채널과 개인 채널 분리
    securities_messages = [msg for msg in valid_messages if msg["channel"] in SECURITIES]
    personal_messages = [msg for msg in valid_messages if msg["channel"] not in SECURITIES]

    # 증권사 채널 선별 (엄격한 기준)
    for i in range(0, len(securities_messages), BATCH_SIZE):
        batch = securities_messages[i:i + BATCH_SIZE]
        if not check_api_limit():
            break
        if len(batch) <= 2:
            selected.extend(batch)
            continue

        numbered_list = ""
        for idx, msg in enumerate(batch):
            text_preview = msg["text"][:300]
            numbered_list += f"\n[{idx}] 채널: {msg['channel']}\n내용: {text_preview}\n"

        prompt = f"""아래는 증권사 리서치 채널에서 수집한 메시지 {len(batch)}개야.

선택 조건 (전부 충족해야 함):
✅ 실적 발표, 정책 변화, 금리 결정, 대형 M&A 등 시장에 즉각적인 영향을 주는 뉴스
✅ 구체적인 수치(%, 조원, YoY, QoQ 등)가 반드시 포함된 분석
✅ 공시, 증권사 리포트, 정부 발표 등 출처가 명확한 정보
✅ 같은 주제가 여러 개 있으면 가장 구체적인 1개만 선택

제외 대상:
❌ 수치 없이 의견/전망만 있는 메시지
❌ 광고, 홍보, 인사, 일상 메시지
❌ 중복 주제

조건을 충족하는 메시지가 없으면 빈 배열을 반환해.
반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"selected": [0, 3, 7]}}

메시지 목록:
{numbered_list}"""

        try:
            count_api_call()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            result = message.content[0].text.strip()
            result = result.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(result)
            selected_indices = parsed.get("selected", [])

            batch_selected = []
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(batch):
                    batch_selected.append(batch[idx])

            selected.extend(batch_selected)
            print(f"🔍 선별(증권사): {len(batch)}개 중 {len(batch_selected)}개 채택")

        except Exception as e:
            print(f"❌ 선별 API 오류: {e} → 이 배치에서 앞 2개만 유지")
            selected.extend(batch[:2])

    # 개인 투자자 채널 선별 (완화된 기준)
    for i in range(0, len(personal_messages), BATCH_SIZE):
        batch = personal_messages[i:i + BATCH_SIZE]
        if not check_api_limit():
            break
        if len(batch) <= 2:
            selected.extend(batch)
            continue

        numbered_list = ""
        for idx, msg in enumerate(batch):
            text_preview = msg["text"][:300]
            numbered_list += f"\n[{idx}] 채널: {msg['channel']}\n내용: {text_preview}\n"

        prompt = f"""아래는 개인 투자자/애널리스트 채널에서 수집한 메시지 {len(batch)}개야.

선택 조건 (하나 이상 충족하면 됨):
✅ 시장 흐름, 종목, 섹터에 대한 명확한 인사이트나 분석이 있는 것
✅ 구체적인 수치나 데이터가 포함된 것 (있으면 우선순위)
✅ 투자자 관점에서 참고할 만한 새로운 시각이나 정보
✅ 특정 종목/섹터의 이슈, 모멘텀, 리스크를 언급한 것

제외 대상:
❌ 광고, 홍보, 안부 인사, 일상 메시지
❌ 근거 없는 루머, 카더라 정보
❌ "좋아 보인다", "관심 있다" 같은 내용 없는 단순 감상
❌ 이미 다른 메시지에서 다룬 주제의 반복

조건을 충족하는 메시지가 없으면 빈 배열을 반환해.
반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"selected": [0, 3, 7]}}

메시지 목록:
{numbered_list}"""

        try:
            count_api_call()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            result = message.content[0].text.strip()
            result = result.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(result)
            selected_indices = parsed.get("selected", [])

            batch_selected = []
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(batch):
                    batch_selected.append(batch[idx])

            selected.extend(batch_selected)
            print(f"🔍 선별(개인): {len(batch)}개 중 {len(batch_selected)}개 채택")

        except Exception as e:
            print(f"❌ 선별 API 오류: {e} → 이 배치에서 앞 3개만 유지")
            selected.extend(batch[:3])

    return selected


def summarize(channel, text):
    if not is_valid_text(text):
        return None

    if not check_api_limit():
        return None

    prompt = f"""아래는 텔레그램 재테크 채널 '{channel}'에서 가져온 글이야.
아래 형식으로 간결하게 요약해줘.
만약 링크만 있거나 요약할 내용이 없으면 반드시 "SKIP" 이라고만 답해줘.

📌 [핵심 제목 한 줄]

📝 내용:
- 구체적인 숫자와 수치를 포함해서 2줄로 요약

💡 투자 포인트:
- 투자자 관점에서 핵심 1~2줄

#해시태그 (관련 종목명, 산업, 키워드를 2~4개, 띄어쓰기 없이)

원문:
{text}"""

    try:
        count_api_call()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text
    except Exception as e:
        print(f"❌ 요약 API 오류: {e}")
        return None

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


def summarize_for_threads(channel, text):
    """텔레그램 발행용이 아니라 쓰레드(Threads) SNS 게시용 초안을 만든다."""
    if not is_valid_text(text):
        return None

    if not check_api_limit():
        return None

    prompt = f"""아래는 텔레그램 재테크 채널 '{channel}'에서 가져온 글이야.
이걸 개인 SNS(쓰레드) 게시글용으로 다시 써줘.

글은 아래 순서로 전개해줘. 이 순서는 네가 참고하는 설계도일 뿐이야.
결과 글에는 "1줄", "2~4줄", "후킹", "흐름", "반전", "내 판단", "근거", "마무리" 같은
번호나 단계 이름을 절대 쓰지 말고, 사람이 직접 쓴 SNS 글처럼 자연스럽게 이어서 써줘.
각 단계는 줄바꿈으로만 구분해.

(1) 후킹: 숫자, 반전, 또는 질문으로 시작해서 스크롤을 멈추게
(2) 흐름: 짧은 문장 + 화살표(→)로 원인에서 결과까지 2~3줄로 나눠서 단계별로 설명
(3) 반전: "근데 의외로 ○○" 식으로 예상 밖의 포인트 짚기
(4) 내 판단: "나는 ○○로 봄" — 이 소식이 시장/산업 구조에 어떤 의미인지
    해석하는 수준으로만 쓰고, "사라/팔아라/지금 들어가라" 같은 지시형 톤은 절대 금지
(5) 근거: "왜냐면 ○○" 한 줄로 (4)의 판단을 뒷받침
(6) 마무리: 답글을 유도하는 가벼운 A/B 선택형 질문, 또는 저장하고 싶어지는
    한 줄 단언 중 더 어울리는 쪽으로 (논쟁·편 가르기를 유도하는 자극적 질문은 절대 금지)

전체 규칙:
- 반말 섞인 캐주얼한 톤 ("~임", "~함", "~인 듯" 같은 말투)
- 특정 종목을 "사라/팔아라" 식으로 추천하는 표현은 절대 쓰지 말 것
  (내 판단도 시장 해석 수준에 머물러야 하고, 투자 지시가 되면 안 됨)
- 본문이 끝난 다음 줄에 "⚠️ 투자 참고용이며 투자 권유가 아닙니다" 그대로 넣기
- 마지막 줄에 해시태그 2~4개 (원문 내용 기반), 그리고 맨 마지막 해시태그 뒤에
  한 칸 띄고 이 소식이 언급된 종목/섹터에 (호재) 또는 (악재) 또는 (중립) 중
  하나를 붙이기 (예: #반도체 (호재))

만약 링크만 있거나 요약할 내용이 없으면 반드시 "SKIP" 이라고만 답해줘.

원문:
{text}"""

    try:
        count_api_call()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text.strip()
    except Exception as e:
        print(f"❌ 쓰레드 초안 API 오류: {e}")
        return None

    # 토큰 한도에 걸려 문장이 중간에 잘린 경우 (해시태그/디스클레이머 누락
    # 등으로 이어짐) — 어설프게 자른 글 보내느니 이번 타임슬롯은 건너뜀
    if message.stop_reason == "max_tokens":
        print("⚠️ 쓰레드 초안이 길이 제한으로 중간에 잘림 → 이번 건 건너뜀")
        return None

    if not result or len(result.strip()) < 10:
        return None
    if "SKIP" in result.strip().upper()[:10]:
        return None
    for keyword in INVALID_KEYWORDS:
        if keyword in result:
            return None

    # 프롬프트의 구조 라벨("1줄 -", "2~4줄 -", "(3)" 등)이 글에 섞여 나오면 제거
    result = re.sub(r"^[ \t]*\d+(?:~\d+)?줄[ \t]*[-–:][ \t]*", "", result, flags=re.MULTILINE)
    result = re.sub(r"^[ \t]*\(\d\)[ \t]*", "", result, flags=re.MULTILINE)

    return result
