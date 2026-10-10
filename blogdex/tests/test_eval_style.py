import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eval_style as ev  # noqa: E402

TAGS = "#" + " #".join(f"태그{i}" for i in range(29))


def body(paragraphs):
    return "\n\n".join(paragraphs + [TAGS])


class EvalTests(unittest.TestCase):
    def test_first_paragraph_keyword_check(self):
        good = ev.evaluate("info", body(["NMN 건강기능식품을 고를 때는 표시를 봅니다.", "둘째 문단입니다."]), ["NMN 건강기능식품"])
        bad = ev.evaluate("info", body(["고를 때는 표시를 봅니다.", "둘째 문단입니다."]), ["NMN 건강기능식품"])
        self.assertTrue(next(c for c in good["checks"] if c["key"] == "first_para")["ok"])
        self.assertFalse(next(c for c in bad["checks"] if c["key"] == "first_para")["ok"])

    def test_uniform_sentences_are_flagged(self):
        s = "이 문장은 길이가 거의 같고 모든 문장이 같은 모양으로 이어지는 문장입니다. "
        res = ev.evaluate("info", body([s * 3] * 6), ["문장"])
        self.assertFalse(next(c for c in res["checks"] if c["key"] == "sent_len")["ok"])
        self.assertTrue(res["issues"])

    def test_varied_sentences_pass(self):
        mid = "정보를 전달하는 보통 길이의 문장이라서 읽는 흐름을 자연스럽게 이어 주는 역할을 합니다."
        par = f"짧아요. {mid} {mid} 네. {mid} {mid}"
        res = ev.evaluate("info", body([par] * 6), ["문장"])
        self.assertTrue(next(c for c in res["checks"] if c["key"] == "sent_len")["ok"])

    def test_duplicate_sentences_detected(self):
        a = "겉은 노릇하게 익었는데 씹을수록 고소한 맛이 은근히 길게 남더라고요."
        b = "겉면은 노릇하게 익었는데 씹을수록 고소한 맛이 은근히 오래 남더라고요."
        res = ev.evaluate("food", body([a + " " + b]), ["고소한"])
        self.assertFalse(next(c for c in res["checks"] if c["key"] == "dup")["ok"])

    def test_hashtag_count_check(self):
        few = ev.evaluate("info", "문단입니다.\n\n#하나 #둘 #셋", ["문단"])
        self.assertFalse(next(c for c in few["checks"] if c["key"] == "hashtags")["ok"])
        ok = ev.evaluate("info", body(["문단입니다."]), ["문단"])
        self.assertTrue(next(c for c in ok["checks"] if c["key"] == "hashtags")["ok"])

    def test_memo_coverage(self):
        memo = "항정살이 맛있었고 직원이 불판을 갈아줬다"
        used = ev.evaluate("food", body(["항정살은 맛있었고 직원이 불판을 계속 갈아줬습니다."]), ["항정살"], memo)
        unused = ev.evaluate("food", body(["분위기가 좋은 가게였습니다."]), ["가게"], memo)
        self.assertTrue(next(c for c in used["checks"] if c["key"] == "memo")["ok"])
        self.assertFalse(next(c for c in unused["checks"] if c["key"] == "memo")["ok"])

    def test_no_memo_check_without_memo(self):
        res = ev.evaluate("info", body(["문단입니다."]), ["문단"], "")
        self.assertFalse(any(c["key"] == "memo" for c in res["checks"]))

    def test_todo_marker_counted_but_not_a_rewrite_issue(self):
        text = body(["NMN 이야기입니다. [확인 필요: 식약처 인정 현황] 직접 확인합니다."])
        res = ev.evaluate("info", text, ["NMN"])
        todo = next(c for c in res["checks"] if c["key"] == "todo")
        self.assertFalse(todo["ok"])
        self.assertEqual(todo["value"], "1곳")
        self.assertNotIn("", res["issues"])  # 빈 안내는 다시 쓰기 지시에 들어가지 않음
        none = ev.evaluate("info", body(["NMN 이야기입니다."]), ["NMN"])
        self.assertTrue(next(c for c in none["checks"] if c["key"] == "todo")["ok"])


if __name__ == "__main__":
    unittest.main()
