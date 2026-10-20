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

    def test_info_title_prompt_has_no_place_wording(self):
        p = prompts.build_title_prompt("info", "루테인", "", None, [], False)
        self.assertIn("검색형 3개와 궁금증형 2개", p)
        self.assertNotIn("지역과 장소 이름", p)

    def test_broadcast_hook_rule_for_place_kinds_only(self):
        self.assertIn("방송 출연", prompts.build_system("food", False, "strict"))
        self.assertIn("방송 출연", prompts.build_system("hotel", False, "strict"))
        self.assertNotIn("방송 출연", prompts.build_system("info", False, "strict"))


class InvestKindTest(unittest.TestCase):
    MEMO_BODY = "\n\n".join(["요즘 시장 분위기가 어수선해서 마음이 복잡했어요."] * 3)

    def test_kind_registered_and_no_place_or_photos(self):
        self.assertEqual(prompts.KINDS["invest"]["label"], "투자 생각")
        self.assertNotIn("invest", prompts.PLACE_KINDS)

    def test_system_prompt_is_essay_without_seo(self):
        sysmsg = prompts.build_system("invest", True, "strict")
        self.assertIn("투자 생각", sysmsg)
        self.assertIn("'작성자 메모'에 적힌 것만", sysmsg)  # 시황·수치는 메모에 있는 것만
        self.assertIn("매수·매도를 권하지 않습니다", sysmsg)
        self.assertIn("투자 표현 가드레일", sysmsg)
        self.assertNotIn("[검색 최적화 규칙]", sysmsg)
        self.assertNotIn("핵심 키워드는 줄이거나", sysmsg)
        self.assertNotIn("[표시·광고 가드레일", sysmsg)
        self.assertIn("{{bold}} 는 4~8번", sysmsg)
        off = prompts.build_system("invest", False, "strict")
        self.assertNotIn("투자 표현 가드레일", off)
        self.assertIn("사진이 없습니다", off)

    def test_article_prompt_without_keywords_and_title_prompt(self):
        up = prompts.build_article_prompt("invest", "요즘 마음", [], "[요즘 시장 분위기]\n- 불안", None, None, None)
        self.assertNotIn("[핵심 키워드]", up)
        self.assertIn("시황 사실은 여기 적힌 것만", up)
        tp = prompts.build_title_prompt("invest", "요즘 마음", "", None, [], True)
        self.assertIn("투자 일기", tp)
        self.assertNotIn("검색형 3개", tp)

    def test_invest_check_flags_recommendation_and_guarantee(self):
        import adcheck
        hits = adcheck.scan("제목", "이 종목은 무조건 오릅니다. 지금이 기회라서 매수하세요. 다만 제 생각이고 틀릴 수 있어요.", "invest")
        cats = {h["category"] for h in hits if not h["soft"]}
        self.assertIn("수익 보장·단정", cats)
        self.assertIn("매수·매도 권유", cats)
        calm = adcheck.scan("제목", "저는 천천히 나눠서 사려고 생각하고 있어요. 틀릴 수도 있어요.", "invest")
        self.assertEqual([h for h in calm if not h["soft"]], [])
        # 식품 목록으로는 투자 표현을 잡지 않음
        self.assertEqual(adcheck.scan("제목", "무조건 오릅니다.", "info"), [])

    def test_eval_skips_seo_checks_and_uses_invest_ad_label(self):
        res = eval_style.evaluate("invest", self.MEMO_BODY + "\n\n#주식 #투자일기 #마음 #원칙 #생각", [], "", "t", ad_check=True)
        keys = [c["key"] for c in res["checks"]]
        self.assertNotIn("first_para", keys)
        self.assertNotIn("kw_density", keys)
        ad = next(c for c in res["checks"] if c["key"] == "ad")
        self.assertIn("투자 표현", ad["label"])


if __name__ == "__main__":
    unittest.main()
