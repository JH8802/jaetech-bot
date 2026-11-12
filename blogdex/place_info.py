"""네이버 지도 정보 정리: 작성자가 네이버 지도에서 복사한 글이나 화면 캡처를 AI가 읽어 매장 정보로 정리합니다.

- 네이버 지도를 프로그램이 직접 긁어오지 않습니다(이용약관·차단·잦은 고장 때문에). 화면은 작성자가 열고, 정리만 프로그램이 합니다.
- 캡처는 정보를 읽는 데만 쓰고 원고 사진으로는 쓰지 않습니다.
- 정리한 결과는 화면의 '매장 정보' 칸에 들어가고, 작성자가 고칠 수 있습니다. 원고를 만들 때 이 칸이 업체 정보로 함께 갑니다.
"""
import json
import re

MAX_CAPTURES = 4  # 캡처 최대 장수(홈 탭, 메뉴 탭 등)
MAX_PASTE = 6000  # 붙여넣기 글 최대 길이
MAX_DETAILS = 2000  # '매장 정보' 칸 최대 길이
LINK_HOSTS = ("naver.me", "map.naver.com", "m.map.naver.com", "place.naver.com", "m.place.naver.com", "pcmap.place.naver.com")

SYSTEM = """너는 네이버 지도(플레이스) 화면의 정보를 정리하는 도우미다.
작성자가 네이버 지도에서 복사한 글이나 화면 캡처를 주면, 그 안에 실제로 적힌 정보만 골라 JSON 하나로 답한다.
- 화면에 없는 정보는 지어내지 않고 빈 값으로 둔다. 추측하거나 일반 상식으로 채우지 않는다.
- 리뷰·광고·추천 장소·다른 매장 정보는 무시한다.
- 설명 없이 JSON 만 출력한다."""

FIELDS = """{
  "name": "상호(화면에 있을 때만)",
  "category": "업종(예: 돼지고기구이, 호텔)",
  "address": "도로명 주소(층·호수 포함). 지번 주소만 있으면 지번",
  "phone": "전화번호(안심번호 포함)",
  "hours": ["영업시간 줄. 요일별로 다르면 '평일 11:00~22:00', '주말 10:30~21:00'처럼 나눠서. 브레이크타임·라스트오더도 한 줄씩. 숙소는 '체크인 15:00', '체크아웃 11:00'"],
  "closed": "정기 휴무(예: 매주 월요일). 없으면 빈 값",
  "menu": ["대표 메뉴 '메뉴 이름 가격' (예: '삼겹살 200g 17,000원'). 화면에 있는 순서로 최대 8개. 관광지·시설은 이용 요금(예: '성인 29,000원')"],
  "parking": "주차 정보",
  "reservation": "예약·대기 정보(예: 네이버 예약 가능, 캐치테이블 원격 줄서기)",
  "transit": "찾아가는 길(예: 공덕역 5번 출구 도보 3분)",
  "extra": ["그 밖에 화면에 적힌 실용 정보(예: 포장 가능, 단체석). 편의시설은 화면에 분명히 적힌 것만. 최대 4개"]
}"""


def build_prompt(kind: str, name: str, text: str, image_count: int) -> str:
    target = "숙소·장소" if kind == "hotel" else "매장"
    parts = [f"[{target} 이름] {name or '(입력 안 함)'}"]
    if text:
        parts.append("[네이버 지도에서 복사한 글]\n" + text)
    if image_count:
        parts.append(f"[네이버 지도 화면 캡처] 위 사진 {image_count}장")
    parts.append(f"위 자료에서 {target} 정보를 아래 형식의 JSON 으로 정리하세요. 값이 없으면 \"\" 또는 [] 로 둡니다.\n" + FIELDS)
    return "\n\n".join(parts)


def _s(v, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _list(v, n: int, limit: int = 80) -> list[str]:
    if isinstance(v, str):
        v = [x for x in re.split(r"\n+", v)]
    if not isinstance(v, list):
        return []
    return [x for x in (_s(i, limit) for i in v) if x][:n]


def parse(raw: str) -> dict:
    """AI 응답(JSON) → 정리된 정보. 읽지 못하면 빈 값."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    d = d if isinstance(d, dict) else {}
    return {
        "name": _s(d.get("name"), 100), "category": _s(d.get("category"), 60), "address": _s(d.get("address"), 200),
        "phone": _s(d.get("phone"), 40), "hours": _list(d.get("hours"), 6), "closed": _s(d.get("closed"), 80),
        "menu": _list(d.get("menu"), 8), "parking": _s(d.get("parking"), 120), "reservation": _s(d.get("reservation"), 120),
        "transit": _s(d.get("transit"), 120), "extra": _list(d.get("extra"), 4),
    }


def to_details(info: dict) -> str:
    """화면 '매장 정보' 칸에 넣을 글(작성자가 읽고 고치기 쉬운 '라벨: 값' 줄). 주소·전화·업종은 각자 칸으로 가니 넣지 않습니다."""
    lines = [f"영업시간: {h}" for h in info.get("hours", [])]
    if info.get("closed"):
        lines.append(f"휴무: {info['closed']}")
    lines += [f"메뉴·가격: {m}" for m in info.get("menu", [])]
    for label, key in (("주차", "parking"), ("예약·대기", "reservation"), ("찾아가는 길", "transit")):
        if info.get(key):
            lines.append(f"{label}: {info[key]}")
    lines += [f"기타: {x}" for x in info.get("extra", [])]
    return "\n".join(lines)[:MAX_DETAILS]


def clean_link(raw) -> str:
    """네이버 지도·플레이스 링크만 받습니다(공유 → 링크 복사로 얻는 naver.me 짧은 주소 포함). 다른 주소는 빈 값."""
    m = re.search(r"https?://[^\s<>\"']+", str(raw or ""))
    if not m:
        return ""
    url = m.group(0).rstrip(".,)")[:300]
    host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
    return url if host in LINK_HOSTS else ""


MOCK_JSON = json.dumps({
    "name": "", "category": "돼지고기구이", "address": "서울 마포구 샘플로 12 1층", "phone": "02-123-4567",
    "hours": ["평일 11:30~22:00", "주말 11:00~21:30", "브레이크타임 15:00~17:00"], "closed": "매주 월요일",
    "menu": ["삼겹살 200g 17,000원", "목살 200g 17,000원", "된장찌개 5,000원"], "parking": "건물 뒤 공영주차장 이용",
    "reservation": "네이버 예약 가능", "transit": "공덕역 5번 출구 도보 3분", "extra": ["포장 가능"],
}, ensure_ascii=False)
