"""구글 자동완성으로 키워드 찾기 (무료, API 키 필요 없음).

사람들이 구글 검색창에 실제로 이어서 치는 검색어를 모아서 보여준다.
- 기본 검색어 + 뒤에 붙는 말(방법·차이·기준·부작용 …)로 여러 번 물어보고, 겹치는 건 하나로 합친다
- 검색량은 알려주지 않는다 → 고른 키워드들을 구글 키워드 플래너 '검색량 및 예측 가져오기'에 붙여넣어 확인
- 구글이 공식 API로 제공하는 기능이 아니라서, 구글이 방식을 바꾸면 갑자기 안 될 수 있다
"""
import json
import time
import urllib.parse
import urllib.request

from blog_sources import USER_AGENT

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"

# 검색 의도별로 뒤에 붙여볼 말 (그룹 이름 → 붙일 말들)
INTENT_SUFFIXES = {
    "🔎 그대로 이어지는 검색어": ["", " "],
    "🛠 방법·확인": ["방법", "확인", "보는법"],
    "⚖️ 비교·선택": ["차이", "비교", "추천", "고르는법"],
    "📏 기준·규정": ["기준", "표시", "법"],
    "⚠️ 문제·주의": ["부작용", "문제", "주의"],
}
REQUEST_GAP = 0.25  # 구글에 너무 빨리 연달아 묻지 않도록 (초)


def _decode(raw, content_type):
    charset = "utf-8"
    if "charset=" in (content_type or ""):
        charset = content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    for enc in (charset, "utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_suggestions(query, timeout=8):
    """검색어 하나에 대한 구글 자동완성 목록 (한국어·한국 기준)."""
    params = urllib.parse.urlencode({
        "client": "firefox", "hl": "ko", "gl": "kr", "ie": "UTF-8", "oe": "UTF-8", "q": query,
    })
    req = urllib.request.Request(f"{SUGGEST_URL}?{params}",
                                 headers={"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = _decode(resp.read(), resp.headers.get("Content-Type", ""))
    data = json.loads(text)
    # 응답 모양: ["검색어", ["자동완성1", "자동완성2", ...], ...]
    if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
        return []
    return [s.strip() for s in data[1] if isinstance(s, str) and s.strip()]


def _norm(text):
    return " ".join(text.split()).lower()


def expand_keyword(seed, fetch=fetch_suggestions, gap=REQUEST_GAP):
    """기본 검색어를 여러 방향으로 넓혀서 자동완성을 모은다.
    돌려주는 값: {"groups": {그룹명: [검색어, …]}, "all": [중복 없는 전체 목록], "failed": 실패한 요청 수}
    전부 실패하면 RuntimeError (인터넷 연결·구글 차단 등)."""
    seed = " ".join(seed.split())
    if not seed:
        return {"groups": {}, "all": [], "failed": 0}
    seen = {_norm(seed)}
    groups, all_items = {}, []
    tried = failed = 0
    last_error = None
    for group, suffixes in INTENT_SUFFIXES.items():
        items = []
        for suffix in suffixes:
            query = seed + suffix if suffix in ("", " ") else f"{seed} {suffix}"
            if tried:
                time.sleep(gap)
            tried += 1
            try:
                found = fetch(query)
            except Exception as e:  # 한두 개 실패는 넘어가고, 전부 실패할 때만 알림
                failed += 1
                last_error = e
                continue
            for s in found:
                key = _norm(s)
                if key in seen:
                    continue
                seen.add(key)
                items.append(s)
                all_items.append(s)
        if items:
            groups[group] = items
    if failed == tried:
        raise RuntimeError(f"구글 자동완성을 불러오지 못했어 ({last_error})")
    return {"groups": groups, "all": all_items, "failed": failed}


def google_search_url(keyword):
    """이 키워드로 구글 검색한 결과 페이지 주소 (한국어·한국 기준)."""
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": keyword, "hl": "ko", "gl": "kr"})
