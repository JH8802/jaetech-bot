import anthropic
from config import SECURITIES
from dotenv import load_dotenv
import os
import json

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
MAX_API_CALLS_PER_RUN = 150
api_call_count = 0


def reset_api_counter():
    """매 실행(job) 시작 시 카운터 초기화"""
    global api_call_count
    api_call_count = 0


def check_api_limit():
    """API 호출 한도 초과 여부 확인"""
    global api_call_count
    if api_call_count >= MAX_API_CALLS_PER_RUN:
        print(f"⚠️ API 호출 한도 도달 ({MAX_API_CALLS_PER_RUN}회). 남은 메시지는 건너뜁니다.")
        return False
    return True


def count_api_call():
    """API 호출 1회 기록"""
    global api_call_count
    api_call_count += 1
# ================================


def is_valid_text(text):
    if not text or len(text.strip()) < 20:
        return False
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    non_link_lines = [l for l in lines if not l.startswith('http') and not l.startswith('#')]
    if len(non_link_lines) == 0:
        return False
    return True


def select_important(messages):
    """
    중요도 판단 + 중복 제거를 한번에 처리.
    20개씩 묶어서 AI에게 "중요하면서 겹치지 않는 최고 3~5개만 골라줘" 요청.
    API 호출 1회로 두 가지를 동시에 처리하여 비용 절감.
    """
    BATCH_SIZE = 20
    selected = []

    # 텍스트 유효성 먼저 필터링 (API 호출 불필요)
    valid_messages = [msg for msg in messages if is_valid_text(msg["text"])]
    print(f"📋 유효 메시지: {len(messages)}개 중 {len(valid_messages)}개")

    for i in range(0, len(valid_messages), BATCH_SIZE):
        batch = valid_messages[i:i + BATCH_SIZE]

        if not check_api_limit():
            break

        if len(batch) <= 2:
            selected.extend(batch)
            continue

        # 각 메시지에 번호를 매겨서 AI에게 전달
        numbered_list = ""
        for idx, msg in enumerate(batch):
            text_preview = msg["text"][:300]
            numbered_list += f"\n[{idx}] 채널: {msg['channel']}\n내용: {text_preview}\n"

        prompt = f"""
아래는 텔레그램 재테크 채널들에서 수집한 메시지 {len(batch)}개야.

너의 역할: 투자자에게 가장 가치 있는 메시지를 1~3개만 엄선해줘. 정말 중요한 것만 골라.

선별 기준:
1. 투자자에게 중요한 정보만 선택 (시장 동향, 실적 발표, 정책 변화, 투자 기회 등)
2. 단순 광고, 안부 인사, 의미없는 링크, 해시태그만 있는 것은 제외
3. 같은 주제가 여러 개 있으면, 가장 구체적이고 수치가 많은 1개만 선택
4. 증권사 리서치가 개인 채널보다 우선

반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
중요한 메시지가 없으면 빈 배열을 반환해.
{{"selected": [0, 3, 7]}}

메시지 목록:
{numbered_list}
"""
        try:
            count_api_call()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )
            result = message.content[0].text.strip()

            # JSON 파싱
            result = result.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(result)
            selected_indices = parsed.get("selected", [])

            # 유효한 인덱스만 필터링
            batch_selected = []
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(batch):
                    batch_selected.append(batch[idx])

            selected.extend(batch_selected)
            print(f"🔍 선별: {len(batch)}개 중 {len(batch_selected)}개 채택")

        except Exception as e:
            print(f"❌ 선별 API 오류: {e} → 이 배치에서 앞 3개만 유지")
            selected.extend(batch[:3])

    return selected


def summarize(channel, text):
    if not is_valid_text(text):
        return None

    if not check_api_limit():
        return None

    prompt = f"""
아래는 텔레그램 재테크 채널 '{channel}'에서 가져온 글이야.
아래 형식으로 간결하게 요약해줘.
만약 링크만 있거나 요약할 내용이 없으면 반드시 "SKIP" 이라고만 답해줘.

📌 [핵심 제목 한 줄]

📝 내용:
- 구체적인 숫자와 수치를 포함해서 2줄로 요약

💡 투자 포인트:
- 투자자 관점에서 핵심 1~2줄

원문:
{text}
"""
    try:
        count_api_call()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
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
