"""블덱스라이터 BETA 재현용 로컬 웹 서버.

실행:  python blogdex/app.py   →  http://127.0.0.1:5000
API 키는 서버(.env)에만 두고, 브라우저에는 절대 내려보내지 않습니다.
"""
import base64
import binascii
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from prompts import POST_TYPES, SYSTEM_PROMPT, build_article_prompt, build_title_prompt, format_place

load_dotenv()

# 모델은 .env 의 BLOGDEX_MODEL 로 바꿀 수 있습니다. (비용 절감: claude-sonnet-5-5 등)
MODEL = os.getenv("BLOGDEX_MODEL", "claude-opus-5-5")
# BLOGDEX_MOCK=1 이면 API를 호출하지 않고 샘플 결과를 돌려줍니다. (화면 테스트용, 비용 0원)
MOCK = os.getenv("BLOGDEX_MOCK") == "1"
# 안전 분류기 거절 시 서버가 대체 모델로 자동 재시도하는 기능을 지원하는 모델들
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

MAX_KEYWORD = 200
MAX_EXTRA = 2000
MAX_PHOTOS = 10                        # 프런트엔드(index.html)의 MAX_PHOTOS와 같게 유지
MAX_PHOTO_BYTES = 3 * 1024 * 1024      # 사진 1장당 (브라우저에서 1280px로 줄여 보내므로 보통 0.5MB 이하)
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        _client = anthropic.Anthropic()
    return _client


def ask_claude(user_prompt: str, max_tokens: int, effort: str, photos: list | None = None) -> str:
    """Claude를 1회 호출해 텍스트만 돌려줍니다. photos가 있으면 사진을 함께 보여줍니다."""
    content: list | str = user_prompt
    if photos:
        content = []
        for i, p in enumerate(photos, 1):
            content.append({"type": "text", "text": f"사진 {i}"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": p["media_type"], "data": p["data"]}})
        content.append({"type": "text", "text": user_prompt})
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort},
    )
    if MODEL in FALLBACK_MODELS:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    response = get_client().beta.messages.create(**kwargs)

    if response.stop_reason == "refusal":
        raise ValueError("이 주제는 AI가 작성을 거절했어요. 주제나 표현을 바꿔서 다시 시도해 주세요.")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise ValueError("AI 응답이 비어 있어요. 다시 시도해 주세요.")
    return text


def read_json():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind", "info")
    if kind not in POST_TYPES:
        raise ValueError("알 수 없는 글 종류입니다.")
    extra = str(data.get("extra", "")).strip()
    if len(extra) > MAX_EXTRA:
        raise ValueError(f"추가 정보는 {MAX_EXTRA}자 이내로 입력해 주세요.")
    if kind == "custom" and not extra:
        raise ValueError("커스텀은 '커스텀 지침'을 입력해야 해요.")
    # 맛집글: 지도 검색으로 고른 매장 정보를 '확인된 사실'로 앞에 붙임 (AI가 주소를 지어내지 않도록)
    place = data.get("place")
    if kind == "food" and isinstance(place, dict):
        clean = {k: str(place.get(k, ""))[:200] for k in ("name", "category", "address", "phone")}
        if clean["name"]:
            extra = (format_place(clean) + "\n\n" + extra).strip()
    return data, kind, extra


def read_photos(data: dict) -> list:
    """요청의 photos([{media_type, data(base64)}])를 검증해서 돌려줍니다."""
    raw = data.get("photos") or []
    if not isinstance(raw, list):
        raise ValueError("사진 형식이 올바르지 않아요.")
    if len(raw) > MAX_PHOTOS:
        raise ValueError(f"사진은 최대 {MAX_PHOTOS}장까지 올릴 수 있어요.")
    photos = []
    for p in raw:
        if not isinstance(p, dict) or p.get("media_type") not in PHOTO_TYPES:
            raise ValueError("지원하지 않는 사진 형식이에요. (JPG, PNG, WEBP, GIF만 가능)")
        b64 = str(p.get("data", ""))
        try:
            size = len(base64.b64decode(b64, validate=True))
        except (binascii.Error, ValueError):
            raise ValueError("사진 데이터가 손상됐어요. 다시 올려주세요.") from None
        if size > MAX_PHOTO_BYTES:
            raise ValueError("사진 한 장의 용량이 너무 커요. (3MB 이하)")
        photos.append({"media_type": p["media_type"], "data": b64})
    return photos


def clean_title(line: str) -> str:
    line = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", line)  # 번호/불릿 제거
    return line.strip().strip("\"'“”‘’")


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):  # 404, 413(업로드 용량 초과) 등은 원래 상태코드 유지
        msg = "업로드 용량이 너무 커요. 사진 수를 줄여주세요." if e.code == 413 else e.description
        return jsonify(error=msg), e.code
    if isinstance(e, ValueError):
        return jsonify(error=str(e)), 400
    if isinstance(e, anthropic.AuthenticationError):
        return jsonify(error="API 키가 올바르지 않아요. .env 의 ANTHROPIC_API_KEY를 확인하세요."), 500
    if isinstance(e, anthropic.RateLimitError):
        return jsonify(error="요청이 너무 많아요. 잠시 후 다시 시도해 주세요."), 429
    if isinstance(e, anthropic.APIConnectionError):
        return jsonify(error="Claude 서버에 연결하지 못했어요. 네트워크를 확인하세요."), 502
    if isinstance(e, anthropic.APIStatusError):
        return jsonify(error=f"Claude API 오류({e.status_code}): {e.message}"), 502
    if isinstance(e, RuntimeError):  # 설정 누락 등 사용자에게 그대로 보여줄 안내 메시지
        return jsonify(error=str(e)), 500
    app.logger.exception("unexpected error")
    return jsonify(error="서버 오류가 발생했어요."), 500


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/types")
def types():
    return jsonify([{"key": k, "label": v["label"]} for k, v in POST_TYPES.items()])


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


@app.get("/api/places")
def places():
    """매장 이름으로 주소를 검색합니다. (네이버 검색 API - 지역)

    발급: https://developers.naver.com → 애플리케이션 등록 → '검색' API 선택
    .env 에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 을 넣으면 동작합니다.
    """
    query = request.args.get("query", "").strip()
    if not query:
        raise ValueError("매장 이름을 입력해 주세요.")
    if len(query) > 100:
        raise ValueError("매장 이름은 100자 이내로 입력해 주세요.")

    if MOCK:
        return jsonify(places=[{
            "name": f"{query} 본점", "category": "한식",
            "address": "서울특별시 마포구 백범로 170 (샘플)", "phone": "02-000-0000",
        }])

    cid, secret = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 .env에 없어서 매장 검색을 쓸 수 없어요.")

    url = "https://openapi.naver.com/v1/search/local.json?" + urllib.parse.urlencode({"query": query, "display": 5})
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            items = json.load(res).get("items", [])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"네이버 검색 API 오류({e.code}). 키와 '검색' API 사용 설정을 확인하세요.") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError("네이버 검색 서버에 연결하지 못했어요.") from e

    result = [{
        "name": strip_tags(it.get("title")),
        "category": strip_tags(it.get("category")).split(">")[-1].strip(),  # '음식점>한식' → '한식'
        "address": strip_tags(it.get("roadAddress") or it.get("address")),
        "phone": strip_tags(it.get("telephone")),
    } for it in items]
    return jsonify(places=result)


@app.post("/api/titles")
def titles():
    data, kind, extra = read_json()
    keyword = str(data.get("keyword", "")).strip()
    if not keyword:
        raise ValueError("주제나 키워드를 먼저 입력해 주세요.")
    if len(keyword) > MAX_KEYWORD:
        raise ValueError(f"주제는 {MAX_KEYWORD}자 이내로 입력해 주세요.")
    exclude = [str(x)[:MAX_KEYWORD] for x in (data.get("exclude") or [])][:15]

    if MOCK:
        return jsonify(titles=[f"[샘플] {keyword} 제목 후보 {i}" for i in range(1, 6)])

    text = ask_claude(build_title_prompt(kind, keyword, extra, exclude), max_tokens=1024, effort="low")
    result = [t for t in (clean_title(l) for l in text.splitlines()) if t][:5]
    return jsonify(titles=result)


@app.post("/api/article")
def article():
    data, kind, extra = read_json()
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("원고 제목을 입력해 주세요.")
    if len(title) > MAX_KEYWORD:
        raise ValueError(f"제목은 {MAX_KEYWORD}자 이내로 입력해 주세요.")

    photos = read_photos(data)

    if MOCK:
        marks = "".join(f"\n\n[사진 {i}]\n사진 {i}번 설명 문단입니다." for i in range(1, len(photos) + 1))
        return jsonify(text=f"{title}\n\n■ 샘플 소제목\n화면 테스트용 샘플 원고입니다.{marks}\n\n#샘플 #테스트")

    text = ask_claude(build_article_prompt(kind, title, extra, len(photos)), max_tokens=8000, effort="medium", photos=photos)
    return jsonify(text=text)


if __name__ == "__main__":
    # 본인 PC에서만 접속되도록 127.0.0.1 로 고정 (외부 공개 시 로그인/요금 제한 먼저 필요)
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
