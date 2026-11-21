"""프로그램 파일 업데이트 — GitHub에 올라간 최신 버전을 받아 교체한다.
사용법: update.bat 더블클릭 (또는 python update.py)

- 바뀐 파일 목록을 먼저 보여주고, 'y'를 눌러야 교체한다
- blog_files.txt에 적힌 프로그램 파일만 교체한다 (.env, 문체 샘플, 설정, drafts 폴더는 절대 안 건드림)
- 교체 전 파일은 _backup/날짜_시간/ 폴더에 남긴다
- 파일을 하나씩 받지 않고 묶음(zip) 하나로 받아서, 중간에 버전이 섞이지 않게 한다
"""
import io
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime

REPO = "JH8802/jaetech-bot"
BRANCH = "claude/relaxed-johnson-rkkjkm"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
HERE = os.path.dirname(os.path.abspath(__file__))
SAFE_NAME = re.compile(r"^[\w.-]+$")  # 폴더 경로·'..' 같은 이상한 이름은 거부


def download_zip(url=ZIP_URL):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return zipfile.ZipFile(io.BytesIO(resp.read()))


def read_manifest(text):
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not SAFE_NAME.match(line):
            raise RuntimeError(f"파일 목록에 이상한 이름이 있어서 중단: {line}")
        names.append(line)
    return names


def plan_update(archive, folder=HERE):
    """zip 안의 최신 파일과 내 폴더의 파일을 비교한다. 반환: [(파일 이름, 새 내용)]"""
    top = archive.namelist()[0].split("/")[0]
    manifest = archive.read(f"{top}/blog_files.txt").decode("utf-8")
    changed = []
    for name in read_manifest(manifest):
        try:
            new = archive.read(f"{top}/{name}")
        except KeyError:
            continue  # 목록에는 있는데 아직 올라가지 않은 파일
        path = os.path.join(folder, name)
        old = open(path, "rb").read() if os.path.exists(path) else None
        if old != new:
            changed.append((name, new))
    return changed


def apply_update(changed, folder=HERE):
    backup = os.path.join(folder, "_backup", datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(backup, exist_ok=True)
    for name, data in changed:
        path = os.path.join(folder, name)
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(backup, name))
        with open(path, "wb") as f:
            f.write(data)
    return backup


def main():
    print("최신 버전 확인 중...")
    try:
        archive = download_zip()
        changed = plan_update(archive)
    except Exception as e:
        print(f"업데이트 확인 실패 (인터넷 연결을 확인해줘): {e}")
        return 1

    if not changed:
        print("이미 최신 버전이야. 바꿀 파일 없음.")
        return 0

    print(f"\n새 버전이 있어. 바뀌는 파일 {len(changed)}개:")
    for name, _ in changed:
        print(f"  - {name}" + ("  (새 파일)" if not os.path.exists(os.path.join(HERE, name)) else ""))
    answer = input("\n지금 업데이트할까? (y/n): ").strip().lower()
    if answer not in ("y", "yes", "ㅛ"):
        print("업데이트 안 함. 지금 파일 그대로 둘게.")
        return 0

    backup = apply_update(changed)
    print(f"\n업데이트 완료. 이전 파일은 {backup} 에 보관했어.")
    if any(name == "requirements_blog.txt" for name, _ in changed):
        print("필요한 라이브러리가 바뀌어서 설치 중...")
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r",
                         os.path.join(HERE, "requirements_blog.txt")])
    print("Streamlit이 켜져 있으면 창을 닫고 run_app.bat으로 다시 켜줘.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
