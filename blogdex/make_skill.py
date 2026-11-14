"""모바일 Claude용 스킬(blogdex-draft) 만들기.

PC 프로그램의 규칙(prompts.py)과 품질 점검 코드(eval_style.py 등)에서 스킬을 뽑아내므로,
규칙을 고친 뒤 이 파일을 다시 실행하면 스킬도 같은 규칙이 됩니다.

사용법: python blogdex/make_skill.py --out 출력폴더 [--version 버전]
결과: 출력폴더/blogdex-draft/ 폴더와 출력폴더/blogdex-draft.zip (Claude 설정의 스킬 메뉴에 올리는 파일)
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import prompts  # noqa: E402

SKILL_NAME = "blogdex-draft"
CHECK_MODULES = ["postprocess.py", "eval_style.py", "adcheck.py", "outline.py", "register.py"]


def rules_markdown(version: str) -> str:
    sections = [
        ("말투", prompts.PLACE_PERSONA),
        ("맛집글 구성·분량·문체", prompts.KIND_SPECS["food"]),
        ("호텔·여행 후기 구성·분량·문체", prompts.KIND_SPECS["hotel"]),
        ("출력 형식 (스킬에서는 강조 태그 대신 '강조 추천'으로 따로 적음 - SKILL.md 4번)", prompts.PLACE_TAG_RULES),
        ("문장", prompts.PLACE_WRITING_RULES),
        ("검색 최적화", prompts.PLACE_SEO_RULES),
        ("핵심 키워드 목표 횟수", prompts.keyword_count_block(["핵심 키워드 1", "핵심 키워드 2"], 1200, "food")),
        ("한 줄 평과 별점 (별점 줄은 스킬에서 직접 씀 - SKILL.md 4번)", prompts.RATING_RULES),
        ("재료 사용", prompts.EVIDENCE_STRICT),
        ("글이 자기 사정을 말하지 않게", prompts.NO_META),
        ("사진", prompts.PHOTO_RULES),
        ("정보 정리 형식 (한눈에 보기 박스)", prompts.INFO_LAYOUT_RULES),
        ("홈판 규칙", prompts.HOMEPAN_PLACE_RULES),
        ("식품·건강 표현 주의", prompts.GUARDRAIL),
    ]
    out = [f"# 블덱스라이터 작성 규칙 (맛집글·호텔·여행 후기) · 버전 {version}",
           "",
           "PC 프로그램 prompts.py 에서 자동으로 뽑은 규칙이다. '시스템이 넣는다'고 된 줄은 스킬에서는 직접 넣는다(SKILL.md 4번).",
           "'사진 정보'는 SKILL.md 2번에서 정리한 사진 목록을 말한다."]
    for title, text in sections:
        out += ["", f"## {title}", "", text.strip()]
    return "\n".join(out) + "\n"


def code_version() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True).strip()
    except Exception:
        return "unknown"


def build(out_dir: str, version: str = "") -> str:
    version = version or code_version()
    root = os.path.join(out_dir, SKILL_NAME)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "references"))
    os.makedirs(os.path.join(root, "scripts"))
    with open(os.path.join(HERE, "skill", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read().replace("{VERSION}", version)
    with open(os.path.join(root, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill)
    with open(os.path.join(root, "references", "rules.md"), "w", encoding="utf-8") as f:
        f.write(rules_markdown(version))
    shutil.copy(os.path.join(HERE, "skill", "check.py"), os.path.join(root, "scripts", "check.py"))
    for m in CHECK_MODULES:
        shutil.copy(os.path.join(HERE, m), os.path.join(root, "scripts", m))
    zip_path = os.path.join(out_dir, SKILL_NAME + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(root):
            for name in sorted(files):
                full = os.path.join(base, name)
                z.write(full, os.path.relpath(full, out_dir))
    return zip_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(build(a.out, a.version))
