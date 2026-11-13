"""홈판 규칙(맛집글·호텔·여행 후기 전용): 고지, 아이 동반 박스, 메뉴판·표시사항, 가격 비교 규칙이 맞는 글 종류에만 들어가는지."""
import unittest

import eval_style
import postprocess as pp
import prompts


class HomepanPromptTest(unittest.TestCase):
    def test_rules_only_for_food_and_hotel(self):
        for kind in ("food", "hotel"):
            self.assertIn("[홈판 규칙", prompts.build_system(kind, False, "strict", 3))
        for kind in ("info", "invest"):
            self.assertNotIn("[홈판 규칙", prompts.build_system(kind, False, "strict", 3))

    def test_rules_do_not_invent(self):
        r = prompts.HOMEPAN_PLACE_RULES
        self.assertIn("[확인 필요: 고지", r)
        self.assertIn("🧒 아이와 함께", r)
        self.assertIn("지어내지 않습니다", r)


BODY = """업체로부터 숙박을 제공받아 작성한 후기예요.

부곡 로얄 호텔 가족탕이 궁금해서 다녀왔어요. 생각보다 넓었어요.

📋 부곡 로얄 호텔
📍 경남 창녕군

🧒 아이와 함께
유아의자: 있음
키즈 메뉴: 돈가스 9,000원

1. 위치와 체크인

체크인은 오후 4시였어요. 주차는 넉넉했어요.

#부곡로얄호텔 #부곡온천 #창녕호텔 #가족탕 #온천여행"""


class HomepanPostprocessTest(unittest.TestCase):
    def test_child_box_kept_as_box(self):
        body = pp.finalize("hotel", BODY, {"name": "부곡 로얄 호텔"}, ["부곡 로얄 호텔"])["body"]
        self.assertIn("🧒 아이와 함께\n유아의자: 있음\n키즈 메뉴: 돈가스 9,000원", body)

    def test_disclosure_note(self):
        notes = pp.finalize("hotel", BODY, {"name": "부곡 로얄 호텔"}, ["부곡 로얄 호텔"])["notes"]
        self.assertFalse(any("고지" in n for n in notes))
        no_disc = BODY.split("\n\n", 1)[1]
        notes = pp.finalize("food", no_disc, {"name": "부곡 로얄 호텔"}, ["부곡 로얄 호텔"])["notes"]
        self.assertTrue(any("고지" in n for n in notes))
        notes = pp.finalize("info", no_disc, None, ["부곡 로얄 호텔"])["notes"]
        self.assertFalse(any("고지" in n for n in notes))

    def test_disclosure_paragraph_is_not_intro(self):
        body = pp.finalize("hotel", BODY, {"name": "부곡 로얄 호텔"}, ["부곡 로얄 호텔"])["body"]
        texts, _, _ = eval_style._body_parts(body)
        self.assertTrue(texts[0].startswith("부곡 로얄 호텔 가족탕"))
        self.assertFalse(any(t.startswith("🧒") for t in texts))
        self.assertTrue(pp.is_disclosure_paragraph("[확인 필요: 고지 - 내돈내산/협찬/제휴 중 하나]"))
        self.assertFalse(pp.is_disclosure_paragraph("부곡 로얄 호텔 가족탕이 궁금해서 다녀왔어요."))


if __name__ == "__main__":
    unittest.main()
