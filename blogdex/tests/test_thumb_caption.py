import unittest

import eval_style
import llm
import prompts


class PhotoCaptionThumbTest(unittest.TestCase):
    def test_parse_caption_and_thumb(self):
        raw = '[{"n": 1, "category": "외관", "desc": "d", "text": "", "caption": "야외 장독대.", "thumb": 5},' \
              '{"n": 2, "category": "내부", "desc": "d", "text": "", "caption": "", "thumb": "x"}]'
        notes = llm.parse_photo_notes(raw, 3)
        self.assertEqual(notes[0]["caption"], "야외 장독대")  # 끝 문장부호 제거
        self.assertEqual(notes[0]["thumb"], 5)
        self.assertEqual(notes[1]["thumb"], 0)  # 숫자가 아니면 0
        self.assertEqual(notes[2], {"n": 3, "category": "기타", "desc": "", "text": "", "dish": "", "dish_confidence": "", "caption": "", "thumb": 0})

    def test_vision_prompt_asks_caption_and_thumb(self):
        p = prompts.build_photo_analysis_prompt("food", "제목", None, 2)
        self.assertIn('"caption"', p)
        self.assertIn('"thumb"', p)
        self.assertIn("caption", prompts.VISION_SYSTEM)


class TypoCheckTest(unittest.TestCase):
    def test_finds_broken_particles(self):
        found = eval_style.find_typos("주문한 커피는를 올렸어요. 남겨 둡니다 있다으로 끝. 가능하고 ,약 50대")
        self.assertIn("커피는를", found)
        self.assertIn("있다으로", found)
        self.assertTrue(any("가능하고" in f for f in found))

    def test_normal_korean_is_not_flagged(self):
        ok = "날씨가 다를 수 있어요. 바다에서 은은한 맛이 나요. 마당 다음으로 갔어요. 먹는다는 점이 좋아요."
        self.assertEqual(eval_style.find_typos(ok), [])


class PromptRulesTest(unittest.TestCase):
    def test_title_prompt_has_two_directions(self):
        p = prompts.build_title_prompt("food", "익산 고스락", "", None, [], False)
        self.assertIn("검색형 3개와 궁금증형 2개", p)

    def test_broadcast_hook_rule_for_place_kinds_only(self):
        self.assertIn("방송 출연", prompts.build_system("food", False, "strict"))
        self.assertIn("방송 출연", prompts.build_system("hotel", False, "strict"))
        self.assertNotIn("방송 출연", prompts.build_system("info", False, "strict"))


if __name__ == "__main__":
    unittest.main()
