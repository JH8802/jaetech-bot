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
# 1회 실행당 최대 API 호출 횟수
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


def batch_filter_important(messages):
    """
    메시지를 10개씩 묶어서 AI에게 한번에 중요도 판단을 요청.
    1개씩 보내는 것보다 API 호출이 10분의 1로 줄어듦.
    """
    BATCH_SIZE = 10
    important_messages = []

    for i in range(0, len(messages), BATCH_SIZE):
        batch = messages[i:i + BATCH_SIZE]

        # 텍스트 유효성 먼저 필터링 (API 호출 불필요)
        valid_batch = []
        for msg in batch:
            if is_valid_text(msg["text"]):
                valid_batch.append(msg)

        if len(valid_batch) == 0:
            continue

        if not check_api_limit():
            break

        # 각 메시지에 번호를 매겨서 AI에게 전달
        numbered_list = ""
        for idx, msg in enumerate(valid_batch):
            text_preview = msg["text"][:300]
            numbered_list += f"\n[{idx}] 채널: {msg['channel']}\n내용: {text_preview}\n"

        prompt = f"""
아래는 텔레그램 재테크 채널들에서 수집한 메시지 {len(valid_batch)}개야.
각 메시지가 주식/ETF/부동산/암호화폐 투자자에게 중요한 정보인지 판단해줘.

중요한 경우: 시장 동향, 실적 발표, 정책 변화, 투자 기회, 구체적 수치가 있는 분석 등
중요하지 않은 경우: 단순 광고, 안부 인사, 의미없는 링크, 해시태그만 있는 경우, 짧은 코멘트

중요하다고 판단되는 메시지의 번호만 골라줘.
반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
중요한 메시지가 없으면 빈 배열을 반환해.
{{"important": [0, 3, 7]}}

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
            selected_indices = parsed.get("important", [])

            # 유효한 인덱스만 필터링
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(valid_batch):
                    important_messages.append(valid_batch[idx])

            batch_important = len([idx for idx in selected_indices if isinstance(idx, int) and 0 <= idx < len(valid_batch)])
            print(f"🔍 중요도 판단: {len(valid_batch)}개 중 {batch_important}개 중요")

        except Exception as e:
            print(f"❌ 중요도 판단 API 오류: {e} → 이 배치는 전체 중요로 처리")
            important_messages.extend(valid_batch)

    return important_messages


def deduplicate(messages):
    """
    중복 주제 메시지를 제거하고, 각 주제별로 가장 품질 좋은 메시지 1개만 선별.
    최대 2회까지만 수행하여 무한 반복 방지.
    """
    if len(messages) <= 1:
        return messages

    BATCH_SIZE = 20

    # --- 1차 중복 제거 ---
    selected = _run_dedup_batch(messages, BATCH_SIZE)
    print(f"✨ 1차 중복 제거 완료: {len(messages)}개 → {len(selected)}개")

    # 배치가 여러 개였을 경우, 배치 간 중복 제거를 위해 1회만 더 수행
    if len(messages) > BATCH_SIZE and len(selected) > BATCH_SIZE:
        before = len(selected)
        selected = _run_dedup_batch(selected, BATCH_SIZE)
        print(f"✨ 2차 중복 제거 완료: {before}개 → {len(selected)}개")

    # 여기서 끝. 더 이상 반복하지 않음.
    return selected


def _run_dedup_batch(messages, batch_size):
    """20개씩 묶어서 중복 제거 1회 수행"""
    selected = []

    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]

        if len(batch) <= 1:
            selected.extend(batch)
            continue

        if not check_api_limit():
            selected.extend(batch)
            continue

        # 각 메시지에 번호를 매겨서 AI에게 전달
        numbered_list = ""
        for idx, msg in enumerate(batch):
            text_preview = msg["text"][:500]
            numbered_list += f"\n[{idx}] 채널: {msg['channel']}\n내용: {text_preview}\n"

        prompt = f"""
아래는 텔레그램 재테크 채널들에서 수집한 메시지 {len(batch)}개야.
같은 주제를 다루는 메시지들이 있을 수 있어.

너의 역할:
1. 같은 주제(같은 기업 실적, 같은 정책, 같은 시장 이슈 등)를 다루는 메시지끼리 그룹으로 묶어.
2. 각 그룹에서 가장 품질이 좋은 메시지 1개만 선택해. 품질 기준: 구체적 수치가 많은 것, 분석이 깊은 것, 신뢰도가 높은 것 (증권사 리서치 > 개인 채널).
3. 중복이 아닌 독립적인 주제의 메시지는 그대로 선택해.

반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"selected": [0, 3, 7]}}

선택된 메시지의 번호(인덱스)만 배열로 넣어줘.

메시지 목록:
{numbered_list}
"""
        try:
            count_api_call()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
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

            # 선별 결과가 비어있으면 원본 유지
            if len(batch_selected) == 0:
                selected.extend(batch)
            else:
                selected.extend(batch_selected)
                removed = len(batch) - len(batch_selected)
                if removed > 0:
                    print(f"🔄 중복 제거: {len(batch)}개 중 {len(batch_selected)}개 선별 ({removed}개 중복 제거)")

        except Exception as e:
            print(f"❌ 중복 제거 API 오류: {e} → 이 배치는 전체 유지")
            selected.extend(batch)

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
            max_tokens=500,
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
