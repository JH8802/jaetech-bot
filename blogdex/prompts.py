"""작문 사양: 글 종류(정보글/맛집글)별 프롬프트.

근거는 DESIGN.md §2.13(원본 수치 분석)과 §4.10(작문 사양).
수정할 때는 eval_style.py 의 기준(숫자)과 같이 맞춰야 품질 점검이 어긋나지 않습니다.
"""
import re

KINDS = {
    "info": {"label": "정보글"},
    "food": {"label": "맛집글"},
}

TAG_RULES = """[출력 형식 - 반드시 지킬 것]
- 평문만 씁니다. 마크다운 기호(#, *, -, >, 표)는 쓰지 않습니다. (해시태그 줄의 # 는 예외)
- 문단은 빈 줄 하나로 나눕니다.
- 소제목은 '1. 문구' 형식의 한 줄로 쓰고, 앞뒤에 빈 줄을 둡니다.
- 강조는 아래 태그만 씁니다. 태그는 한 문단 안에서 열고 닫으며 서로 겹치지 않습니다.
  {{bold}}핵심 용어 구절{{/bold}}
  {{color}}독자가 꼭 기억해야 할 확인·주의 문장{{/color}}
  {{highlight}}글 전체에서 가장 중요한 한 문장{{/highlight}}
  - {{highlight}} 는 글 전체에서 정확히 2번, {{bold}} 는 8~14번, {{color}} 는 3~7번 씁니다.
  - 마침표와 쉼표는 태그 밖에 둡니다. (예: {{bold}}원료 함량{{/bold}}을 봅니다.)
- 마지막 문단은 해시태그 한 줄입니다. 28~30개, 공백으로 구분, 중복 없이, 각각 # 로 시작하고 태그 안에 공백을 넣지 않습니다.
- 설명, 사과, 머리말, 꼬리말 없이 원고 본문만 출력합니다."""

WRITING_RULES = """[문장 규칙 - 사람이 쓴 글처럼 읽히게]
- 문장 길이에 변화를 줍니다. 20자 안팎의 짧은 문장을 전체의 약 20% 섞고, 60자를 넘는 긴 문장은 20% 이하로 합니다.
- 문단은 1~4문장으로 길이를 달리합니다. 모든 문단을 같은 길이로 맞추지 않습니다.
- 같은 내용을 다른 말로 반복하지 않습니다. 앞에서 한 말은 뒤 섹션에서 다시 하지 않습니다.
- '편안한, 무난한, 자연스러운, 부담 없는, 좋았다' 같은 범용 표현을 반복하지 말고 구체적인 사실이나 장면으로 바꿉니다. (1,000자당 3회 이하)
- 사소한 단점, 망설임, 비교를 한 가지 이상 넣습니다.
- '이번 글에서는 ~ 살펴보겠습니다' 같은 글 안내 문장과 끝인사는 필요할 때만, 매번 다른 표현으로 씁니다.
- 접속어(다만, 특히, 그래서)는 꼭 필요한 곳에만 씁니다."""

SEO_RULES = """[검색 최적화 규칙]
- 아래 '핵심 키워드'를 첫 문단 안에 반드시 포함합니다.
- 핵심 키워드는 본문 전체에서 1,000자당 약 3~6회 자연스러운 문맥으로 반복합니다. 억지로 끼워 넣거나 같은 문장에서 반복하지 않습니다.
- 지역·역 이름은 표현을 바꿔 가며 분산합니다. (예: 마포역, 마포, 공덕역)
- 소제목은 의미가 분명한 짧은 문구로 쓰고 키워드를 억지로 넣지 않습니다."""

EVIDENCE_STRICT = """[재료 사용 규칙 - 사실 우선]
- '작성자 메모'가 글의 뼈대입니다. 메모에 적힌 사실(메뉴, 가격, 시간, 동행, 느낀 점, 좋았던 점, 아쉬운 점)을 가장 구체적으로 풀어 쓰고, 메모의 감정과 판단을 바꾸지 않습니다.
- 메모에 없는 구체 사실(가격, 메뉴 이름, 영업시간, 수치, 방문 날짜, 맛 평가)은 지어내지 않습니다. 꼭 필요하면 [확인 필요: 항목] 으로 표시합니다.
- 방문·사용 경험은 메모에 있는 것만 씁니다. 메모에 없는 부분은 입력된 업체 정보와 일반적으로 확인 가능한 안내 중심으로 쓰고, 가본 것처럼 단정하지 않습니다."""

EVIDENCE_TEMPLATE = """[재료 사용 규칙 - 템플릿형]
- '작성자 메모'가 있으면 우선 반영합니다.
- 메모가 부족한 부분은 일반적인 분위기와 맛 표현으로 채워도 되지만, 가격, 메뉴 이름, 영업시간, 수치, 방문 날짜 같은 구체 사실은 지어내지 않습니다. 필요하면 [확인 필요: 항목] 으로 표시합니다."""

GUARDRAIL = """[표시·광고 가드레일 - 켜짐]
- 질병의 치료·예방·개선, 노화 방지, 특정 기능을 단정하거나 암시하는 표현(예: '~에 효과적이다', '~를 개선한다', '~가 좋아진다')을 쓰지 않습니다. '~로 알려져 있다', '연구가 충분하지 않다'처럼 근거 수준을 함께 밝힙니다.
- 건강기능식품은 '인정된 기능성 표시가 있는지 확인하는 방법'을 안내하고, 의약품이 아니라는 점과 복용 중인 약·질환이 있으면 전문가와 상담하라는 점을 포함합니다.
- 제목과 해시태그에도 같은 기준을 적용합니다. (예: #효능, #치료, #개선, #항산화 같은 태그 금지)
- 수치, 법령, 연구 결과는 출처를 알 수 없으면 쓰지 않거나 [확인 필요: 출처] 로 표시합니다."""

KIND_SPECS = {
    "info": """[글 종류: 정보글]
목적: 검색해서 들어온 독자의 질문을 끝까지 해결하는 정보 글.
구성:
1) 인트로 2문단. 첫 문장에 핵심 키워드와 독자가 가장 먼저 알아야 할 한 가지를 넣고, 둘째 문단에서 이 글이 다룰 내용을 안내합니다.
2) 소제목 4개('1. ' ~ '4. '). 독자의 질문 순서(개념 → 확인 방법 → 주의할 점 → 실천)로 배열합니다. 각 섹션은 4~7문단, 문단당 2~3문장입니다.
3) 소제목 없는 정리 문단 3~5개. 정리 마지막에 짧은 끝인사 한 줄(문구는 매번 다르게).
4) 해시태그 한 줄: 핵심 키워드 + 수식어(고르는법, 추천, 주의사항, 비교 등), 상위 카테고리, 관련 주제 키워드를 섞습니다.
문체: 합니다체. 단정 대신 근거와 한계를 함께 씁니다. 1인칭은 메모에 개인 경험이 있을 때만 1~3회 씁니다.
분량: 공백을 뺀 글자 수로 2,700자 안팎(최소 2,500자). 짧아지기 쉬우니 섹션마다 문단을 4~7개 채우고, 확인 방법·사례·예시 계산을 구체적으로 풀어 씁니다.""",
    "food": """[글 종류: 맛집글(방문 후기)]
구성:
1) 인트로 2~3문단. 장면·감각·상황으로 시작하되 첫 문단 안에 상호, 지점, 지역이 들어갑니다.
2) '1. ' 가게 위치와 분위기: 주소와 가까운 역·길 안내, 외관과 내부, 좌석·소음·주차·대기 팁.
3) '2. ' 주문한 메뉴.
4) '3. ' 다른 메뉴와 추천 조합, 또는 누구와 가면 좋은지.
5) '4. ' 다시 갈 만한가? 재방문 의사, 아쉬운 점, 이런 사람에게 추천.
소제목 문구는 글마다 조금씩 바꿔도 됩니다. 섹션마다 3~5문단, 문단당 2~3문장입니다.
'(플레이스 지도 삽입: …)' 줄과 사진 자리는 시스템이 넣으니 쓰지 않습니다.
문체: 1인칭 후기. 합니다체 약 50%, 해요체 약 35%, 구어 어미(~더라고요, ~거든요, ~잖아요, ~죠) 약 15%를 섞습니다. '저는/저도/제가'로 시작하는 문장은 전체의 25% 이하입니다.
해시태그 한 줄: 상호(지점 있는 것과 없는 것), 지역×업종 조합(예: 마포맛집, 마포고깃집), 메뉴, 상황(회식, 데이트, 모임, 혼밥), 후기·추천 키워드를 섞습니다.
분량: 공백을 뺀 글자 수로 2,100자 안팎(최소 1,900자). 짧아지기 쉬우니 섹션마다 문단을 3~5개 채웁니다.""",
}

BASE_ROLE = "당신은 네이버 블로그 검색 노출에 강하면서도 사람이 쓴 것처럼 읽히는 한국어 블로그 원고를 쓰는 작가입니다."


def build_system(kind: str, guardrail: bool, evidence_mode: str) -> str:
    parts = [BASE_ROLE, KIND_SPECS[kind], TAG_RULES, WRITING_RULES, SEO_RULES]
    parts.append(EVIDENCE_STRICT if evidence_mode == "strict" else EVIDENCE_TEMPLATE)
    if guardrail:
        parts.append(GUARDRAIL)
    return "\n\n".join(parts)


def derive_keywords(kind: str, title: str, place: dict | None) -> list[str]:
    """제목과 업체 정보에서 핵심 키워드 후보를 뽑습니다. (화면에서 사용자가 수정 가능)"""
    kws: list[str] = []
    place = place or {}
    if kind == "food" and place.get("name"):
        name = place["name"].strip()
        kws.append(name)
        first = name.split()[0]
        if first != name:
            kws.append(first)
        m = re.search(r"([가-힣]{2,})구", place.get("address", ""))
        if m:
            kws.append(m.group(1))
    head = re.split(r"[,，]", title or "")[0].split()
    if kind == "info" and head:
        kws.append(" ".join(head[:2]))
    if kind == "food":
        kws += re.findall(r"[가-힣]{2,}역", title or "")
    seen, out = set(), []
    for k in kws:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:6]


def _place_block(place: dict | None) -> str:
    if not place or not place.get("name"):
        return ""
    lines = ["[업체 정보 - 지도 검색 결과이므로 사실로 사용 가능]"]
    for label, key in (("상호", "name"), ("업종", "category"), ("주소", "address"), ("전화", "phone")):
        if place.get(key):
            lines.append(f"- {label}: {place[key]}")
    return "\n".join(lines)


def build_article_prompt(kind: str, title: str, keywords: list[str], memo: str, place: dict | None) -> str:
    parts = [f"[글 제목]\n{title}"]
    if keywords:
        parts.append("[핵심 키워드]\n" + ", ".join(keywords))
    pb = _place_block(place)
    if pb:
        parts.append(pb)
    memo_label = "작성자 메모 - 직접 겪은 일과 느낀 점" if kind == "food" else "작성자 메모 - 경험, 의견, 참고 자료"
    parts.append(f"[{memo_label}]\n" + (memo.strip() if memo and memo.strip() else "(없음)"))
    first_line = (
        "위 재료로 원고를 쓰세요. 첫 줄부터 바로 본문을 시작하고 제목 줄은 쓰지 않습니다."
        if kind == "info"
        else "위 재료로 원고를 쓰세요. 첫 줄부터 바로 본문을 시작하고 제목 줄은 쓰지 않습니다."
    )
    parts.append(first_line)
    return "\n\n".join(parts)


def build_title_prompt(kind: str, keyword: str, memo: str, place: dict | None, exclude: list[str], guardrail: bool) -> str:
    parts = [f"글 종류: {KINDS[kind]['label']}", f"주제/키워드: {keyword}"]
    pb = _place_block(place)
    if pb:
        parts.append(pb)
    if memo and memo.strip():
        parts.append("작성자 메모(참고):\n" + memo.strip()[:600])
    if exclude:
        parts.append("아래 제목들과 겹치지 않는 새로운 방향으로 쓰세요:\n" + "\n".join(f"- {x}" for x in exclude))
    rules = [
        "네이버 블로그 검색 노출에 유리한 제목 5개를 제안하세요.",
        "- 핵심 키워드를 제목 앞쪽에 배치",
        "- 공백 포함 25~35자",
        "- 허위·과장·낚시성 표현 금지",
        "- 5개는 서로 다른 각도(질문형, 숫자형, 후기형, 방법형, 비교형 등)로 작성",
        "- 한 줄에 제목 하나만, 번호·따옴표·부연 설명 없이 출력",
    ]
    if guardrail:
        rules.append("- 효능·치료·개선·노화 방지 등을 단정하거나 암시하는 단어(효능, 효과, 개선, 치료, 예방) 금지")
    parts.append("\n" + "\n".join(rules))
    return "\n".join(parts)


def build_rewrite_prompt(kind: str, body: str, issues: list[str], keywords: list[str]) -> str:
    return "\n\n".join([
        "아래 원고를 같은 주제와 같은 사실을 유지한 채 다시 쓰세요. 아래 '고칠 점'을 모두 반영합니다.",
        "[고칠 점]\n" + "\n".join(f"- {i}" for i in issues),
        "[핵심 키워드]\n" + ", ".join(keywords) if keywords else "",
        "[기존 원고]\n" + body,
        "출력 형식 규칙은 그대로이며, 설명 없이 원고 본문만 출력합니다.",
    ]).strip()
