"""뉴스 기사 URL 에서 제목·언론사·날짜·본문을 읽어 옵니다(투자 생각·정보글의 참고 자료용).

- 표준 라이브러리만 씁니다(설치할 것 없음). 네이버 뉴스(n.news.naver.com)는 본문 칸(dic_area)을 바로 찾고,
  그 밖의 사이트는 <article> 또는 문단(<p>)을 모아 본문으로 씁니다.
- 로그인·유료 기사, 자바스크립트로만 본문을 그리는 사이트는 본문을 못 읽을 수 있습니다. 그럴 땐 기사 내용을 메모에 붙여 넣으세요.
- 기사 원문은 AI에게 '요약 재료'로만 넘기고, 글에는 핵심만 내 말로 요약하고 출처를 밝힙니다(저작권).
"""
import ipaddress
import re
import socket
import urllib.request
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

TIMEOUT = 10
MAX_BYTES = 3 * 1024 * 1024
MAX_TEXT = 6000  # AI에게 넘길 본문 최대 글자 수
MAX_NEWS = 3     # 한 글에 붙일 수 있는 기사 수
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

BODY_IDS = ("dic_area", "newsct_article", "articleBodyContents", "articeBody", "article-view-content-div", "article_body", "articleBody")
SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "button", "form", "nav", "footer", "header", "aside", "figcaption"}
VOID_TAGS = {"br", "img", "hr", "input", "link", "source", "wbr", "area", "col", "embed", "param", "track"}
BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "section", "article", "tr", "blockquote"}


class FetchError(ValueError):
    """화면에 그대로 보여 줄 수 있는 안내 문구를 담은 오류"""


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._target_depth = 0     # 본문 칸(id) 안에 있을 때 깊이
        self._article_depth = 0    # <article> 안에 있을 때 깊이
        self.target: list[str] = []
        self.article: list[str] = []
        self.paras: list[str] = []
        self._p: list[str] | None = None
        self.date_attr = ""

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
            return
        if tag in VOID_TAGS:  # 닫는 태그가 없는 태그는 깊이 계산에서 뺌
            if tag == "br":
                self._newline()
            return
        if tag == "title":
            self._in_title = True
        if tag in SKIP_TAGS:
            self._skip += 1
        if a.get("data-date-time") and not self.date_attr:  # 네이버 뉴스 입력 시각
            self.date_attr = a["data-date-time"]
        if self._target_depth:
            self._target_depth += 1
        elif a.get("id") in BODY_IDS or a.get("itemprop") == "articleBody":
            self._target_depth = 1
        if self._article_depth:
            self._article_depth += 1
        elif tag == "article":
            self._article_depth = 1
        if tag == "p":
            self._p = []
        if tag in BLOCK_TAGS:
            self._newline()

    def handle_startendtag(self, tag, attrs):
        if tag == "meta":
            self.handle_starttag(tag, attrs)
        elif tag == "br":
            self._newline()

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if tag == "title":
            self._in_title = False
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "p" and self._p is not None:
            text = _clean(" ".join(self._p))
            if len(text) >= 30:
                self.paras.append(text)
            self._p = None
        if tag in BLOCK_TAGS:
            self._newline()
        if self._target_depth:
            self._target_depth -= 1
        if self._article_depth:
            self._article_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if self._target_depth:
            self.target.append(data)
        if self._article_depth:
            self.article.append(data)
        if self._p is not None:
            self._p.append(data)

    def _newline(self):
        if self._target_depth:
            self.target.append("\n")
        if self._article_depth:
            self.article.append("\n")


def _clean(text: str) -> str:
    text = unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _decode(raw: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if not m:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
    enc = (m.group(1).decode() if m and isinstance(m.group(1), bytes) else (m.group(1) if m else "utf-8")).lower()
    if enc in ("euc-kr", "ks_c_5601-1987", "ksc5601"):
        enc = "cp949"
    try:
        return raw.decode(enc)
    except (LookupError, UnicodeDecodeError):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp949", errors="replace")


def check_url(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchError("기사 주소는 http:// 또는 https:// 로 시작해야 해요.")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except OSError:
        raise FetchError("기사 주소의 사이트를 찾을 수 없어요. 주소를 다시 확인해 주세요.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise FetchError("내 컴퓨터·사내망 주소는 읽을 수 없어요. 인터넷 뉴스 기사 주소를 넣어 주세요.")
    return url


def _download(url: str) -> tuple[bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read(MAX_BYTES + 1)
            return raw[:MAX_BYTES], resp.headers.get("Content-Type", ""), resp.geturl()
    except Exception as e:  # 네트워크·차단·404 등은 사용자가 이해할 수 있는 말로
        raise FetchError(f"기사를 불러오지 못했어요({type(e).__name__}). 주소를 확인하거나, 기사 내용을 메모에 붙여 넣어 주세요.")


def parse_article(html: str, url: str) -> dict:
    ex = _Extractor()
    ex.feed(html)
    meta = ex.meta
    title = _clean(meta.get("og:title") or meta.get("twitter:title") or ex.title)
    source = _clean(meta.get("og:article:author") or meta.get("og:site_name") or meta.get("article:author") or urlparse(url).hostname or "")
    source = source.split("|")[0].strip()  # '연합뉴스 | 네이버' → '연합뉴스'
    if source.startswith("http"):
        source = urlparse(url).hostname or ""
    published = (meta.get("article:published_time") or meta.get("og:regdate") or meta.get("pubdate") or ex.date_attr or "")[:16]
    text = _clean("".join(ex.target))
    if len(text) < 200:
        art = _clean("".join(ex.article))
        text = art if len(art) > len(text) else text
    if len(text) < 200 and ex.paras:
        joined = "\n\n".join(ex.paras)
        text = joined if len(joined) > len(text) else text
    if len(text) < 80:
        text = _clean(meta.get("og:description") or meta.get("description") or text)
    return {"url": url, "title": title[:200], "source": source[:60], "published": published.replace("T", " "), "text": text[:MAX_TEXT]}


def fetch_article(url: str) -> dict:
    url = check_url(url)
    raw, ctype, final = _download(url)
    if "html" not in ctype.lower() and not raw.lstrip()[:20].lower().startswith((b"<!doctype", b"<html")):
        raise FetchError("뉴스 기사(웹페이지) 주소가 아니에요.")
    art = parse_article(_decode(raw, ctype), final or url)
    if len(art["text"]) < 80:
        raise FetchError("기사 본문을 읽지 못했어요(유료·로그인 기사이거나 특수한 페이지일 수 있어요). 기사 내용을 메모에 붙여 넣어 주세요.")
    return art


def read_news_list(raw) -> list[dict]:
    """브라우저가 보낸 기사 목록(미리보기 결과)을 검사해 돌려줍니다."""
    if not raw:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_NEWS:
        raise ValueError(f"참고 기사는 최대 {MAX_NEWS}개까지 붙일 수 있어요.")
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", "")).strip()[:MAX_TEXT]
        if not text:
            continue
        out.append({"url": str(it.get("url", ""))[:500], "title": str(it.get("title", ""))[:200],
                    "source": str(it.get("source", ""))[:60], "published": str(it.get("published", ""))[:20], "text": text})
    return out
