"""블로그 초안 작성 — 실제로 쓸 때 이걸 실행하면 됨.
사용법: python blog_write.py

주제/사실/의견을 입력하면 초안을 만들어서 화면에 보여주고,
drafts/ 폴더에 파일로도 저장한다. 저장된 파일을 열어서 다듬은 뒤
네이버/티스토리 에디터에 그대로 복사해서 붙여넣으면 됨.
"""
from blog_drafter import draft_post
from datetime import datetime
import os


def get_key_points():
    print("\n실제 경험/숫자/사례를 한 줄씩 입력해 (다 넣었으면 빈 줄에서 엔터):")
    points = []
    while True:
        line = input(f"  [{len(points) + 1}] ").strip()
        if not line:
            break
        points.append(line)
    return points


if __name__ == "__main__":
    print("=== 블로그 초안 생성 ===")

    topic = input("\n주제: ").strip()
    key_points = get_key_points()

    if not key_points:
        print("\n❌ 사실/경험을 최소 1개는 입력해야 해. 다시 실행해줘.")
        raise SystemExit(1)

    personal_take = input("\n본인 의견/입장 (없으면 그냥 엔터): ").strip()

    print("\n⏳ 초안 생성 중...\n")
    draft = draft_post(topic, key_points, personal_take)

    print("=" * 50)
    print(draft)
    print("=" * 50)
    print(f"\n[글자 수: {len(draft)}자]")

    os.makedirs("drafts", exist_ok=True)
    filename = f"drafts/{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"주제: {topic}\n\n{draft}")

    print(f"\n💾 저장됨: {filename}")
    print("이 파일 열어서 다듬은 다음, 네이버/티스토리 에디터에 복사해서 붙여넣으면 돼.")
