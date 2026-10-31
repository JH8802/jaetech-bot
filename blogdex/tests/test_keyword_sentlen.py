import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402
import eval_style as ev  # noqa: E402
import prompts  # noqa: E402


class SentenceLengthTest(unittest.TestCase):
    def test_info_lines_not_counted_as_sentences(self):
        for line in ("휴무: 매주 월요일", "운영 시간: 09:20~16:50", "① 앱에서 등록", "광화문 ➡ 명동 ➡ 남산"):
            self.assertTrue(ev.is_info_line(line), line)
        for line in ("2층 앞자리에 앉으니 바람이 시원했어요.", "가격은 1인 15,000원이었습니다."):
            self.assertFalse(ev.is_info_line(line), line)

    def test_short_mixed_sentences_pass(self):
        sents = ["버스는 광화문에서 출발해요.", "2층 앞자리는 금방 찼습니다.", "생각보다 바람이 셌어요.",
                 "남산 구간에서는 단풍이 정말 예뻐서 사진을 여러 장 찍었습니다.", "좋았어요.",
                 "다음엔 오후 시간대에 타 보려고요.", "정류장마다 내려서 걸어 볼 수 있다는 점이 편했어요."]
        body = "\n\n".join(sents[i:i + 2] and "\n".join(sents[i:i + 2]) for i in range(0, len(sents), 2))
        body += "\n\n휴무: 월요일\n주차: 불가\n\n#a #b #c #d #e"
        chk = next(c for c in ev.evaluate("hotel", body, [])["checks"] if c["key"] == "sent_len")
        self.assertEqual(chk["target"], "평균 18~55 · 편차 8 이상")
        self.assertTrue(chk["ok"], chk["value"])


class KeywordTest(unittest.TestCase):
    def test_density_and_prompt_targets(self):
        body = "타이거버스를 탔다.\n좋았다.\n\n📋 한눈에 보기\n위치: 타이거버스 매표소\n\n#타이거버스 #a #b #c #d"
        d = ev.keyword_density(body, ["타이거버스"])
        self.assertAlmostEqual(d, 1000 / len("타이거버스를탔다.좋았다."))  # 박스·해시태그 속 키워드는 세지 않음
        up = prompts.build_article_prompt("hotel", "t", ["타이거버스", "서울시티투어버스"], "m", None)
        self.assertIn("[핵심 키워드 목표 횟수", up)
        self.assertIn("'타이거버스': 본문(박스·소제목·해시태그 제외)에 13회 이상", up)
        self.assertNotIn("목표 횟수", prompts.build_article_prompt("invest", "t", [], "m", None))

    def test_keyword_fix_pass_accepts_only_improvement(self):
        thin = "\n\n".join(["버스를 타고 광화문에서 출발했어요.\n2층이 시원했습니다."] * 6) + "\n\n#a #b #c #d #e"
        rich = "\n\n".join(["타이거버스를 타고 광화문에서 출발했어요.\n2층이 시원했습니다."] * 6) + "\n\n#a #b #c #d #e"
        base = {"body": thin, "chars": 120, "notes": []}
        with mock.patch.object(A.llm, "ask_text", return_value=rich):
            fin = dict(base, notes=[])
            list(A._enforce_keywords(fin, "sys", {}, "hotel", {}, ["타이거버스"], "t", [], [], None, []))
        self.assertIn("타이거버스를 타고", fin["body"])
        self.assertTrue(any("핵심 키워드를 보강했어요" in n for n in fin["notes"]))
        with mock.patch.object(A.llm, "ask_text", return_value=thin):  # 나아지지 않으면 원래 글 유지
            fin = dict(base, notes=[])
            list(A._enforce_keywords(fin, "sys", {}, "hotel", {}, ["타이거버스"], "t", [], [], None, []))
        self.assertEqual(fin["body"], thin)
        enough = {"body": rich, "chars": 200, "notes": []}  # 이미 충분하면 호출하지 않음
        with mock.patch.object(A.llm, "ask_text", side_effect=AssertionError("called")):
            list(A._enforce_keywords(enough, "sys", {}, "hotel", {}, ["타이거버스"], "t", [], [], None, []))


if __name__ == "__main__":
    unittest.main()
