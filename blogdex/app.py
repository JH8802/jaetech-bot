"""블로그 원고 생성 웹 서버 (개인용).

실행:  python blogdex/app.py   →  http://127.0.0.1:5000
API 키는 서버(.env)에만 두고, 브라우저에는 내려보내지 않습니다.
"""
import json
import os
import re
import subprocess

import anthropic
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from werkzeug.exceptions import HTTPException

import eval_style
import invest_guard
import llm
import market
import news
import postprocess
import prompts
import storage

MAX_TITLE = 200
MAX_MEMO = 4000
MAX_MEMO_BY_KIND = {"invest": 20000}  # 투자 생각: 못 읽은 기사 원문을 메모에 붙여 넣을 수 있게 넉넉히
MAX_KEYWORDS = 8
MAX_BODY = 60000
EXPAND_MIN = {"food": 2100, "hotel": 2400}  # 맛집글이 이 글자수에 못 미치면 사진·메모 안에서 한 번 더 풀어 씁니다(목표 기준 2,100자)
EXPAND_TARGET_EXTRA = 300  # 보강 시에는 모델이 덜 쓰는 경향을 감안해 기준보다 이만큼 더 쓰라고 요청
EVIDENCE_MODES = {"strict", "template"}

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # 사진 최대 30장(브라우저에서 줄인 JPEG) + 본문
MAX_PHOTOS = 30  # 가장 큰 한도(요청 크기 계산용)
PHOTO_LIMITS = {"info": 20, "food": 20, "hotel": 30, "invest": 10}  # 투자 생각: 그래프·리포트·캡처 같은 이미지 자료  # 글 종류별 사진 한도
VISION_BATCH = 10  # 사진 분석은 10장씩 나누어 호출(출력이 잘리거나 오래 걸리는 것을 막음)
MAX_PHOTO_BYTES = 3 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _code_version() -> str:
    """서버가 켜질 때의 코드 버전(git 커밋 앞 7자리). 업데이트 후 서버를 다시 켰는지 확인하는 용도입니다."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__)),
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


APP_VERSION = _code_version()


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
    limit = MAX_MEMO_BY_KIND.get(kind, MAX_MEMO)
    if len(memo) > limit:
        raise ValueError(f"메모는 {limit:,}자 이내로 입력해 주세요.")
    evidence = data.get("evidence_mode", "strict")
    if evidence not in EVIDENCE_MODES:
        raise ValueError("경험 서술 모드가 올바르지 않아요.")
    return {
        "kind": kind,
        "memo": memo,
        "place": read_place(data.get("place")) if kind in prompts.PLACE_KINDS else {},
        "guardrail": True if kind == "invest" else bool(data.get("guardrail", False)),  # 투자 글 가드레일은 끌 수 없음
        "evidence_mode": evidence,
    }


def read_ratings(data: dict, kind: str) -> list[dict]:
    """항목별 별점 [{label, score(1~5)}]. 맛집글·호텔·여행 후기만 쓰고, 점수가 없는 항목은 뺍니다."""
    if kind not in prompts.PLACE_KINDS:
        return []
    raw = data.get("ratings") or []
    if not isinstance(raw, list) or len(raw) > 8:
        raise ValueError("별점 항목은 최대 8개까지 넣을 수 있어요.")
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        label = re.sub(r"\s+", " ", str(r.get("label", ""))).strip()[:12]
        try:
            score = int(r.get("score"))
        except (TypeError, ValueError):
            continue
        if not label:
            continue
        if not 1 <= score <= 5:
            raise ValueError("별점은 1~5점으로 입력해 주세요.")
        out.append({"label": label, "score": score})
    return out


def read_photo_names(data: dict) -> list[str]:
    """브라우저가 보낸 사진 파일명(사진 순서와 같음). 화면에서 '사진 3 (IMG_0123.jpg)'로 보여 주는 용도입니다."""
    raw = data.get("photo_names") or []
    if not isinstance(raw, list):
        return []
    return [str(x)[:120] for x in raw]


def read_photos(data: dict, kind: str = "food") -> list[dict]:
    """브라우저가 줄여서 보낸 사진(data URL)을 읽어 [{'media_type','data'}] 로 돌려줍니다."""
    raw = data.get("photos") or []
    if not isinstance(raw, list):
        raise ValueError("사진 형식이 올바르지 않아요.")
    limit = PHOTO_LIMITS.get(kind, 20)
    if len(raw) > limit:
        raise ValueError(f"{prompts.KINDS[kind]['label']}은 사진을 최대 {limit}장까지 올릴 수 있어요. ({len(raw)}장 선택됨)")
    out = []
    for i, item in enumerate(raw, 1):
        m = re.match(r"^data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)$", item if isinstance(item, str) else "")
        if not m or m.group(1) not in PHOTO_TYPES:
            raise ValueError(f"사진 {i}번 형식을 읽을 수 없어요. JPG, PNG, WEBP 사진을 올려 주세요.")
        b64 = re.sub(r"\s", "", m.group(2))
        if len(b64) * 3 // 4 > MAX_PHOTO_BYTES:
            raise ValueError(f"사진 {i}번이 너무 커요. 다시 올려 주세요.")
        out.append({"media_type": m.group(1), "data": b64})
    return out


# ---------- 화면 / 매장 검색 ----------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/version")
def version():
    return jsonify(version=APP_VERSION)


STYLE_SCOPES = ["common", *prompts.KINDS]  # common: 모든 글 공통, 그 밖: 글 종류별(비어 있으면 공통을 씀)


def _style_key(scope: str) -> str:
    return "style_sample" if scope == "common" else f"style_sample:{scope}"


def style_for(kind: str) -> str:
    """글 종류별 말투 샘플이 있으면 그것을, 없으면 공통 샘플을 씁니다."""
    own = storage.get_setting(_style_key(kind))[0]
    return own if own.strip() else storage.get_setting("style_sample")[0]


@app.get("/api/style")
def style_get():
    samples = {}
    for scope in STYLE_SCOPES:
        text, updated = storage.get_setting(_style_key(scope))
        samples[scope] = {"text": text, "updated_at": updated}
    return jsonify(samples=samples, style_sample=samples["common"]["text"], updated_at=samples["common"]["updated_at"],
                   max_chars=prompts.MAX_STYLE_SAMPLE)


@app.put("/api/style")
def style_put():
    """말투 샘플을 저장합니다. scope 가 common 이면 모든 글 공통, 글 종류면 그 종류에만 쓰입니다(비우면 공통으로 돌아감)."""
    data = request.get_json(silent=True) or {}
    scope = data.get("scope") or "common"
    if scope not in STYLE_SCOPES:
        raise ValueError("말투를 저장할 글 종류가 올바르지 않아요.")
    text = str(data.get("style_sample", "")).replace("\r\n", "\n").strip()
    if len(text) > prompts.MAX_STYLE_SAMPLE:
        raise ValueError(f"말투 샘플은 {prompts.MAX_STYLE_SAMPLE:,}자 이내로 적어 주세요.")
    updated = storage.set_setting(_style_key(scope), text)
    return jsonify(scope=scope, style_sample=text, updated_at=updated)


@app.post("/api/news/preview")
def news_preview():
    """기사 주소를 읽어 제목·언론사·날짜·본문 앞부분을 돌려줍니다. 화면에서 확인한 뒤 원고 생성에 함께 보냅니다."""
    url = str((request.get_json(silent=True) or {}).get("url", "")).strip()[:1000]
    if llm.is_mock():
        return jsonify(article={"url": url, "title": "샘플 기사 제목", "source": "샘플일보", "published": "2026-10-20",
                                "text": "샘플 기사 본문입니다. 지수가 1% 올랐다고 보도했습니다."})
    try:
        return jsonify(article=news.fetch_article(url))
    except news.FetchError as e:
        raise ValueError(str(e))


@app.get("/api/market")
def market_snapshot():
    """오늘 시황(주요 지수·환율·원자재·비트코인)을 불러와 메모에 넣을 글로 돌려줍니다."""
    if llm.is_mock():
        snap = {"items": [{"name": "코스피", "close": 2600.0, "pct": 0.5, "label": "10/20 종가", "digits": 2, "unit": "", "source": "샘플"}],
                "failed": [], "fetched_at": "2026-10-20 09:00", "source": "샘플"}
    else:
        snap = market.fetch_snapshot()
    if not snap["items"]:
        raise ValueError("시황을 불러오지 못했어요(인터넷 연결이나 데이터 제공 사이트 사정일 수 있어요). 잠시 뒤 다시 시도하거나 직접 적어 주세요.")
    return jsonify(memo=market.to_memo(snap), **snap)


@app.get("/api/rating-labels")
def rating_labels_get():
    raw, _ = storage.get_setting("rating_labels", "{}")
    try:
        return jsonify(labels=json.loads(raw))
    except ValueError:
        return jsonify(labels={})


@app.put("/api/rating-labels")
def rating_labels_put():
    """종류별 별점 항목 이름(예: 맛집글 [맛, 가격, …])을 저장합니다. 언제든 바꿀 수 있습니다."""
    labels = (request.get_json(silent=True) or {}).get("labels") or {}
    clean = {}
    for kind in prompts.PLACE_KINDS:
        items = labels.get(kind)
        if isinstance(items, list):
            clean[kind] = [re.sub(r"\s+", " ", str(x)).strip()[:12] for x in items[:8]]
    storage.set_setting("rating_labels", json.dumps(clean, ensure_ascii=False))
    return jsonify(labels=clean)


@app.get("/favicon.ico")
def favicon():
    return "", 204


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
    system = prompts.INVEST_ROLE + "\n\n" + prompts.INVEST_PRINCIPLES if c["kind"] == "invest" else prompts.BASE_ROLE
    user = prompts.build_title_prompt(c["kind"], keyword, c["memo"], c["place"], exclude, c["guardrail"])
    text = llm.ask_text(system, user, max_tokens=1024, effort="low")
    result = [t for t in (clean_title(l) for l in text.splitlines()) if t]
    if c["kind"] == "invest":  # 권유·보장·단정 표현이 든 제목 후보는 버림
        result = [t for t in result if not invest_guard.violations("", t)]
    result = result[:5]
    return jsonify(titles=result, keywords=prompts.derive_keywords(c["kind"], keyword, c["place"]))


# ---------- 원고 ----------
def _enforce_invest_guard(fin, system, usage, kind, place, keywords, title, ratings, news_list):
    """투자 글 가드레일 강제(invest_guard.py 참고): AI 수정 1번 → 남은 위반 문장 삭제 → 안내 문장 보장. fin 을 고쳐 씁니다."""
    hits = invest_guard.violations(fin["body"])
    if hits:
        yield sse("status", {"text": f"투자 글 원칙에 어긋난 표현 {len(hits)}곳을 고치고 있어요."})
        try:
            g_usage = {}
            raw = llm.ask_text(system, prompts.build_guard_fix_prompt(fin["body"], hits), max_tokens=9000, effort=llm.EFFORT, usage=g_usage)
            fixed = postprocess.finalize(kind, raw, place, keywords, title, 0, ratings, news_list)
            usage = llm.merge_usage(usage, g_usage)
            # 고친 글이 원래 글의 70% 이상 분량이고 위반이 줄었을 때만 받음(엉뚱한 응답 방지)
            if fixed["chars"] >= fin["chars"] * 0.7 and len(invest_guard.violations(fixed["body"])) < len(hits):
                fin["body"], fin["chars"] = fixed["body"], fixed["chars"]
                fin["notes"].append(f"투자 글 원칙에 어긋난 표현 {len(hits)}곳을 AI가 고쳤어요.")
        except Exception:
            app.logger.exception("guard fix failed")
    body, removed = invest_guard.remove_violations(fin["body"])
    if removed:
        fin["notes"].append(f"원칙에 어긋난 문장 {len(removed)}개를 지웠어요: " + " / ".join(r[:40] for r in removed[:3]))
    body, added = invest_guard.ensure_disclaimer(body)
    if added:
        fin["notes"].append("개인 의견 안내 문장(투자 판단과 책임은 각자에게 있어요)을 넣었어요.")
    if body != fin["body"]:
        fin["body"], fin["chars"] = body, postprocess.count_chars(body)
        yield sse("replace", {"text": body})
    fin["_usage"] = usage


def _generate_events(*, kind, title, keywords, memo, place, guardrail, evidence_mode, build_prompt,
                     photos=None, photo_notes=None, parent_id=None, title_input=None, ratings=None, photo_names=None, news_list=None):
    """원고를 스트리밍으로 만들고, 후처리·점검·저장 후 SSE 이벤트를 흘려보냅니다.
    photos(사진 원본)가 있으면 먼저 사진을 살펴보고, photo_notes(이미 분석된 결과)가 있으면 그대로 씁니다."""
    parts, usage, photo_usage = [], {}, {}
    try:
        if photos and not photo_notes:
            photo_notes = []
            for start in range(0, len(photos), VISION_BATCH):
                chunk = photos[start:start + VISION_BATCH]
                yield sse("status", {"text": f"사진 {start + 1}~{start + len(chunk)}번째를 살펴보고 있어요(총 {len(photos)}장)."})
                part_usage = {}
                raw = llm.ask_vision(prompts.vision_system(kind), prompts.build_photo_analysis_prompt(kind, title, place, len(chunk), start + 1),
                                     chunk, usage=part_usage, start=start + 1)
                photo_usage = llm.merge_usage(photo_usage, part_usage)
                photo_notes += llm.parse_photo_notes(raw, len(chunk), start + 1, text_max=400 if kind == "invest" else 100)
        for note in photo_notes or []:
            idx = note.get("n", 0) - 1
            if photo_names and 0 <= idx < len(photo_names) and photo_names[idx]:
                note["name"] = photo_names[idx]
        if photo_notes:
            yield sse("photos", {"notes": photo_notes})
        system = prompts.build_system(kind, guardrail, evidence_mode, len(photo_notes or []),
                                      style_sample=style_for(kind), has_news=bool(news_list))
        user_prompt = build_prompt(photo_notes)
        yield sse("status", {"text": "원고를 쓰고 있어요."})
        for chunk in llm.stream_text(system, user_prompt, max_tokens=16000, usage=usage):
            parts.append(chunk)
            yield sse("chunk", {"text": chunk})
        usage = llm.merge_usage(photo_usage, usage)
        yield sse("status", {"text": "태그와 해시태그를 정리하고 품질을 점검하고 있어요."})
        fin = postprocess.finalize(kind, "".join(parts), place, keywords, title, len(photo_notes or []), ratings, news_list)
        floor = EXPAND_MIN.get(kind)
        enough_material = len(re.sub(r"\s", "", memo or "")) >= 150 or bool(photo_notes)
        if floor and fin["chars"] < floor and enough_material:
            yield sse("status", {"text": f"분량이 {fin['chars']:,}자로 짧아서 메모와 사진을 더 풀어 쓰고 있어요."})
            try:
                ex_usage = {}
                raw2 = llm.ask_text(system, prompts.build_expand_prompt(kind, fin["body"], fin["chars"], floor + EXPAND_TARGET_EXTRA, memo, photo_notes, keywords, ratings),
                                    max_tokens=9000, effort=llm.EFFORT, usage=ex_usage)
                fin2 = postprocess.finalize(kind, raw2, place, keywords, title, len(photo_notes or []), ratings, news_list)
                usage = llm.merge_usage(usage, ex_usage)
                if fin2["chars"] > fin["chars"]:
                    fin2["notes"].append(f"분량이 짧아 한 번 보강했어요({fin['chars']:,}자 → {fin2['chars']:,}자).")
                    fin = fin2
                else:
                    fin["notes"].append("분량 보강을 시도했지만 늘지 않아 처음 글을 그대로 썼어요.")
            except Exception:  # 보강 실패가 원고 생성 전체를 막으면 안 됩니다
                app.logger.exception("expand failed")
                fin["notes"].append("분량 보강에 실패해 처음 글을 그대로 썼어요.")
        if kind == "invest":
            for ev in _enforce_invest_guard(fin, system, usage, kind, place, keywords, title, ratings, news_list):
                yield ev
            usage = fin.pop("_usage", usage)
        quality = eval_style.evaluate(kind, fin["body"], keywords, memo, title=title, ad_check=guardrail)
        yield sse("replace", {"text": fin["body"]})
        article_id = storage.save_article(
            kind=kind, title_input=title_input or title, title_final=title, memo=memo, place=place, keywords=keywords,
            options={"guardrail": guardrail, "evidence_mode": evidence_mode, "usage": usage, "photos": photo_notes or [], "ratings": ratings or [],
                     "news": news_list or []},
            body=fin["body"], chars=fin["chars"],
            quality=quality, model=usage.get("model") or llm.MODEL, parent_id=parent_id)
        yield sse("done", {"article_id": article_id, "title": title, "body": fin["body"], "chars": fin["chars"],
                           "quality": quality, "notes": fin["notes"], "usage": usage, "photos": photo_notes or []})
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
    if c["kind"] == "invest":
        keywords = []  # 투자 생각 글은 검색 키워드를 쓰지 않음(제목을 해시태그로 억지로 넣지 않게)
    elif not keywords:
        keywords = prompts.derive_keywords(c["kind"], title, c["place"])
    photos = read_photos(data, c["kind"])
    ratings = read_ratings(data, c["kind"])
    news_list = news.read_news_list(data.get("news")) if c["kind"] == "invest" else []  # 참고 기사는 투자 생각 글 전용
    if c["kind"] == "invest":
        bad = invest_guard.violations("", title)
        if bad:
            raise ValueError(f"제목에 투자 권유·보장·단정 표현({', '.join(dict.fromkeys(h['match'] for h in bad))})이 있어요. 제목을 바꿔 주세요.")
    return sse_response(_generate_events(
        kind=c["kind"], title=title, keywords=keywords, memo=c["memo"], place=c["place"],
        guardrail=c["guardrail"], evidence_mode=c["evidence_mode"], photos=photos, ratings=ratings,
        photo_names=read_photo_names(data), news_list=news_list,
        build_prompt=lambda notes: prompts.build_article_prompt(c["kind"], title, keywords, c["memo"], c["place"], notes, ratings, news_list)))


@app.post("/api/articles/<int:article_id>/rewrite")
def article_rewrite(article_id: int):
    art = storage.get_article(article_id)
    if not art:
        raise ValueError("원고를 찾을 수 없어요.")
    issues = (art["quality"] or {}).get("issues", [])
    if not issues:
        raise ValueError("품질 점검에서 고칠 점이 없어요.")
    opts = art["options"] or {}
    notes = opts.get("photos") or []
    return sse_response(_generate_events(
        kind=art["kind"], title=art["title"], keywords=art["keywords"], memo=art["memo"], place=art["place"],
        guardrail=bool(opts.get("guardrail")), evidence_mode=opts.get("evidence_mode", "strict"),
        photo_notes=notes, parent_id=article_id, title_input=art["title_input"], ratings=opts.get("ratings") or [],
        news_list=opts.get("news") or [],
        build_prompt=lambda n: prompts.build_rewrite_prompt(art["kind"], art["body"], issues, art["keywords"], n, opts.get("ratings") or [],
                                                            opts.get("news") or [])))


@app.get("/api/articles")
def articles_list():
    return jsonify(articles=storage.list_articles())


@app.get("/api/articles/<int:article_id>")
def articles_get(article_id: int):
    art = storage.get_article(article_id)
    if not art:
        return jsonify(error="원고를 찾을 수 없어요."), 404
    return jsonify(article=art)


@app.put("/api/articles/<int:article_id>/body")
def articles_update_body(article_id: int):
    """[확인 필요] 채우기처럼 사용자가 고친 본문을 저장하고 글자수·품질 점검을 다시 계산합니다."""
    art = storage.get_article(article_id)
    if not art:
        raise ValueError("원고를 찾을 수 없어요.")
    body = str((request.get_json(silent=True) or {}).get("body", "")).replace("\r\n", "\n").strip()
    if not body:
        raise ValueError("본문이 비어 있어요.")
    if len(body) > MAX_BODY:
        raise ValueError("본문이 너무 길어요.")
    quality = eval_style.evaluate(art["kind"], body, art["keywords"], art["memo"], title=art["title"],
                                  ad_check=bool((art["options"] or {}).get("guardrail")))
    chars = postprocess.count_chars(body)
    storage.update_body(article_id, body, chars, quality)
    return jsonify(chars=chars, quality=quality)


@app.delete("/api/articles")
def articles_delete():
    ids = [int(i) for i in (request.get_json(silent=True) or {}).get("ids", []) if str(i).isdigit()]
    return jsonify(deleted=storage.delete_articles(ids))


def _open_browser_later(port: int) -> None:
    """run_blogdex.bat 로 실행하면(BLOGDEX_OPEN_BROWSER=1) 서버가 켜진 뒤 브라우저를 엽니다."""
    import threading
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()


if __name__ == "__main__":
    if os.getenv("BLOGDEX_OPEN_BROWSER") == "1":
        _open_browser_later(int(os.getenv("PORT", "5000")))
    # 본인 PC에서만 접속되도록 127.0.0.1 로 고정 (외부 공개 시 로그인/사용량 제한을 먼저 붙여야 합니다)
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False, threaded=True)
