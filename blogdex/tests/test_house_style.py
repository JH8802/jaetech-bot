import unittest

import postprocess as pp
import prompts


class InvestHouseStyleTest(unittest.TestCase):
    def test_house_style_replaces_persona_for_invest_only(self):
        inv = prompts.build_system("invest", True, "strict", register="plain")
        self.assertIn("[투자 생각 고정 문체 - 분석 칼럼형]", inv)
        self.assertNotIn("[글쓴이 말투 컨셉", inv)
        self.assertIn("소제목('1. ' 형식 줄)은 쓰지 않는다", inv)
        self.assertIn("[종결어미 - 최우선 규칙", inv)
        food = prompts.build_system("food", False, "strict")
        self.assertIn("[글쓴이 말투 컨셉", food)
        self.assertNotIn("고정 문체", food)

    def test_user_sample_still_added_on_top(self):
        inv = prompts.build_system("invest", True, "strict", style_sample="나는 이렇게 본다.", register="plain")
        self.assertIn("나는 이렇게 본다.", inv)
        self.assertLess(inv.index("[투자 생각 고정 문체"), inv.index("[말투 샘플 시작]"))

    def test_invest_headings_removed_others_kept(self):
        raw = "사실 한 줄이다.\n\n1. 소제목\n\n본문이다.\n\n#a #b #c"
        inv = pp.finalize("invest", raw, None, [])
        self.assertNotIn("1. 소제목", inv["body"])
        self.assertTrue(any("소제목 1줄을 지웠어요" in n for n in inv["notes"]))
        self.assertIn("1. 소제목", pp.finalize("info", raw, None, ["사실"])["body"])

    def test_invest_title_prompt_is_column_style(self):
        p = prompts.build_title_prompt("invest", "금리", "", None, [], True)
        self.assertIn("칼럼형", p)


if __name__ == "__main__":
    unittest.main()
