import anthropic
from blog_utils import extract_text, has_keyword
from dotenv import load_dotenv
import os
import json
import re

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

# 질병 치료·예방을 암시할 수 있는 표현 — 나오면 "확인 필요"로만 알려줌
# (표시광고를 다루는 글이면 "이런 표현은 못 쓴다"는 설명 문맥에서도 나오므로
#  자동 불합격 처리는 안 함). 실무 기준에 맞게 자유롭게 추가/삭제해서 쓰면 됨.
HEALTH_CLAIM_WATCH = [
    "치료", "완치", "예방", "특효", "만병", "기적", "부작용 없", "부작용이 없",
    "약 대신", "약을 끊", "의약품 대체", "100% 효과", "즉효",
]

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


def scan_health_claims(draft):
    """규칙 기반 표시광고 표현 점검 — HEALTH_CLAIM_WATCH 표현이 들어간 문장을
    찾아 '표현: 문장 일부' 형태로 돌려준다 (문맥은 사람이 판단)."""
    found = []
    sentences = re.split(r"(?<=[.!?。])\s+|\n", draft)
    for sentence in sentences:
        sentence = sentence.strip()
        for phrase in HEALTH_CLAIM_WATCH:
            if phrase in sentence:
                snippet = sentence if len(sentence) <= 80 else sentence[:80] + "…"
                found.append(f"'{phrase}' → {snippet}")
                break
    return found


def scan_seo(meta, platform, target_keyword=""):
    """규칙 기반 SEO 점검 — 구글 기준(티스토리/워드프레스)은 더 엄격하게 본다.
    meta는 parse_draft_metadata()의 반환값."""
    issues = []
    body = meta["body"]
    is_google = platform in ("티스토리", "워드프레스")

    subheadings = [l.strip()[len("[소제목]"):].strip()
                   for l in body.split("\n") if l.strip().startswith("[소제목]")]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("[")]
    first_paragraph = paragraphs[0] if paragraphs else ""

    if target_keyword:
        if not has_keyword(meta["title"], target_keyword):
            issues.append(f"제목에 타깃 키워드 '{target_keyword}'가 없음")
        if not has_keyword(first_paragraph, target_keyword):
            issues.append(f"첫 문단에 타깃 키워드 '{target_keyword}'가 없음 (구글이 첫 문단으로 주제를 파악함)")
        if is_google and subheadings and not any(has_keyword(s, target_keyword) for s in subheadings):
            issues.append("소제목 중 타깃 키워드가 들어간 게 하나도 없음")

    title_len = len(meta["title"])
    if title_len > 35:
        issues.append(f"제목 {title_len}자 — 검색결과에서 뒷부분이 잘릴 수 있음 (30자 안팎 권장)")

    if is_google:
        if not 3 <= len(subheadings) <= 5:
            issues.append(f"소제목 {len(subheadings)}개 — 구글용 글은 3~5개 권장")
        desc_len = len(meta["meta_description"])
        if desc_len == 0:
            issues.append("메타설명이 없음")
        elif not 100 <= desc_len <= 160:
            issues.append(f"메타설명 {desc_len}자 — 120~155자 권장 (너무 짧거나 길면 구글이 본문에서 임의로 가져감)")

    if platform == "워드프레스" and not meta.get("slug"):
        issues.append("글 주소(슬러그)가 없음")

    pending = body.count("[추가 필요")
    if pending:
        issues.append(f"[추가 필요] {pending}곳 — AI가 재료가 없어 못 채운 부분. 발행 전에 직접 채우거나 "
                      "그 줄을 지워야 함 (그대로 올라가면 대괄호 문구가 글에 노출됨)")

    missing_sources = body.count("[출처 필요")
    if missing_sources:
        issues.append(f"[출처 필요] {missing_sources}곳 — 발행 전에 근거를 채우거나 문장을 고쳐야 함 "
                      "(건강·돈 주제는 구글이 근거를 특히 엄격하게 봄)")

    return issues


def ai_issue(val):
    """AI 점검 항목 하나의 응답에서 '진짜 지적'만 돌려준다 (문제 없으면 빈 문자열).

    AI가 '문제 없음'을 "…다양하다고 보기 어렵다. 없음"처럼 설명을 붙여서 답하는
    경우가 있어서, 정확히 '없음'일 때뿐 아니라 문장이 끝난 뒤 '없음'으로 마무리되는
    경우도 문제 없음으로 본다. ('출처가 없음'처럼 지적 문장 자체가 '없음'으로 끝나는
    경우는 앞에 마침표가 없으므로 지적으로 유지됨.)"""
    val = (val or "").strip()
    if not val or val.rstrip(" .") == "없음":
        return ""
    if re.search(r"[.。!?]\s*없음\.?$", val):
        return ""
    return val


def collect_issues(review):
    """화면에 저장해 둔 점검 결과(dict)에서 '고쳐야 할 지적'만 문자열 리스트로 모은다
    (다듬기 요청에 그대로 넘기기 위함)."""
    issues = []
    issues += [f"[클리셰/반복] {i}" for i in review.get("cliche", [])]
    issues += [f"[글 구조] {i}" for i in review.get("structure", [])]
    issues += [f"[검색 최적화] {i}" for i in review.get("seo", [])]
    issues += [f"[표시광고 표현 확인] {i}" for i in review.get("claims", [])]
    for key, label in AI_REVIEW_LABELS.items():
        val = ai_issue((review.get("ai") or {}).get(key))
        if val:
            issues.append(f"[{label}] {val}")
    return issues


def review_draft(draft):
    """AI 기반 점검 (문장 리듬 / 저자 의견 / 사실 구체성 / 차별화 / SEO 키워드) — Haiku로 저비용 호출."""
    prompt = f"""아래는 블로그 초안이야. 다음 5개 기준으로만 점검해줘.
문제 되는 부분은 원문 문장을 그대로 짧게 인용해서 지적하고,
문제 없으면 설명을 덧붙이지 말고 정확히 "없음" 한 단어만 답해.

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

    last_error = None
    for attempt in range(2):  # 형식이 깨지거나 일시적으로 실패하면 1번 더 시도
        try:
            message = client.messages.create(
                model="claude-haiku-5-5",
                max_tokens=2000,
                extra_body={"output_config": {"effort": "low"}},
                messages=[{"role": "user", "content": prompt}]
            )
            parsed = _parse_review_json(extract_text(message))
            if parsed:
                return parsed
            last_error = "응답에서 점검 결과를 읽지 못함"
        except Exception as e:
            last_error = e

    print(f"⚠️ AI 점검 실패 (건너뜀): {last_error}")
    return {}


def _parse_review_json(text):
    """AI 응답에서 5개 항목을 뽑는다. 지적 문장에 따옴표(")가 섞여 JSON이 깨져도
    항목별로 직접 찾아서 최대한 살린다."""
    text = text.replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0), strict=False)
            if isinstance(data, dict) and data:
                return data
        except ValueError:
            pass

    keys = list(AI_REVIEW_LABELS)
    result = {}
    for i, key in enumerate(keys):
        nxt = keys[i + 1] if i + 1 < len(keys) else None
        end = rf'"\s*,\s*"{nxt}"\s*:' if nxt else r'"\s*\}\s*$'
        pm = re.search(rf'"{key}"\s*:\s*"(.*?){end}', text, re.DOTALL)
        if pm:
            result[key] = pm.group(1).strip()
    return result if len(result) == len(keys) else {}
