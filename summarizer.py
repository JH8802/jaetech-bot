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


THREADS_SECTORS = [
    "반도체", "전력망", "소비재", "화장품", "금리", "유가", "식품", "의류",
    "자동차", "바이오", "금융", "엔터", "교육", "기타",
]

IDEAS_MARKER = "[내 한 줄 아이디어]"

# Meta가 랭킹을 낮춘다고 밝힌 '인게이지먼트 베이트'(행동을 요구하는 참여 유도) 패턴.
# 경험을 묻는 일반 질문("체감돼?")은 걸리지 않도록 '요구 동사'와 붙은 경우만 잡는다.
ENGAGEMENT_BAIT_PATTERNS = [
    r"팔로우\s*(?:해|부탁|눌러|좀)",
    r"맞팔",
    r"좋아요[^\n]{0,10}(?:눌러|부탁|꾹|해\s*줘|해주세요)",
    r"하트[^\n]{0,10}(?:눌러|부탁|꾹|알려|해\s*줘|해주세요)",
    r"댓글[^\n]{0,15}(?:알려|남겨|달아|부탁)",
    r"공유[^\n]{0,10}(?:해\s*줘|부탁|해주세요)",
    r"리포스트[^\n]{0,10}(?:해\s*줘|부탁|해주세요)",
    r"구독[^\n]{0,10}(?:눌러|부탁|해\s*줘|해주세요)",
    r"아이디[^\n]{0,10}(?:알려|남겨)",
]


def find_engagement_bait(text):
    """참여 유도 문구가 있으면 해당 부분을, 없으면 None을 돌려준다."""
    for pattern in ENGAGEMENT_BAIT_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def pick_for_threads(candidates, recent_sectors):
    """선별된 후보 중 쓰레드에 올릴 1건을 고른다.
    candidates: [{"channel", "text", "has_image"}], recent_sectors: 최근에 다룬 섹터 목록.
    반환: (후보 인덱스, 섹터명)
    """
    if len(candidates) == 1 or not check_api_limit():
        return 0, "기타"

    numbered_list = ""
    for idx, c in enumerate(candidates):
        image_flag = " [이미지 있음]" if c.get("has_image") else ""
        numbered_list += f"\n[{idx}]{image_flag} 채널: {c['channel']}\n내용: {c['text'][:300]}\n"

    recent = ", ".join(recent_sectors) if recent_sectors else "없음"

    prompt = f"""아래는 오늘 개인 SNS(쓰레드)에 올릴 투자 소식 후보 {len(candidates)}개야. 이 중 1개를 골라줘.

선택 기준 (중요한 순서):
1. 일반 개인투자자도 쉽게 공감하거나 생활 속에서 체감할 수 있는 소식
2. 최근에 다룬 섹터({recent})와 겹치지 않는 섹터 우선
   (단, 다른 후보들이 내용이 너무 빈약하면 겹쳐도 됨)
3. [이미지 있음] 표시가 있는 후보 우선 (실제 차트·표가 붙어 있는 소식)
4. 구체적인 사실이나 숫자가 있는 소식

고른 소식의 섹터는 다음 중 하나로 분류해: {", ".join(THREADS_SECTORS)}

반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"index": 0, "sector": "반도체"}}

후보 목록:
{numbered_list}"""

    try:
        count_api_call()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        index = parsed.get("index", 0)
        sector = parsed.get("sector", "기타")
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            index = 0
        if sector not in THREADS_SECTORS:
            sector = "기타"
        return index, sector
    except Exception as e:
        print(f"❌ 쓰레드 소재 선택 오류: {e} → 첫 번째 후보 사용")
        return 0, "기타"


def summarize_for_threads(channel, text, sector=None):
    """텔레그램 발행용이 아니라 쓰레드(Threads) SNS 게시용 초안을 만든다."""
    if not is_valid_text(text):
        return None

    if not check_api_limit():
        return None

    if sector and sector != "기타":
        tag_rule = f"주제 태그는 #{sector} 로 할 것"
    else:
        tag_rule = "주제 태그는 이 소식의 섹터 이름 하나만 (예: #반도체, #화장품, #금리)"

    prompt = f"""아래는 텔레그램 재테크 채널 '{channel}'에서 가져온 글이야.
이걸 개인 SNS(쓰레드) 게시글용으로 다시 써줘.

[본문 쓰는 법]
본문은 4~5줄로 짧게, 핵심 포인트는 딱 하나만. 각 줄은 줄바꿈으로 구분해.
아래 (1)~(4)는 네가 참고할 설계도일 뿐이야. 결과 글에 번호나 "후킹", "핵심" 같은
단계 이름은 절대 쓰지 말고, 사람이 직접 쓴 SNS 글처럼 자연스럽게 써줘.

(1) 첫 줄: 숫자·반전·질문 중 하나로 스크롤을 멈추게.
    단, 원문에 없는 내용으로 과장하거나 오해를 부르는 낚시성 표현은 금지.
    사실 그대로인데 흥미로운 지점을 짚을 것.
(2) 다음 1~2줄: 왜 그런지 핵심만. 숫자는 꼭 필요한 1~2개만, 화살표(→)는 쓰더라도 한 번만.
(3) 다음 1줄: "나는 ○○로 봄" + 짧은 이유. 시장/산업에 어떤 의미인지 해석하는 수준으로만 쓰고,
    "사라/팔아라/지금 들어가라" 같은 지시형 표현은 절대 금지.
(4) 마지막 1줄: 누구나 자기 경험이나 체감으로 바로 답할 수 있는 쉬운 질문.
    (예: "요즘 마트 가면 이거 체감돼?", "너는 이 소식 듣고 제일 먼저 뭐가 떠올랐어?")
    공부해야 답할 수 있는 분석형 질문, 편 가르기나 분노를 부르는 질문은 금지.

[하지 말 것]
- "좋아요/댓글/팔로우 눌러줘", "하트로 알려줘" 같은 참여 유도 문구
- 원문에 없는 개인 경험, 보유 종목, 매매 내역을 지어내는 것
- 자극적·선동적인 표현, 특정 집단을 비난하는 표현

[형식]
- 말투: 반말 섞인 캐주얼한 톤 ("~임", "~함", "~인 듯")
- 본문 다음 줄에 "⚠️ 투자 참고용이며 투자 권유가 아닙니다" 그대로 넣기
- 그다음 줄에 주제 태그 1개, 한 칸 띄고 (호재) 또는 (악재) 또는 (중립) 중 하나 (예: #반도체 (호재))
  {tag_rule}
- 그다음 줄에 "{IDEAS_MARKER}"라고 쓰고, 그 아래에 글쓴이가 자기 상황에 맞으면
  본문 맨 위에 덧붙일 수 있는 개인적인 한 줄을 "- "로 시작해 2개 제안
  (예: "- (보유 중이라면) 나도 들고 있어서 이 소식은 그냥 못 넘기겠음")

만약 링크만 있거나 요약할 내용이 없으면 반드시 "SKIP" 이라고만 답해줘.

원문:
{text}"""

    retry_note = (
        "\n\n[주의] 방금 쓴 초안에 참여 유도 문구(좋아요·댓글·팔로우·공유 요청 등)가 있었어. "
        "이런 문구 없이 다시 써줘. 마무리는 경험을 묻는 질문으로만."
    )

    result = None
    for attempt in range(2):
        if not check_api_limit():
            return None
        try:
            count_api_call()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=700,
                messages=[{"role": "user", "content": prompt + (retry_note if attempt else "")}]
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

        # Meta가 금지한 인게이지먼트 베이트(참여 유도 문구) 검사 — 1회 재생성 후에도 있으면 폐기
        bait = find_engagement_bait(result)
        if not bait:
            break
        if attempt == 0:
            print(f"⚠️ 참여 유도 문구 감지('{bait}') → 다시 생성")
        else:
            print(f"⚠️ 재생성 후에도 참여 유도 문구 감지('{bait}') → 이번 건 건너뜀")
            return None

    # 본문(그대로 복사해서 올릴 부분)과 '내 한 줄 아이디어'(참고용)를 분리
    body, _, ideas = result.partition(IDEAS_MARKER)
    body, ideas = body.strip(), ideas.strip()

    # 프롬프트의 구조 라벨("1줄 -", "2~4줄 -", "(3)" 등)이 본문에 섞여 나오면 제거
    body = re.sub(r"^[ \t]*\d+(?:~\d+)?줄[ \t]*[-–:][ \t]*", "", body, flags=re.MULTILINE)
    body = re.sub(r"^[ \t]*\(\d\)[ \t]*", "", body, flags=re.MULTILINE)

    if ideas:
        body += f"\n\n━━━━━━━━━━\n✍️ 내 한 줄 추가 아이디어 (선택, 맞으면 본문 맨 위에)\n{ideas}"

    return body
