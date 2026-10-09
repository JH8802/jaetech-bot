"""블로그 원고 생성 웹 서버 (개인용).

실행:  python blogdex/app.py   →  http://127.0.0.1:5000
API 키는 서버(.env)에만 두고, 브라우저에는 내려보내지 않습니다.
"""
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import anthropic
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from werkzeug.exceptions import HTTPException

import eval_style
import llm
import postprocess
import prompts
import storage

MAX_TITLE = 200
MAX_MEMO = 4000
MAX_KEYWORDS = 8
EVIDENCE_MODES = {"strict", "template"}

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


# ---------- 공통 ----------
def friendly_error(e: Exception) -> tuple[str, int]:
    if isinstance(e, (llm.RefusedError, llm.TruncatedError)):
        return str(e), 422
    if isinstance(e, ValueError):
        return str(e), 400
    if isinstance(e, anthropic.AuthenticationError):
        return "API 키가 올바르지 않아요. .env 의 ANTHROPIC_API_KEY를 확인하세요.", 500
    if isinstance(e, anthropic.RateLimitError):
        return "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.", 429
    if isinstance(e, anthropic.APIConnectionError):
        return "Claude 서버에 연결하지 못했어요. 네트워크를 확인하세요.", 502
    if isinstance(e, anthropic.APIStatusError):
        return f"Claude API 오류({e.status_code}): {e.message}", 502
    if isinstance(e, RuntimeError):
        return str(e), 500
    return "서버 오류가 발생했어요.", 500


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        msg = "요청이 너무 커요." if e.code == 413 else e.description
        return jsonify(error=msg), e.code
    msg, code = friendly_error(e)
    if code == 500 and not isinstance(e, RuntimeError):
        app.logger.exception("unexpected error")
    return jsonify(error=msg), code


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(gen) -> Response:
    return Response(stream_with_context(gen), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def read_place(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw.get(k, "")).strip()[:200] for k in ("name", "category", "address", "phone")}


def read_common(data: dict) -> dict:
    kind = data.get("kind", "info")
    if kind not in prompts.KINDS:
        raise ValueError("알 수 없는 글 종류입니다.")
    memo = str(data.get("memo", "")).strip()
    if len(memo) > MAX_MEMO:
        raise ValueError(f"메모는 {MAX_MEMO:,}자 이내로 입력해 주세요.")
    evidence = data.get("evidence_mode", "strict")
    if evidence not in EVIDENCE_MODES:
        raise ValueError("경험 서술 모드가 올바르지 않아요.")
    return {
        "kind": kind,
        "memo": memo,
        "place": read_place(data.get("place")) if kind == "food" else {},
        "guardrail": bool(data.get("guardrail", False)),
        "evidence_mode": evidence,
    }


# ---------- 화면 / 매장 검색 ----------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/favicon.ico")
def favicon():
    return "", 204


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


@app.get("/api/places")
def places():
    """매장 이름으로 주소를 검색합니다. (네이버 검색 API - 지역)
    .env 에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 있어야 동작합니다."""
    query = request.args.get("query", "").strip()
    if not query:
        raise ValueError("매장 이름을 입력해 주세요.")
    if len(query) > 100:
        raise ValueError("매장 이름은 100자 이내로 입력해 주세요.")
    if llm.is_mock():
        return jsonify(places=[{"name": f"{query} 본점", "category": "한식", "address": "서울 마포구 샘플로 1", "phone": ""}])
    cid, secret = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 .env에 없어서 매장 검색을 쓸 수 없어요. 아래 '직접 입력'을 이용하세요.")
    url = "https://openapi.naver.com/v1/search/local.json?" + urllib.parse.urlencode({"query": query, "display": 5})
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret})
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            items = json.load(res).get("items", [])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"네이버 검색 API 오류({e.code}). 키와 '검색' API 사용 설정을 확인하세요.") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError("네이버 검색 서버에 연결하지 못했어요.") from e
    return jsonify(places=[{
        "name": strip_tags(it.get("title")),
        "category": strip_tags(it.get("category")).split(">")[-1].strip(),
        "address": strip_tags(it.get("roadAddress") or it.get("address")),
        "phone": strip_tags(it.get("telephone")),
    } for it in items])


# ---------- 제목 ----------
def clean_title(line: str) -> str:
    line = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", line)
    return line.strip().strip("\"'“”‘’")


@app.post("/api/titles")
def titles():
    data = request.get_json(silent=True) or {}
    c = read_common(data)
    keyword = str(data.get("keyword", "")).strip()
    if not keyword:
        raise ValueError("주제나 키워드를 먼저 입력해 주세요.")
    if len(keyword) > MAX_TITLE:
        raise ValueError(f"주제는 {MAX_TITLE}자 이내로 입력해 주세요.")
    exclude = [str(x)[:MAX_TITLE] for x in (data.get("exclude") or [])][:15]
    system = prompts.BASE_ROLE
    user = prompts.build_title_prompt(c["kind"], keyword, c["memo"], c["place"], exclude, c["guardrail"])
    text = llm.ask_text(system, user, max_tokens=1024, effort="low")
    result = [t for t in (clean_title(l) for l in text.splitlines()) if t][:5]
    return jsonify(titles=result, keywords=prompts.derive_keywords(c["kind"], keyword, c["place"]))


# ---------- 원고 ----------
def _generate_events(*, kind, title, keywords, memo, place, guardrail, evidence_mode, user_prompt, parent_id=None, title_input=None):
    """원고를 스트리밍으로 만들고, 후처리·점검·저장 후 SSE 이벤트를 흘려보냅니다."""
    system = prompts.build_system(kind, guardrail, evidence_mode)
    parts = []
    try:
        yield sse("status", {"text": "원고를 쓰고 있어요."})
        for chunk in llm.stream_text(system, user_prompt, max_tokens=16000):
            parts.append(chunk)
            yield sse("chunk", {"text": chunk})
        yield sse("status", {"text": "태그와 해시태그를 정리하고 품질을 점검하고 있어요."})
        fin = postprocess.finalize(kind, "".join(parts), place, keywords)
        quality = eval_style.evaluate(kind, fin["body"], keywords, memo)
        yield sse("replace", {"text": fin["body"]})
        article_id = storage.save_article(
            kind=kind, title_input=title_input or title, title_final=title, memo=memo, place=place, keywords=keywords,
            options={"guardrail": guardrail, "evidence_mode": evidence_mode}, body=fin["body"], chars=fin["chars"],
            quality=quality, model="mock" if llm.is_mock() else llm.MODEL, parent_id=parent_id)
        yield sse("done", {"article_id": article_id, "title": title, "body": fin["body"], "chars": fin["chars"],
                           "quality": quality, "notes": fin["notes"]})
    except Exception as e:  # 스트림 중 오류는 SSE 로 알려 줍니다.
        msg, _ = friendly_error(e)
        if not isinstance(e, (ValueError, RuntimeError, llm.RefusedError, llm.TruncatedError)):
            app.logger.exception("stream error")
        yield sse("error", {"message": msg})


@app.post("/api/articles/stream")
def article_stream():
    data = request.get_json(silent=True) or {}
    c = read_common(data)
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("원고 제목을 입력해 주세요.")
    if len(title) > MAX_TITLE:
        raise ValueError(f"제목은 {MAX_TITLE}자 이내로 입력해 주세요.")
    keywords = [str(k).strip()[:40] for k in (data.get("keywords") or []) if str(k).strip()][:MAX_KEYWORDS]
    if not keywords:
        keywords = prompts.derive_keywords(c["kind"], title, c["place"])
    user_prompt = prompts.build_article_prompt(c["kind"], title, keywords, c["memo"], c["place"])
    return sse_response(_generate_events(kind=c["kind"], title=title, keywords=keywords, memo=c["memo"], place=c["place"],
                                         guardrail=c["guardrail"], evidence_mode=c["evidence_mode"], user_prompt=user_prompt))


@app.post("/api/articles/<int:article_id>/rewrite")
def article_rewrite(article_id: int):
    art = storage.get_article(article_id)
    if not art:
        raise ValueError("원고를 찾을 수 없어요.")
    issues = (art["quality"] or {}).get("issues", [])
    if not issues:
        raise ValueError("품질 점검에서 고칠 점이 없어요.")
    opts = art["options"] or {}
    user_prompt = prompts.build_rewrite_prompt(art["kind"], art["body"], issues, art["keywords"])
    return sse_response(_generate_events(
        kind=art["kind"], title=art["title"], keywords=art["keywords"], memo=art["memo"], place=art["place"],
        guardrail=bool(opts.get("guardrail")), evidence_mode=opts.get("evidence_mode", "strict"),
        user_prompt=user_prompt, parent_id=article_id, title_input=art["title_input"]))


@app.get("/api/articles")
def articles_list():
    return jsonify(articles=storage.list_articles())


@app.get("/api/articles/<int:article_id>")
def articles_get(article_id: int):
    art = storage.get_article(article_id)
    if not art:
        return jsonify(error="원고를 찾을 수 없어요."), 404
    return jsonify(article=art)


@app.delete("/api/articles")
def articles_delete():
    ids = [int(i) for i in (request.get_json(silent=True) or {}).get("ids", []) if str(i).isdigit()]
    return jsonify(deleted=storage.delete_articles(ids))


if __name__ == "__main__":
    # 본인 PC에서만 접속되도록 127.0.0.1 로 고정 (외부 공개 시 로그인/사용량 제한을 먼저 붙여야 합니다)
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False, threaded=True)
