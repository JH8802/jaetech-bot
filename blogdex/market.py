"""오늘 시황 불러오기: 주요 지수·환율·원자재·비트코인의 최근 종가와 등락률을 가져와 메모에 넣을 글로 만듭니다.

- 출처는 Yahoo Finance 의 공개 차트 주소(비공식)입니다. 키가 필요 없지만, 사이트 사정으로 막히거나 바뀔 수 있습니다.
  그때는 오류 안내가 나오고, 시황은 직접 적으면 됩니다.
- 숫자는 '마지막 종가(또는 최근 값)'와 '그 전 종가 대비 등락률'입니다. 장중 실시간 값과 다를 수 있어 날짜를 함께 적습니다.
- 목록(SYMBOLS)은 자유롭게 고쳐도 됩니다. (이름, 야후 기호, 소수 자리, 단위)
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

SYMBOLS = [
    ("코스피", "^KS11", 2, ""),
    ("코스닥", "^KQ11", 2, ""),
    ("S&P 500", "^GSPC", 2, ""),
    ("나스닥", "^IXIC", 2, ""),
    ("다우존스", "^DJI", 2, ""),
    ("원/달러 환율", "KRW=X", 1, "원"),
    ("WTI 유가", "CL=F", 2, "달러"),
    ("금", "GC=F", 1, "달러"),
    ("비트코인", "BTC-USD", 0, "달러"),
]
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10d&interval=1d"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 8
SOURCE = "Yahoo Finance"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read(2 * 1024 * 1024).decode("utf-8"))


def parse_chart(data: dict) -> dict | None:
    """차트 응답에서 마지막 종가·전 종가·날짜를 뽑습니다. 값이 모자라면 None."""
    try:
        res = data["chart"]["result"][0]
        stamps = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
        offset = int(res.get("meta", {}).get("gmtoffset") or 0)
    except (KeyError, IndexError, TypeError):
        return None
    pts = [(t, c) for t, c in zip(stamps, closes) if c is not None]
    if len(pts) < 2:
        return None
    (t_prev, prev), (t_last, last) = pts[-2], pts[-1]
    day = datetime.fromtimestamp(t_last, timezone(timedelta(seconds=offset)))
    return {"close": last, "prev": prev, "pct": (last - prev) / prev * 100 if prev else 0.0, "date": day.strftime("%m/%d")}


def fetch_snapshot(get_json=_get_json) -> dict:
    """{items: [{name, close, pct, date, unit, digits}], failed: [이름], fetched_at, source}"""
    items, failed = [], []
    for name, sym, digits, unit in SYMBOLS:
        try:
            q = parse_chart(get_json(CHART_URL.format(sym=urllib.request.quote(sym))))
        except Exception:
            q = None
        if q:
            items.append({"name": name, "digits": digits, "unit": unit, **q})
        else:
            failed.append(name)
    return {"items": items, "failed": failed, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": SOURCE}


def to_memo(snap: dict) -> str:
    """메모에 붙일 글. 이 블록의 숫자는 '메모에 있는 사실'로 취급되어 글에 쓸 수 있습니다."""
    lines = [f"[자동 시황 - {snap['fetched_at']} 조회, 출처: {snap['source']}, 최근 종가와 전일 대비]"]
    for it in snap["items"]:
        val = f"{it['close']:,.{it['digits']}f}{it['unit']}"
        lines.append(f"- {it['name']} {val} ({it['pct']:+.2f}%, {it['date']} 기준)")
    if snap["failed"]:
        lines.append(f"- (불러오지 못함: {', '.join(snap['failed'])})")
    return "\n".join(lines)
