"""모바일 스킬(blogdex-draft) 만들기: 규칙이 PC 프로그램과 같은지, 점검 스크립트가 도는지."""
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import make_skill  # noqa: E402

DRAFT = """업체로부터 숙박을 제공받아 작성한 후기예요.

부곡 로얄 호텔 가족탕이 궁금해서 다녀왔어요.
생각보다 넓었어요.

📋 부곡 로얄 호텔
📍 경남 창녕군

1. 위치와 체크인

체크인은 오후 4시였어요.

[사진 1]

(플레이스 지도 삽입: 〈부곡 로얄 호텔〉)

2. 객실

객실은 깔끔했어요.

한 줄 평: 가족탕 하나로 충분히 다시 갈 만한 곳이에요.

(관련 글 링크 삽입: 내 다른 글 1~2개)

#부곡로얄호텔 #창녕호텔 #부곡온천 #가족탕 #온천여행 #경남여행 #가족여행 #호텔후기 #국내여행 #겨울여행"""


class SkillBuildTest(unittest.TestCase):
    def test_build_and_check(self):
        out = tempfile.mkdtemp()
        zp = make_skill.build(out, "test123")
        names = zipfile.ZipFile(zp).namelist()
        for n in ("SKILL.md", "references/rules.md", "scripts/check.py", "scripts/eval_style.py", "scripts/postprocess.py",
                  "scripts/adcheck.py", "scripts/outline.py", "scripts/register.py"):
            self.assertIn("blogdex-draft/" + n, names)
        root = os.path.join(out, "blogdex-draft")
        skill = open(os.path.join(root, "SKILL.md"), encoding="utf-8").read()
        self.assertTrue(skill.startswith("---\nname: blogdex-draft\ndescription: "))
        self.assertIn("버전 test123", skill)
        rules = open(os.path.join(root, "references", "rules.md"), encoding="utf-8").read()
        for s in ("공백을 포함한 글자 수로 1,500자 안팎", "[홈판 규칙", "해요체를 중심으로", "10~15개", "4~6회", "🧒 아이와 함께"):
            self.assertIn(s, rules)
        draft = os.path.join(out, "draft.txt")
        with open(draft, "w", encoding="utf-8") as f:
            f.write(DRAFT)
        r = subprocess.run([sys.executable, os.path.join(root, "scripts", "check.py"), "--kind", "hotel",
                            "--keywords", "부곡 로얄 호텔", draft], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("분량(공백 포함)", r.stdout)
        self.assertIn("고지 문단(맨 위): 있음", r.stdout)
        self.assertIn("| 통과 | 해시태그 개수 | 10개", r.stdout)


if __name__ == "__main__":
    unittest.main()
