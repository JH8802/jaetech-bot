"""글 구성(목차) 칸: 키워드 기획 메모(주제, 메인·세부 키워드, 검색자 니즈, 소제목 목차)를 읽어 원고 설계도로 씁니다.

- AI 없이 코드가 읽습니다(비용 0원). 형식이 조금 달라도 '메인 키워드', '세부', '니즈', '1. 소제목' 같은 표시를 찾아 읽습니다.
- 구성은 '사실'이 아니라 '설계도'입니다. 구성 속 경험·숫자는 메모·사진에 없으면 쓰지 않고 [확인 필요]로 남기게 합니다(prompts.OUTLINE_RULES).
"""
import re

MAX_OUTLINE = 4000

_EMPH = re.compile(r"\*\*|__|`")
_LEAD = re.compile(r"^[\s\-•*>·]+")
_HEAD = re.compile(r"^\s*(\d{1,2})[.)]\s*(.+)$")
_TOPIC = re.compile(r"\[\s*주제\s*\d*\s*\]\s*(.+)$")


def _clean(s: str) -> str:
    s = _EMPH.sub("", s)
    s = re.sub(r"^[^\w\[(]+", "", s.strip())  # 앞쪽 이모지·기호(📈 🎈 등)
    return re.sub(r"\s+", " ", s).strip()


def _value(line: str) -> str:
    return _clean(line.split(":", 1)[1]) if ":" in line else ""


def _split_kws(v: str) -> list[str]:
    return [k for k in (x.strip(" '\"`") for x in re.split(r"[,，/]", v)) if k]


def parse(text: str) -> dict:
    """{'topic', 'main', 'subs'[], 'needs', 'sections': [{'heading', 'points'[]}]}"""
    out = {"topic": "", "main": "", "subs": [], "needs": "", "sections": []}
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = _EMPH.sub("", raw).strip()
        if not line or set(line) <= set("-=_*"):
            continue
        bare = _LEAD.sub("", line)
        m = _TOPIC.search(bare)
        if m and not out["topic"]:
            out["topic"] = _clean(m.group(1))
            continue
        key = bare.split(":", 1)[0] if ":" in bare else ""
        if "메인" in key and "키워드" in key:
            out["main"] = _value(bare).strip("'\"")
            continue
        if ("세부" in key or "연관" in key) and "키워드" in key:
            out["subs"] = _split_kws(_value(bare))
            continue
        if "니즈" in key or "검색 의도" in key or "검색의도" in key:
            out["needs"] = _value(bare)
            continue
        if not out["topic"] and re.match(r"^(주제|제목)\s*:", bare):
            out["topic"] = _value(bare)
            continue
        h = _HEAD.match(line)
        if h and not raw.startswith((" ", "\t")):
            out["sections"].append({"heading": _clean(h.group(2)), "points": []})
            continue
        if out["sections"] and re.match(r"^\s*[-•*·]", raw):
            out["sections"][-1]["points"].append(_clean(_LEAD.sub("", line)))
    out["sections"] = out["sections"][:10]
    return out


def headings(text: str) -> list[str]:
    return [s["heading"] for s in parse(text)["sections"] if s["heading"]]


def to_block(text: str) -> str:
    """원고 지시에 넣을 '[글 구성]' 블록. 읽은 게 없으면 원문 그대로."""
    p = parse(text)
    lines = ["[글 구성 - 작성자가 기획한 설계도. 사실 자료가 아님]"]
    if p["main"] or p["subs"]:
        lines.append("- 키워드: " + ", ".join([p["main"]] + p["subs"] if p["main"] else p["subs"]))
    if p["needs"]:
        lines.append("- 검색자 니즈: " + p["needs"])
    if p["sections"]:
        lines.append("- 소제목 목차(이 순서와 뜻 그대로):")
        for i, s in enumerate(p["sections"], 1):
            lines.append(f"  {i}. {s['heading']}")
            lines += [f"     · {pt}" for pt in s["points"]]
    if len(lines) == 1:
        lines.append(text.strip()[:MAX_OUTLINE])
    return "\n".join(lines)


def _tokens(s: str) -> set[str]:
    s = re.sub(r"\[[^\]]*\]|\{\{/?\w+\}\}", " ", s)
    return {t[:2] if re.search(r"[가-힣]", t) else t.lower() for t in re.findall(r"[가-힣A-Za-z0-9%]+", s) if len(t) >= 2}


def coverage(outline_heads: list[str], body_heads: list[str]) -> list[str]:
    """원고 소제목에 반영되지 않은 구성 소제목 목록(단어가 절반 이상 겹치는 원고 소제목이 없으면 빠진 것으로 봄)."""
    bh = [_tokens(h) for h in body_heads]
    missing = []
    for h in outline_heads:
        t = _tokens(h)
        core = _tokens(re.sub(r"\[[^\]]*\]", "", h).split(":", 1)[0]) if ":" in h else set()  # 'A: B' 형식이면 A(핵심 대상)
        ok = (not t or any(len(t & b) / len(t) >= 0.4 for b in bh)
              or (core and any(len(core & b) / len(core) >= 0.6 for b in bh)))
        if not ok:
            missing.append(h)
    return missing
