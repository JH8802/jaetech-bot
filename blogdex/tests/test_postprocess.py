import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import postprocess as pp  # noqa: E402


class TagTests(unittest.TestCase):
    def test_unclosed_tag_is_closed_at_paragraph_end(self):
        out = pp.normalize_tags("{{bold}}가나다 라마바")
        self.assertEqual(out, "{{bold}}가나다 라마바{{/bold}}")

    def test_stray_closing_tag_is_dropped(self):
        self.assertEqual(pp.normalize_tags("가나다{{/bold}} 라마"), "가나다 라마")

    def test_tags_do_not_span_paragraphs(self):
        out = pp.normalize_tags("{{color}}첫째\n\n둘째{{/color}}")
        self.assertEqual(out, "{{color}}첫째{{/color}}\n\n둘째")

    def test_unknown_tags_removed(self):
        self.assertEqual(pp.normalize_tags("가{{foo}}나{{/foo}}다"), "가나다")

    def test_period_moves_outside_tag(self):
        out = pp.normalize_tags("{{highlight}}중요한 문장 .{{/highlight}}")
        self.assertEqual(out, "{{highlight}}중요한 문장{{/highlight}}.")

    def test_limit_highlights_keeps_two(self):
        text = "{{highlight}}a{{/highlight}} {{highlight}}b{{/highlight}} {{highlight}}c{{/highlight}}"
        out, total = pp.limit_highlights(text, 2)
        self.assertEqual(total, 3)
        self.assertEqual(out.count("{{highlight}}"), 2)
        self.assertIn("{{bold}}c{{/bold}}", out)


class HashtagTests(unittest.TestCase):
    def test_dedupe_clean_and_limit(self):
        tags = "#가나 #가나 #다라. #마바, " + " ".join(f"#t{i}" for i in range(40))
        out = pp.normalize_hashtags(tags, limit=30)
        parts = out.split()
        self.assertEqual(len(parts), 30)
        self.assertEqual(len(set(parts)), 30)
        self.assertIn("#다라", parts)

    def test_must_have_goes_first(self):
        out = pp.normalize_hashtags("#마포맛집 #공덕맛집", must_have=["락희옥 마포본점", "락희옥"])
        self.assertEqual(out.split()[:2], ["#락희옥마포본점", "#락희옥"])


class StructureTests(unittest.TestCase):
    BODY = "인트로 문단입니다.\n\n1. 위치\n\n위치 설명입니다.\n\n2. 메뉴\n\n메뉴 설명입니다.\n\n#가 #나 #다"

    def test_map_line_goes_before_second_heading(self):
        out = pp.insert_map_line(self.BODY, "락희옥 마포본점")
        paras = pp.split_paragraphs(out)
        i = next(k for k, p in enumerate(paras) if "지도 삽입" in p)
        self.assertEqual(paras[i + 1], "2. 메뉴")
        self.assertIn("〈락희옥 마포본점〉", paras[i])

    def test_map_line_not_duplicated(self):
        once = pp.insert_map_line(self.BODY, "가게")
        self.assertEqual(pp.insert_map_line(once, "가게"), once)

    def test_count_chars_rule(self):
        # 태그 제거, 해시태그 문단 제외, 공백 제외 (DESIGN.md §2.12 에서 확인한 규칙)
        text = "{{bold}}가나{{/bold}} 다라\n\n1. 마바\n\n#태그 #하나 #둘"
        self.assertEqual(pp.count_chars(text), len("가나다라1.마바"))

    def test_finalize_food_adds_map_line_and_must_have_tags(self):
        raw = ("락희옥 마포본점 후기입니다.\n\n1. 위치\n\n설명.\n\n2. 메뉴\n\n설명.\n\n#마포맛집 #공덕맛집 #회식")
        fin = pp.finalize("food", raw, {"name": "락희옥 마포본점"}, ["락희옥 마포본점"])
        self.assertIn("플레이스 지도 삽입", fin["body"])
        self.assertTrue(fin["body"].strip().splitlines()[-1].startswith("#락희옥마포본점"))
        self.assertGreater(fin["chars"], 0)

    def test_finalize_info_has_no_map_line(self):
        raw = "NMN 이야기입니다.\n\n1. 개념\n\n설명.\n\n#NMN #건강"
        fin = pp.finalize("info", raw, None, ["NMN"])
        self.assertNotIn("지도 삽입", fin["body"])


if __name__ == "__main__":
    unittest.main()
