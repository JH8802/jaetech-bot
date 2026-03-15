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
# 1회 실행당 최대 API 호출 횟수 (이 숫자를 넘으면 더 이상 API 호출 안 함)
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


def is_important(channel, text):
    if not is_valid_text(text):
        return False

    if not check_api_limit():
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
        count_api_call()
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

            # JSON 파싱 (```json 감싸기 제거)
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
        count_api_call()
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
