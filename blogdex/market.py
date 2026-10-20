"""오늘 시황 불러오기: 주요 지수·환율·원자재·비트코인의 최신 값과 등락률을 가져와 메모에 넣을 글로 만듭니다.

- 출처는 Yahoo Finance 의 공개 차트 주소(비공식)이고, 코스피·코스닥은 네이버 증권 값도 함께 확인해 더 최신인 쪽을 씁니다.
  키가 필요 없지만, 사이트 사정으로 막히거나 바뀔 수 있습니다. 그때는 오류 안내가 나오고, 시황은 직접 적으면 됩니다.
- 조회 시각을 기준으로 가장 최근 값을 씁니다. 장이 끝난 시장은 '마지막 거래일 종가', 거래 중인 시장(환율·원자재·비트코인 등)은
  '조회 시점 현재 값'으로 적고, 등락률은 직전 거래일 종가 대비입니다.
- 목록(SYMBOLS)은 자유롭게 고쳐도 됩니다. (이름, 야후 기호, 소수 자리, 단위, 네이버 지수 코드)
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

SYMBOLS = [
    ("코스피", "^KS11", 2, "", "KOSPI"),
    ("코스닥", "^KQ11", 2, "", "KOSDAQ"),
    ("S&P 500", "^GSPC", 2, "", ""),
    ("나스닥", "^IXIC", 2, "", ""),
    ("다우존스", "^DJI", 2, "", ""),
    ("원/달러 환율", "KRW=X", 1, "원", ""),
    ("WTI 유가", "CL=F", 2, "달러", ""),
    ("금", "GC=F", 1, "달러", ""),
    ("비트코인", "BTC-USD", 0, "달러", ""),
]
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10d&interval=1d"
NAVER_URL = "https://m.stock.naver.com/api/index/{code}/basic"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 8
KST = timezone(timedelta(hours=9))
LIVE_WINDOW = timedelta(minutes=30)  # 마지막 값이 이보다 최근이면 '거래 중(현재 값)'으로 봄


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read(2 * 1024 * 1024).decode("utf-8"))


def _label(when: datetime, local_tz, now: datetime) -> tuple[str, bool]:
    """'10/20 종가' / '현지 10/20 종가' / '10/21 07:14 현재'"""
    if now - when <= LIVE_WINDOW:
        return f"{when.astimezone(KST):%m/%d %H:%M} 현재", True
    local = when.astimezone(local_tz)
    return (f"{local:%m/%d} 종가" if local.utcoffset() == KST.utcoffset(None) else f"현지 {local:%m/%d} 종가"), False


def parse_chart(data: dict, now: datetime | None = None) -> dict | None:
    """야후 차트 응답 → 최신 값·직전 거래일 종가·등락률·기준 시각.
    최신 값은 meta.regularMarketPrice(일봉의 마지막 종가가 비어 있거나 늦게 채워져도 최신)를 우선 씁니다."""
    now = now or datetime.now(timezone.utc)
    try:
        res = data["chart"]["result"][0]
        meta = res.get("meta") or {}
        stamps = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
    except (KeyError, IndexError, TypeError):
        return None
    tz = timezone(timedelta(seconds=int(meta.get("gmtoffset") or 0)))
    bars = [(datetime.fromtimestamp(t, timezone.utc), c) for t, c in zip(stamps, closes) if c is not None]
    price, ptime = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if price is not None and ptime:
        last_t, last = datetime.fromtimestamp(int(ptime), timezone.utc), float(price)
        if bars and bars[-1][0] > last_t:  # 메타가 일봉보다 오래됐으면 일봉을 씀
            last_t, last = bars[-1]
    elif bars:
        last_t, last = bars[-1]
    else:
        return None
    day = last_t.astimezone(tz).date()
    prevs = [c for t, c in bars if t.astimezone(tz).date() < day]  # 직전 거래일 종가
    if not prevs:
        return None
    prev = prevs[-1]
    label, live = _label(last_t, tz, now)
    return {"close": last, "prev": prev, "pct": (last - prev) / prev * 100 if prev else 0.0,
            "at": last_t.isoformat(), "label": label, "live": live, "source": "Yahoo Finance"}


def _num(v) -> float:
    return float(str(v).replace(",", "").replace("%", "").strip())


def parse_naver_index(data: dict, now: datetime | None = None) -> dict | None:
    """네이버 증권 지수 응답(코스피·코스닥) → parse_chart 와 같은 모양. 형식이 다르면 None."""
    now = now or datetime.now(timezone.utc)
    try:
        last = _num(data["closePrice"])
        pct = _num(data["fluctuationsRatio"])
        when = datetime.fromisoformat(str(data["localTradedAt"]))
    except (KeyError, TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=KST)
    live = str(data.get("marketStatus", "")).upper() == "OPEN"
    label = f"{when.astimezone(KST):%m/%d %H:%M} 현재" if live else f"{when.astimezone(KST):%m/%d} 종가"
    return {"close": last, "prev": last / (1 + pct / 100), "pct": pct, "at": when.astimezone(timezone.utc).isoformat(),
            "label": label, "live": live, "source": "네이버 증권"}


def fetch_snapshot(get_json=_get_json, now: datetime | None = None) -> dict:
    """{items: [{name, close, pct, label, unit, digits, source}], failed: [이름], fetched_at, source}"""
    now = now or datetime.now(timezone.utc)
    items, failed = [], []
    for name, sym, digits, unit, naver in SYMBOLS:
        cands = []
        for url, parse in ([(CHART_URL.format(sym=urllib.request.quote(sym)), parse_chart)]
                           + ([(NAVER_URL.format(code=naver), parse_naver_index)] if naver else [])):
            try:
                q = parse(get_json(url), now)
            except Exception:
                q = None
            if q:
                cands.append(q)
        if cands:
            best = max(cands, key=lambda q: q["at"])  # 두 출처 중 더 최신 값
            items.append({"name": name, "digits": digits, "unit": unit, **best})
        else:
            failed.append(name)
    sources = list(dict.fromkeys(it["source"] for it in items)) or ["Yahoo Finance"]
    return {"items": items, "failed": failed, "fetched_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"), "source": ", ".join(sources)}


def to_memo(snap: dict) -> str:
    """메모에 붙일 글. 이 블록의 숫자는 '메모에 있는 사실'로 취급되어 글에 쓸 수 있습니다."""
    lines = [f"[자동 시황 - {snap['fetched_at']} 조회(한국 시간), 출처: {snap['source']}, 등락률은 직전 거래일 종가 대비]"]
    for it in snap["items"]:
        val = f"{it['close']:,.{it['digits']}f}{it['unit']}"
        lines.append(f"- {it['name']} {val} ({it['pct']:+.2f}%, {it.get('label') or it.get('date', '')})")
    if snap["failed"]:
        lines.append(f"- (불러오지 못함: {', '.join(snap['failed'])})")
    return "\n".join(lines)
