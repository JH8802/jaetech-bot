import anthropic
from blog_utils import link_stats, button_line_problems, parse_draft_metadata, count_keyphrase, keyphrase_target, long_sentence_stats, LONG_SENTENCE_WORDS, LONG_SENTENCE_MAX_RATIO, extract_text, has_keyword, load_settings, find_placeholders, source_cards, card_numbers
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

# AI 글에서 자주 반복되는 말버릇 — (화면 이름, 찾을 표현들, 한 글에서 허용 횟수)
# 한두 번은 자연스럽지만 반복되면 AI 티가 남. 실제로 써보며 자유롭게 추가/조정하면 됨.
AI_PATTERNS = [
    ("'~얘기다/이야기다'로 맺기", ["는 얘기다", "라는 얘기다", "는 이야기다", "라는 이야기다", "란 얘기다"], 1),
    ("'~셈이다'", ["셈이다"], 1),
    ("'~하는 이유다'", ["이유다."], 1),
    ("'솔직히'", ["솔직히"], 1),
    ("'짚어야/짚어볼'", ["짚어야", "짚어볼", "짚어둘", "짚고 넘어"], 1),
    ("'따져봐야/따져보면'", ["따져봐", "따져보", "따져야"], 2),
    ("'핵심은/중요한 건'", ["핵심은", "중요한 건", "중요한 것은"], 1),
    ("'결국'", ["결국"], 2),
    ("'~라고 할 수 있다'", ["라고 할 수 있다", "다고 할 수 있다"], 0),
    ("'~것이 중요하다'", ["것이 중요하다", "게 중요하다"], 0),
    ("'살펴보자/알아보자'", ["살펴보자", "알아보자", "살펴보겠", "정리해보면", "정리해 보면"], 0),
    ("'주목할 만한/눈여겨볼'", ["주목할 만한", "눈여겨볼", "주목할 만하다"], 0),
    ("'~는 점이다'", ["는 점이다", "다는 점이다"], 1),
    ("'다만'", ["다만"], 2),
    ("'물론'", ["물론"], 1),
]
SAME_ENDING_RUN = 3  # 같은 어미로 끝나는 문장이 이만큼 연속되면 지적


def scan_ai_patterns(body):
    """AI 말투 점검 (규칙 기반, 무료) — 반복되는 말버릇 + 같은 어미 연속."""
    issues = []
    text = re.sub(r"\[[^\]]*\]", " ", body)
    for label, phrases, allowed in AI_PATTERNS:
        # 긴 표현부터 맞춰서 겹쳐 세지 않게 ('라는 얘기다' 안의 '는 얘기다'를 또 세지 않음)
        pattern = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
        count = len(re.findall(pattern, text))
        if count > allowed:
            limit = "쓰지 않는 게 좋음" if allowed == 0 else f"{allowed}번 이하 권장"
            issues.append(f"{label} {count}번 — {limit}")

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 5]
    endings = [re.sub(r"[.!?\s]+$", "", s)[-2:] for s in sentences]
    run_start, reported = 0, 0
    for i in range(1, len(endings) + 1):
        if i < len(endings) and endings[i] == endings[run_start]:
            continue
        run = i - run_start
        if run >= SAME_ENDING_RUN and reported < 3:
            sample = sentences[run_start][-25:]
            issues.append(f"'~{endings[run_start]}'로 끝나는 문장 {run}개 연속 (예: …{sample}) — 어미를 바꿔 리듬 주기")
            reported += 1
        run_start = i
    return issues


# review_draft()가 반환하는 키 -> 화면에 보여줄 라벨 (blog_write.py, blog_app.py 공용)
AI_REVIEW_LABELS = {
    "sentence_rhythm": "문장 길이 변주",
    "opinion": "저자 의견",
    "specificity": "사실 구체성",
    "differentiation": "차별화(뻔한 내용 여부)",
    "keyword_clarity": "SEO 키워드 명확성",
    "intent_answer": "검색 의도 충족(소제목마다 답했나)",
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

    paragraphs = [p for p in draft.split("\n\n") if p.strip() and not (p.strip().startswith("[") and not p.strip().startswith("[["))]
    # 표(| 구분)·목록(- / 1.) 묶음은 문단이 아니므로 길이 점검에서 뺌
    paragraphs = [p for p in paragraphs
                  if not all("|" in l or re.match(r"^\s*(?:[-•·]|\d{1,2}[.)])\s", l) for l in p.strip().split("\n"))]
    long_paragraphs = [p for p in paragraphs if len(p) > 400]
    if long_paragraphs:
        issues.append(f"긴 문단 {len(long_paragraphs)}개 (400자 초과 — 나누면 가독성 좋아짐)")

    if len(draft) < 1000:
        issues.append(f"본문이 짧음 ({len(draft)}자) — 짧은 글은 저품질 신호로 취급될 수 있음")

    issues += button_line_problems(parse_draft_metadata(draft)["body"])

    long_ones, total, ratio = long_sentence_stats(parse_draft_metadata(draft)["body"])
    if total and ratio > LONG_SENTENCE_MAX_RATIO:
        examples = " / ".join(f"'{s[:40]}…'" for s in sorted(long_ones, key=lambda s: -len(s.split()))[:2])
        issues.append(f"긴 문장 비율 {ratio}% ({LONG_SENTENCE_WORDS}어절 넘는 문장 {len(long_ones)}개 / 전체 {total}개) — "
                      f"{LONG_SENTENCE_MAX_RATIO}% 이하 권장 (Yoast 가독성 기준). 긴 문장을 두 문장으로 끊기. 예: {examples}")

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


# 태그 개수 권장 범위 (플랫폼별)
TAG_RANGE = {"워드프레스": (2, 4), "티스토리": (3, 7), "네이버 블로그": (3, 10)}

# 저자 경험을 주장하는 표현 — 이런 문장은 내가 준 메모·의견에 근거가 있어야 함
EXPERIENCE_MARKERS = [
    "실무에서", "현장에서", "현업에서", "업무에서", "업무상", "일하면서", "담당하면서", "검수하면서",
    "점검하면서", "직접 확인", "직접 봤", "직접 본", "직접 먹", "직접 써", "직접 사용", "직접 검사",
    "내가 본", "제가 본", "본 적이", "봐 왔", "봐왔", "경험상", "경험으로", "겪어 보", "겪어보",
    "먹어 보", "먹어보", "써 보니", "써보니", "확인해 보니", "확인해보니", "해 보니", "해보니",
]
_EXPERIENCE_RE = re.compile("|".join(re.escape(m) for m in EXPERIENCE_MARKERS))


def _bigrams(text):
    chars = re.sub(r"[^0-9A-Za-z가-힣]", "", text)
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def scan_experience_claims(body, own_texts, threshold=0.35):
    """메모·의견에 근거 없는 '저자 경험' 주장 문장을 찾는다 (구글이 중시하는 '경험'을 지어내는 것 방지).
    own_texts: 저자가 직접 준 글 (경험 메모·의견·다듬기 메모·직접 입력) — 출처 자료는 포함하지 않음.
    경험 표현이 들어간 문장과 저자 글의 글자 조각(2글자) 겹침 비율이 낮으면 지적."""
    own = _bigrams(" ".join(own_texts))
    found = []
    text = re.sub(r"\[[^\]]*\]", " ", body)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = sentence.strip()
        if not sentence or not _EXPERIENCE_RE.search(sentence):
            continue
        content = _bigrams(_EXPERIENCE_RE.sub(" ", sentence))
        if not content:
            continue
        overlap = len(content & own) / len(content)
        if overlap < threshold:
            found.append(sentence[:120])
    return found


UNCERTAIN_RE = re.compile(r"모르겠|모른다|알 수 없|확인하지 못|찾지 못했|답을 찾지|정해진 기준이 없|알려진 바 없")


def scan_sections(body):
    """검색 의도 점검 — 소제목 아래 내용이 그 소제목에 실제로 답하는지 (규칙 기반).
    너무 짧은 섹션, '모르겠다'로만 끝나는 섹션을 찾는다."""
    issues = []
    sections, title, buf = [], None, []
    for line in body.split("\n"):
        if line.strip().startswith("[소제목]"):
            if title is not None:
                sections.append((title, "\n".join(buf)))
            title, buf = line.strip()[len("[소제목]"):].strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        sections.append((title, "\n".join(buf)))

    for title, content in sections:
        text = re.sub(r"\[[^\]]*\][^\n]*", " ", content).strip()
        if UNCERTAIN_RE.search(text) and not re.search(r"\d", text):
            issues.append(f"'{title}' 섹션이 '모르겠다'류로 끝나고 구체적 정보(수치 등)가 없음 — 검색한 사람이 답을 못 얻고 "
                          "나감. 소제목을 내용에 맞게 바꾸거나(예: '기준이 없을 때 확인할 것') 근거를 보강")
        elif len(text) < 120:
            issues.append(f"'{title}' 섹션이 너무 짧음 ({len(text)}자) — 소제목이 약속한 내용을 충분히 다루지 못함")
    return issues


def scan_seo(meta, platform, target_keyword="", has_reference_links=False):
    """규칙 기반 SEO 점검 — 구글 기준(티스토리/워드프레스)은 더 엄격하게 본다.
    meta는 parse_draft_metadata()의 반환값."""
    issues = []
    body = meta["body"]
    is_google = platform in ("티스토리", "워드프레스")

    subheadings = [l.strip()[len("[소제목]"):].strip()
                   for l in body.split("\n") if l.strip().startswith("[소제목]")]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not (p.strip().startswith("[") and not p.strip().startswith("[["))]
    first_paragraph = paragraphs[0] if paragraphs else ""

    focus = (meta.get("focus_keyphrase") or "").strip()
    kp = focus or target_keyword
    if is_google and not focus:
        issues.append("[초점 키프레이즈] 줄이 없음 — 워드프레스 Yoast SEO의 '초점 키프레이즈' 칸에 넣을 검색어 "
                      "(보통 타깃 키워드와 같게)")
    elif focus and target_keyword and focus.replace(" ", "") != target_keyword.replace(" ", ""):
        issues.append(f"초점 키프레이즈 '{focus}'가 타깃 키워드 '{target_keyword}'와 다름 — 하나로 맞추는 걸 권장")

    if kp and is_google:
        # Yoast SEO처럼 '글자 그대로 + 뒤에 조사 없이' 쓴 것만 인정해서 센다
        def where(label, text):
            if count_keyphrase(text, kp):
                return
            if count_keyphrase(text, kp, exact=False):
                issues.append(f"{label}에 초점 키프레이즈 '{kp}'가 조사와 붙어 있음 (예: '{kp}는') — Yoast는 글자 그대로만 "
                              f"인정해서 없는 걸로 봄. '{kp} 기준은', '{kp}, …'처럼 뒤를 띄어 쓰기")
            else:
                issues.append(f"{label}에 초점 키프레이즈 '{kp}'가 없음")
        where("제목", meta["title"])
        where("첫 문단", first_paragraph)
        where("메타설명", meta["meta_description"])
        body_text = "\n".join(l for l in body.split("\n") if not l.strip().startswith("[사진 제안]"))
        count = count_keyphrase(body_text, kp)
        low, high = keyphrase_target(len(body))
        if count < low:
            loose = count_keyphrase(body_text, kp, exact=False)
            extra = f" (조사가 붙어서 인정 안 되는 것 {loose - count}번 포함하면 {loose}번)" if loose > count else ""
            issues.append(f"본문에 초점 키프레이즈 '{kp}'가 {count}번{extra} — 이 길이({len(body):,}자)면 "
                          f"{low}~{high}번 권장 (키워드 밀도)")
        elif count > high + 3:
            issues.append(f"본문에 초점 키프레이즈 '{kp}'가 {count}번 — 너무 많으면 키워드 욱여넣기로 보여 "
                          f"({low}~{high}번 권장)")
        if subheadings and not any(count_keyphrase(s, kp, exact=False) for s in subheadings):
            issues.append(f"소제목 중 초점 키프레이즈 '{kp}'가 들어간 게 하나도 없음 (1~2개 권장)")
        alts = re.findall(r'ALT:\s*"([^"]*)"', body)
        if alts and not any(count_keyphrase(a, kp, exact=False) for a in alts):
            issues.append(f"사진 ALT 중 초점 키프레이즈 '{kp}'가 들어간 게 없음 (1개 권장)")
    elif kp:
        if not has_keyword(meta["title"], kp):
            issues.append(f"제목에 타깃 키워드 '{kp}'가 없음")
        if not has_keyword(first_paragraph, kp):
            issues.append(f"첫 문단에 타깃 키워드 '{kp}'가 없음 (검색엔진이 첫 문단으로 주제를 파악함)")

    title_len = len(meta["title"])
    if title_len > 35:
        issues.append(f"제목 {title_len}자 — 검색결과에서 뒷부분이 잘릴 수 있음 (30자 안팎 권장)")

    tags = [t.strip() for t in re.split(r"[,，]", meta.get("tags", "")) if t.strip()]
    low, high = TAG_RANGE.get(platform, (3, 7))
    if not low <= len(tags) <= high:
        why = " (워드프레스는 태그마다 목록 페이지가 생겨서, 많으면 얇은 페이지가 쌓임)" if platform == "워드프레스" else ""
        issues.append(f"태그 {len(tags)}개 — {low}~{high}개 권장{why}")
    categories = load_settings()["categories"]
    if categories and meta.get("category", "").strip() not in categories:
        issues.append(f"카테고리 '{meta.get('category', '')}'가 내 카테고리 목록에 없음 — 목록 중에서 골라야 사이트 구조가 흐트러지지 않음")
    flat_tags = [t.replace(" ", "").lower() for t in tags]
    if len(set(flat_tags)) < len(flat_tags):
        issues.append("중복된 태그가 있음")
    if kp and tags and not any(has_keyword(t, kp) for t in tags):
        issues.append(f"태그에 타깃 키워드 '{kp}'가 없음 (첫 태그로 넣는 걸 권장)")

    if is_google:
        if not 3 <= len(subheadings) <= 5:
            issues.append(f"소제목 {len(subheadings)}개 — 구글용 글은 3~5개 권장")
        desc_len = len(meta["meta_description"])
        if desc_len == 0:
            issues.append("메타설명이 없음")
        elif not 100 <= desc_len <= 160:
            issues.append(f"메타설명 {desc_len}자 — 120~155자 권장 (너무 짧거나 길면 구글이 본문에서 임의로 가져감)")

    if is_google:
        internal, external = link_stats(body)
        if internal == 0:
            issues.append("내부 링크가 없음 (Yoast 빨간불) — 내 블로그의 관련 글로 가는 링크를 1개 이상: "
                          "[링크: 글 제목 | 주소] 줄이나 문장 속 [[글자 | 주소]]. 사이드바에 '내 블로그 주소'를 적어둬야 "
                          "내부/외부가 정확히 구분돼")
        if external == 0 and not has_reference_links:
            issues.append("외부 링크가 없음 (Yoast 빨간불) — 근거 출처의 원문 링크를 1개 이상: 출처 칸에 링크를 넣거나, "
                          "문장 속 [[출처 이름 | 주소]]")

    if platform == "워드프레스" and not meta.get("slug"):
        issues.append("글 주소(슬러그)가 없음")

    reviews = body.count("[검수")
    if reviews:
        issues.append(f"[검수] {reviews}곳 — AI가 판단이 필요하다고 표시한 부분 (인정 범위 밖 표현·자료 충돌 등). "
                      "확인하고 '남은 항목 채우기'에서 처리해야 함")

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
    issues += [f"[AI 말투] {i}" for i in review.get("ai_patterns", [])]
    issues += [f"[검색 의도] {i}" for i in review.get("sections", [])]
    for sentence in review.get("experience", []):
        issues.append(f"[지어낸 경험] '{sentence}' — 저자 메모·의견에 근거가 없는 경험 주장. 경험 표현을 빼고 "
                      "사실 서술로 바꾸거나, 근거 없는 내용이면 삭제해야 함")
    for row in review.get("copied", []):
        issues.append(f"[원문과 거의 같은 문장] '{row['sentence']}' ({row['source']}) — 자료 문장을 거의 그대로 "
                      "옮김. 같은 뜻을 블로그 문체로 완전히 새로 써야 함 (저작권)")
    for row in review.get("facts", []):
        if not row["found_in"]:
            issues.append(f"[근거 없는 숫자] '{row['number']}' ({row['context']}) — 입력한 메모·출처에 없는 숫자. "
                          "재료에 있는 숫자로 바로잡거나, 확인할 수 없으면 그 숫자를 빼야 함")
    for key, label in AI_REVIEW_LABELS.items():
        val = ai_issue((review.get("ai") or {}).get(key))
        if val:
            issues.append(f"[{label}] {val}")
    return issues


def review_draft(draft):
    """AI 기반 점검 (문장 리듬 / 저자 의견 / 사실 구체성 / 차별화 / SEO 키워드) — Haiku로 저비용 호출."""
    prompt = f"""아래는 블로그 초안이야. 다음 6개 기준으로 점검해줘.
각 기준마다 "문제가 있는지(problem: true/false)"를 먼저 판정하고, 문제가 있을 때만
detail에 원문 문장을 그대로 짧게 인용해서 무엇이 문제인지 적어줘.
문제가 없으면 problem을 false로 하고 detail은 빈 문자열("")로 둬 — 문제 없다는
설명을 detail에 쓰지 마.

1. sentence_rhythm: 문장 길이가 단조로운가 (대부분 비슷한 길이인가)
2. opinion: 저자의 의견/판단 없이 중립적 나열에 그치는가
3. specificity: 사실/사례가 뭉뚱그려져 있고 구체성이 떨어지는가
4. differentiation: 이 주제를 검색하면 어디서나 나올 법한 뻔하고 일반적인
   설명/사례에 그치는가 (직접 겪은 일이나 실무자만 아는 디테일이 아니라
   교과서적/통념적 설명 위주인가). 이 글만의 구체적 시각·경험이 충분하면 false
5. keyword_clarity: [제목]과 본문 첫 문단만 보고 "이 글이 정확히 무엇에
   대한 글인지" 검색하는 사람 입장에서 바로 알 수 있는가. 제목이나
   도입부가 모호하거나 핵심 키워드 없이 겉돈다면 true
   (키워드를 억지로 많이 넣으라는 뜻이 아니라, 명확성 문제만 봐줘)
6. intent_answer: 각 [소제목]을 검색어로 친 사람이 그 아래 내용만 읽고 원하던 답을 얻는가.
   소제목이 질문·약속을 하는데 아래 내용이 답을 안 주거나 빙빙 돌면 true

반드시 아래 JSON 형식으로만 답해. 다른 설명 없이 JSON만 출력해.
{{"sentence_rhythm": {{"problem": false, "detail": ""}},
 "opinion": {{"problem": false, "detail": ""}},
 "specificity": {{"problem": false, "detail": ""}},
 "differentiation": {{"problem": false, "detail": ""}},
 "keyword_clarity": {{"problem": false, "detail": ""}},
 "intent_answer": {{"problem": false, "detail": ""}}}}

초안:
{draft}"""

    last_error = None
    for attempt in range(2):  # 형식이 깨지거나 일시적으로 실패하면 1번 더 시도
        # 1차: 생각(thinking)을 끄고 빠르게 / 2차: 기본 설정 + 넉넉한 토큰
        # (생각에 토큰을 다 쓰면 JSON이 중간에 끊겨 'Unterminated string' 오류가 났음)
        extra = {"output_config": {"effort": "low"}}
        if attempt == 0:
            extra["thinking"] = {"type": "disabled"}
        try:
            message = client.messages.create(
                model="claude-haiku-5-5",
                max_tokens=2000 if attempt == 0 else 6000,
                extra_body=extra,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = extract_text(message)
            parsed = _parse_review_json(raw)
            if parsed:
                return parsed
            last_error = (f"응답에서 점검 결과를 읽지 못함 (stop_reason={message.stop_reason}, "
                          f"응답 앞부분: {raw[:80]!r})")
        except Exception as e:
            last_error = e

    print(f"⚠️ AI 점검 실패 (건너뜀): {last_error}")
    return {}


def _normalize(value):
    """항목 하나를 '없음' 또는 지적 문장으로 통일한다.
    새 형식 {"problem": bool, "detail": str}과 옛 형식(문자열)을 모두 받는다."""
    if isinstance(value, dict):
        if value.get("problem") is True or str(value.get("problem")).lower() == "true":
            return (value.get("detail") or "").strip() or "문제가 있다고 판정됨 (상세 설명 없음)"
        return "없음"
    return (value or "").strip() or "없음"


def _parse_review_json(text):
    """AI 응답에서 5개 항목을 뽑아 {키: '없음' 또는 지적 문장}으로 돌려준다.
    지적 문장에 따옴표(")가 섞여 JSON이 깨져도 항목별로 직접 찾아서 최대한 살린다."""
    text = text.replace("```json", "").replace("```", "").strip()
    keys = list(AI_REVIEW_LABELS)

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0), strict=False)
            if isinstance(data, dict) and all(k in data for k in keys):
                return {k: _normalize(data[k]) for k in keys}
        except ValueError:
            pass

    result = {}
    for key in keys:
        # 새 형식: "key": {"problem": true/false, "detail": "..."}
        pm = re.search(
            rf'"{key}"\s*:\s*\{{\s*"problem"\s*:\s*(true|false)\s*,\s*"detail"\s*:\s*"(.*?)"\s*\}}',
            text, re.DOTALL | re.IGNORECASE)
        if pm:
            result[key] = _normalize({"problem": pm.group(1).lower() == "true", "detail": pm.group(2)})
    return result if len(result) == len(keys) else {}



def own_texts(inputs):
    """저자가 직접 준 글 (경험 주장 대조용) — 출처 자료는 제외."""
    return (list(inputs.get("key_points", [])) + [inputs.get("personal_take", "")]
            + list(inputs.get("notes", [])) + list(inputs.get("user_additions", [])))


def readiness(review, body, inputs, settings, platform):
    """발행 준비 상태. 반환: [(항목, 상태, 설명)] — 상태: "ok" | "block"(발행 전 반드시 해결) | "warn"(확인 권장)"""
    items = find_placeholders(body)
    pending = [i for i in items if i["kind"] in ("source", "add", "review", "link")]
    photos = [i for i in items if i["kind"] == "visual"]
    facts_missing = [r for r in review.get("facts", []) if not r["found_in"]]
    has_own = any(t.strip() for t in own_texts(inputs))
    ai = review.get("ai") or {}
    ai_problems = [AI_REVIEW_LABELS[k] for k in AI_REVIEW_LABELS if ai_issue(ai.get(k))]
    google = platform in ("티스토리", "워드프레스")

    rows = [
        ("남은 항목([출처 필요]·[추가 필요]·[검수]·[내부링크 제안])",
         "block" if pending else "ok", f"{len(pending)}개 남음" if pending else "모두 처리됨"),
        ("자료와 다르게 쓴 곳 (내가 쓴 글 ↔ 자료 노트)",
         "block" if review.get("mismatch") else "ok",
         f"{len(review.get('mismatch') or [])}곳 — 원문 확인 후 본문에서 직접 고치기" if review.get("mismatch") else "없음"),
        ("근거 없는 숫자", "block" if facts_missing else "ok",
         f"{len(facts_missing)}개" if facts_missing else "없음"),
        ("원문과 거의 같은 문장 (저작권)", "block" if review.get("copied") else "ok",
         f"{len(review.get('copied', []))}개" if review.get("copied") else "없음"),
        ("지어낸 경험 (메모에 없는 실무 경험 주장)", "block" if review.get("experience") else "ok",
         f"{len(review.get('experience', []))}개" if review.get("experience") else "없음"),
        ("저자 의견·경험 입력", "ok" if has_own else "block",
         "있음" if has_own else "없음 — 자료만 다시 정리한 글은 구글이 가치 낮게 봄"),
        ("저자 소개 (사이드바에서 저장)", "ok" if settings.get("author_bio", "").strip() else ("block" if google else "warn"),
         "있음" if settings.get("author_bio", "").strip() else "없음 — 누가 쓴 글인지 보여줘야 신뢰도가 올라감"),
        ("검색 의도 (섹션마다 답을 주는지)", "warn" if review.get("sections") else "ok",
         f"{len(review.get('sections', []))}개 섹션 확인 필요" if review.get("sections") else "문제 없음"),
        ("검색 최적화 (키워드·태그·카테고리 등)", "warn" if review.get("seo") else "ok",
         f"{len(review.get('seo', []))}건" if review.get("seo") else "문제 없음"),
        ("표시광고 표현", "warn" if review.get("claims") else "ok",
         "확인 필요 (설명 문맥이면 괜찮음)" if review.get("claims") else "걸리는 표현 없음"),
        ("AI 점검", "warn" if ai_problems else "ok", ", ".join(ai_problems) if ai_problems else "문제 없음"),
        ("원문 카드 (독자가 눌러 원문을 보는 링크 박스)",
         "warn" if source_cards(inputs) and not set(card_numbers(body)) & set(source_cards(inputs)) else "ok",
         "링크 있는 출처가 있는데 본문에 카드가 없음" if source_cards(inputs)
         and not set(card_numbers(body)) & set(source_cards(inputs)) else "문제 없음"),
        ("사진 자리", "warn" if photos else "ok",
         f"{len(photos)}곳 — 에디터에서 사진을 넣고 📌 줄 삭제" if photos else "없음"),
    ]
    return rows
