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


class HomepanDecisionTest(unittest.TestCase):
    """사용자 결정(①분량 ②말투 ③해시태그 ④강조 ⑤문단 ⑦내 글 링크)이 맛집글·호텔에만 들어가는지"""

    def test_prompt_variants_only_for_place_kinds(self):
        for kind in ("food", "hotel"):
            s = prompts.build_system(kind, False, "strict", 3)
            self.assertIn("공백을 포함한 글자 수로 1,500자 안팎", s)
            self.assertIn("해요체를 중심으로 씁니다(합니다체는 20% 이하)", s)
            self.assertIn("10~15개(15개를 넘기지 않습니다)", s)
            self.assertNotIn("합니다체와 해요체를 자연스럽게 섞습니다", s)
            self.assertNotIn("2,300자", s)
            self.assertNotIn("2,700자", s)
        info = prompts.build_system("info", False, "strict", 3)
        self.assertIn("합니다체와 해요체를 자연스럽게 섞습니다", info)
        self.assertIn("5~10개(10개를 넘기지 않습니다)", info)
        self.assertIn("2,700자 안팎", info)

    def test_count_chars_ws(self):
        body = "가 나다.\n라마\n\n<사진1>\n\n(플레이스 지도 삽입: 〈x〉)\n\n(관련 글 링크 삽입: 내 다른 글 1~2개)\n\n#a #b #c"
        self.assertEqual(pp.count_chars_ws(body), len("가 나다.") + len("라마"))
        self.assertGreater(pp.count_chars(body), pp.count_chars_ws(body))  # 기존 공백 제외 기준(자리 줄 포함)은 그대로

    def test_hashtag_range(self):
        self.assertEqual(pp.HASHTAG_RANGE["food"], (10, 15))
        self.assertEqual(pp.HASHTAG_RANGE["hotel"], (10, 15))
        self.assertNotIn("info", pp.HASHTAG_RANGE)

    def test_expand_prompt_with_spaces_wording(self):
        self.assertIn("공백을 포함한 글자 수가 1,000자", prompts.build_expand_prompt("food", "본문", 1000, 1500, "메모", None, with_spaces=True))
        self.assertIn("공백을 뺀 글자 수가", prompts.build_expand_prompt("food", "본문", 1000, 1500, "메모", None))


class HomepanQualityCheckTest(unittest.TestCase):
    """품질 점검 재검토: 키워드 목표 4회·업종어 제외, 문장 길이 평균 15~45·편차 6 이상(맛집·호텔만)"""

    def test_keyword_target_and_generic_tokens(self):
        self.assertEqual(prompts.keyword_target(1200, "food"), 4)
        self.assertEqual(prompts.keyword_target(2700, "info"), 13)
        self.assertEqual(eval_style.keyword_tokens(["부곡 로얄 호텔"], "hotel"), ["부곡", "로얄"])
        self.assertEqual(eval_style.keyword_tokens(["부곡 로얄 호텔"], "info"), ["부곡", "로얄", "호텔"])
        self.assertEqual(eval_style.keyword_tokens(["제주 호텔"], "hotel"), ["제주"])
        self.assertEqual(eval_style.keyword_tokens(["호텔 맛집"], "hotel"), ["호텔", "맛집"])  # 업종어뿐이면 그대로
        self.assertIn("4~6회", prompts.build_system("food", False, "strict"))
        self.assertIn("(2,000자 글이면 8~12회)", prompts.build_system("info", False, "strict"))

    def test_sentence_length_target_by_kind(self):
        body = "\n\n".join(["객실은 깔끔했어요.\n침구가 포근했어요."] * 6) + "\n\n#a #b #c #d #e"
        food = next(c for c in eval_style.evaluate("food", body, [])["checks"] if c["key"] == "sent_len")
        info = next(c for c in eval_style.evaluate("info", body, [])["checks"] if c["key"] == "sent_len")
        self.assertEqual(food["target"], "평균 15~45 · 편차 6 이상")
        self.assertEqual(info["target"], "평균 18~55 · 편차 8 이상")


if __name__ == "__main__":
    unittest.main()
