import unittest

import eval_style
import postprocess as pp
import prompts


class MobileReadabilityTest(unittest.TestCase):
    def test_every_kind_breaks_line_per_sentence(self):
        raw = ("놉스 사당점에 다녀왔어요. 양이 넉넉했습니다! 다시 갈 것 같아요.\n\n1. 위치\n\n"
               "역에서 가까워요. 주차는 어렵습니다.\n\n한 줄 평: 양 많은 동네 맛집입니다.\n\n#놉스 #사당맛집 #a #b #c")
        for kind in ("info", "food", "hotel"):
            body = pp.finalize(kind, raw, {"name": "놉스 사당점"} if kind != "info" else None, ["놉스"])["body"]
            self.assertIn("놉스 사당점에 다녀왔어요.\n양이 넉넉했습니다!\n다시 갈 것 같아요.", body, kind)
            self.assertIn("1. 위치", body)

    def test_summary_block_kept_as_is_and_skipped_in_eval(self):
        raw = ("NMN 이야기입니다. 둘째 문장입니다.\n\n📌 이 글 핵심 3줄\n① 표시를 먼저 본다\n② 함량을 비교한다\n③ 상담이 우선이다\n\n"
               "1. 개념\n\n본문입니다.\n\n#NMN #a #b #c #d")
        body = pp.finalize("info", raw, None, ["NMN"])["body"]
        self.assertIn("📌 이 글 핵심 3줄\n① 표시를 먼저 본다\n② 함량을 비교한다\n③ 상담이 우선이다", body)
        ev = eval_style.evaluate("info", body, ["NMN"])
        self.assertTrue(ev["checks"])

    def test_prompts_ask_short_paragraphs_and_fewer_emphasis(self):
        for kind in ("info", "food", "hotel"):
            s = prompts.build_system(kind, False, "strict")
            self.assertIn("문단은 1~2문장", s)
            self.assertIn("{{bold}} 는 5~8번, {{color}} 는 2~4번", s)
            self.assertIn("60~100자", prompts.KIND_SPECS[kind])
        self.assertIn("📌 이 글 핵심 3줄", prompts.KIND_SPECS["info"])
        self.assertNotIn("📌 이 글 핵심 3줄", prompts.KIND_SPECS["food"])
        inv = prompts.build_system("invest", True, "strict")
        self.assertNotIn("문단은 1~2문장", inv)  # 투자 글은 자기 형식(문단 2~4줄)
        self.assertIn("{{bold}} 는 4~8번", inv)


if __name__ == "__main__":
    unittest.main()
