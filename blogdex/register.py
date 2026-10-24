"""종결어미(말투 높낮이) 판별: 말투 샘플이 한다체·합니다체·해요체 중 무엇인지 알아내고, 원고가 그 어미를 얼마나 지켰는지 잽니다.

- 투자 생각 글은 말투 샘플의 어미를 최우선으로 씁니다(prompts.register_block). 생성 뒤 일치율이 낮으면 어미만 고치는 수정을 한 번 더 합니다(app.py).
- 판별은 문장 끝 글자로 하는 간단한 규칙입니다. 명사로 끝나는 문장(소제목 등)은 세지 않습니다.
"""
import re

from postprocess import is_special_paragraph, split_paragraphs, split_sentences, strip_tags

LABELS = {"plain": "한다체(~다)", "formal": "합니다체(~습니다)", "polite": "해요체(~요)"}

_TRAIL = re.compile(r"[\s.?!…~\"'”’)\]]+$")


def _has_bieup(ch: str) -> bool:
    """받침이 ㅂ인 한글 음절인지(합니다·입니다·습니다의 '합/입/습')"""
    code = ord(ch) - 0xAC00
    return 0 <= code < 11172 and code % 28 == 17


def _is_formal(core: str) -> bool:
    """합니다체: '-ㅂ니다/-습니다', '-ㅂ니까', '-십시오'. '아니다'처럼 받침 없는 '니다'는 한다체."""
    m = re.search(r"(.)(니다|니까)$", core)
    return bool((m and _has_bieup(m.group(1))) or core.endswith("십시오"))


def sentence_register(s: str) -> str:
    """'plain'(한다체) / 'formal'(합니다체) / 'polite'(해요체) / ''(판별 안 됨: 명사 끝 등)"""
    core = _TRAIL.sub("", strip_tags(s).strip())
    if _is_formal(core):
        return "formal"
    if re.search(r"(요|죠)$", core):
        return "polite"
    if re.search(r"(다|까|냐|지|자|군|구나|네|나)$", core):
        return "plain"
    return ""


def detect_register(sample: str) -> str:
    """말투 샘플의 어미가 한 가지로 뚜렷하면 그 이름, 섞여 있거나 짧으면 ''."""
    segs = [x for x in re.split(r"[.?!\n]+", sample or "") if x.strip()]
    counts = {"plain": 0, "formal": 0, "polite": 0}
    for seg in segs:
        r = sentence_register(seg + ".")
        if r:
            counts[r] += 1
    total = sum(counts.values())
    if total < 3:
        return ""
    best = max(counts, key=counts.get)
    return best if counts[best] / total >= 0.6 else ""


def body_sentences(body: str) -> list[str]:
    out = []
    for par in split_paragraphs(body):
        if not is_special_paragraph(par):
            out += split_sentences(par)
    return out


def match_ratio(body: str, register: str) -> tuple[float, list[str]]:
    """원고에서 판별되는 문장 중 register 어미의 비율과, 어긋난 문장 목록."""
    judged, wrong = 0, []
    for s in body_sentences(body):
        r = sentence_register(s)
        if not r:
            continue
        judged += 1
        if r != register:
            wrong.append(strip_tags(s))
    return (1.0 if not judged else (judged - len(wrong)) / judged), wrong
