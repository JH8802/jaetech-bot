import os
import re
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


class SafetyTests(unittest.TestCase):
    def test_markdown_is_converted(self):
        raw = "```\n## 1. 위치\n\n**핵심**은 이것입니다.\n\n- 목록 항목입니다.\n```"
        out, notes = pp.clean_markdown(raw)
        self.assertNotIn("**", out)
        self.assertNotIn("```", out)
        self.assertIn("1. 위치", out)
        self.assertIn("{{bold}}핵심{{/bold}}", out)
        self.assertIn("목록 항목입니다.", out)
        self.assertTrue(notes)

    def test_hashtags_untouched_by_heading_cleanup(self):
        out, _ = pp.clean_markdown("본문입니다.\n\n#마포맛집 #공덕맛집 #회식")
        self.assertTrue(out.endswith("#마포맛집 #공덕맛집 #회식"))

    def test_leading_title_line_removed(self):
        out, notes = pp.clean_markdown("제목: NMN 건강기능식품 고르는 법\n\n본문입니다.", "NMN 건강기능식품 고르는 법")
        self.assertEqual(out, "본문입니다.")
        self.assertTrue(notes)

    def test_region_tag_added_for_food(self):
        raw = "본문.\n\n1. 위치\n\n설명.\n\n2. 메뉴\n\n설명.\n\n#회식 #고깃집 #데이트"
        fin = pp.finalize("food", raw, {"name": "락희옥 마포본점", "address": "서울 마포구 백범로 170"}, [])
        tags = fin["body"].strip().splitlines()[-1].split()
        self.assertEqual(tags[:3], ["#락희옥마포본점", "#락희옥", "#마포맛집"])


class PhotoTests(unittest.TestCase):
    def test_markers_become_own_lines_and_bad_ones_dropped(self):
        t = "인트로입니다.\n\n<사진1>\n\n1. 소제목 <사진2>\n\n본문 <사진2> 이어서.\n\n<사진9>\n\n<사진2>"
        out, notes = pp.normalize_photos(t, 3)
        paras = out.split("\n\n")
        self.assertEqual(paras[:5], ["인트로입니다.", "<사진1>", "1. 소제목", "본문 이어서.", "<사진2>"])
        self.assertIn("<사진3>", paras)  # 빠진 3번은 자동으로 끼워 넣는다
        self.assertTrue(any("3번" in n for n in notes))  # 알림

    def test_no_photos_removes_all_markers(self):
        out, _ = pp.normalize_photos("글입니다.\n\n<사진1>", 0)
        self.assertEqual(out, "글입니다.")

    def test_marker_counts_like_original(self):
        # 원본은 사진 자리를 '사진N' 으로 셉니다(공백 제외)
        self.assertEqual(pp.count_chars("가나\n\n<사진1>\n\n#a #b #c"), len("가나사진1"))

    def test_all_fifteen_photos_present_in_order_even_if_ai_skips_many(self):
        paras = ["인트로 문단 하나", "인트로 문단 둘", "<사진1>", "1. 위치"] + [f"위치 문단 {i}" for i in range(4)] \
            + ["2. 메뉴"] + [f"메뉴 문단 {i}" for i in range(5)] + ["<사진9>", "3. 추천"] + [f"추천 문단 {i}" for i in range(4)] \
            + ["4. 재방문"] + [f"재방문 문단 {i}" for i in range(3)] + ["#a #b #c"]
        out, notes = pp.normalize_photos("\n\n".join(paras), 15)
        order = [int(m) for m in re.findall(r"<사진(\d+)>", out)]
        self.assertEqual(order, list(range(1, 16)))  # 15장 모두, 번호 순서대로
        self.assertTrue(out.rstrip().endswith("#a #b #c"))  # 해시태그는 마지막 유지
        self.assertNotIn("<사진10>\n\n1.", out)  # 소제목 바로 앞 문단은 피함(가능한 경우)
        self.assertTrue(notes)

    def test_out_of_order_markers_are_kept_and_missing_ones_still_inserted(self):
        # AI가 글 흐름에 맞춰 사진 4를 5보다 뒤에 놓아도(번호 순서 아님) 그대로 둔다
        paras = ["인트로", "1. 위치", "위치 문단", "2. 메뉴", "빵 문단", "<사진5>", "스테이크 문단", "<사진4>", "마무리 문단", "#a #b #c"]
        out, notes = pp.normalize_photos("\n\n".join(paras), 6)
        order = [int(m) for m in re.findall(r"<사진(\d+)>", out)]
        self.assertEqual(order.index(5) < order.index(4), True)  # 순서 유지
        self.assertEqual(sorted(order), [1, 2, 3, 4, 5, 6])      # 빠진 번호는 채움
        self.assertTrue(out.rstrip().endswith("#a #b #c"))

    def test_sections_do_not_start_with_marker_before_heading(self):
        out, _ = pp.normalize_photos("글1\n\n글2\n\n1. 소제목\n\n글3\n\n글4\n\n#a #b #c", 2)
        paras = out.split("\n\n")
        for i, p in enumerate(paras[:-1]):
            if p.startswith("<사진"):
                self.assertFalse(paras[i + 1].startswith("1."))


class RatingTests(unittest.TestCase):
    R = [{"label": "맛", "score": 4}, {"label": "가격", "score": 3}, {"label": "주차", "score": 5}]

    def test_block_format(self):
        b = pp.build_rating_block(self.R)
        self.assertEqual(b.split("\n"), ["★ 별점 한눈에 보기", "맛 ★★★★☆ 4/5", "가격 ★★★☆☆ 3/5", "주차 ★★★★★ 5/5"])

    def test_inserted_before_one_liner_and_before_hashtags(self):
        raw = "인트로 문단입니다.\n\n마무리 문단입니다.\n\n한 줄 평: 양이 넉넉해서 만족스러운 곳이에요.\n\n#맛집 #마포 #고기 #후기 #추천"
        out = pp.finalize("food", raw, {"name": "테스트 마포점"}, ["테스트"], ratings=self.R)["body"].split("\n\n")
        i = next(k for k, p in enumerate(out) if p.startswith("★ 별점"))
        self.assertTrue(out[i + 1].startswith("한 줄 평:"))   # 별점 블록 바로 뒤에 한 줄 평
        self.assertTrue(out[-1].startswith("#"))              # 해시태그는 마지막 유지

    def test_idempotent_and_ai_written_block_replaced(self):
        raw = "본문입니다.\n\n★ 별점 한눈에 보기\n맛 ★☆☆☆☆ 1/5\n\n한 줄 평: 괜찮아요.\n\n#a #b #c #d #e"
        once = pp.finalize("hotel", raw, {"name": "호텔"}, ["호텔"], ratings=self.R)["body"]
        twice = pp.finalize("hotel", once, {"name": "호텔"}, ["호텔"], ratings=self.R)["body"]
        self.assertEqual(once.count("★ 별점 한눈에 보기"), 1)
        self.assertNotIn("1/5", once)                          # AI가 만든 값은 버리고 입력값으로 교체
        self.assertEqual(once, twice)

    def test_no_ratings_and_missing_one_liner(self):
        r = pp.finalize("food", "본문입니다.\n\n#a #b #c #d #e", {"name": "가게"}, ["가게"])
        self.assertNotIn("별점", r["body"])
        self.assertTrue(any("한 줄 평" in n for n in r["notes"]))
        r2 = pp.finalize("food", "본문입니다.\n\n#a #b #c #d #e", {"name": "가게"}, ["가게"], ratings=self.R)
        self.assertLess(r2["body"].index("★ 별점"), r2["body"].index("#a"))  # 한 줄 평이 없어도 해시태그 앞

    def test_info_kind_never_gets_rating_block(self):
        r = pp.finalize("info", "본문입니다.\n\n한 줄 정리: 확인이 먼저입니다.\n\n#a #b #c #d #e", None, ["본문"], ratings=self.R)
        self.assertNotIn("★", r["body"])


class BatFileTests(unittest.TestCase):
    def test_bat_files_use_crlf_and_have_no_nested_quote_trap(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("run_blogdex.bat", "update_blogdex.bat"):
            raw = open(os.path.join(base, name), "rb").read()
            self.assertIn(b"\r\n", raw)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))  # 모든 줄바꿈이 CRLF
            self.assertIn(b"chcp 65001", raw)
        self.assertIn(b"BLOGDEX_OPEN_BROWSER=1", open(os.path.join(base, "run_blogdex.bat"), "rb").read())


if __name__ == "__main__":
    unittest.main()
