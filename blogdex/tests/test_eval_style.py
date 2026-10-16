import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eval_style as ev  # noqa: E402

TAGS = "#" + " #".join(f"태그{i}" for i in range(8))


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


class PromptTests(unittest.TestCase):
    def test_no_meta_rule_in_both_modes_and_kinds(self):
        import prompts
        for kind in ("info", "food"):
            for mode in ("strict", "template"):
                self.assertIn("자기 사정", prompts.build_system(kind, False, mode))


class HotelEvalTests(unittest.TestCase):
    def test_hotel_length_bounds_and_endings_use_review_rules(self):
        res = ev.evaluate("hotel", body(["객실이 넓었어요. 침구가 푹신했습니다. 조식은 붐볐어요."] * 5), ["객실"])
        length = next(c for c in res["checks"] if c["key"] == "length")
        self.assertEqual(length["target"], "2,400~3,400자")
        self.assertFalse(length["ok"])
        self.assertTrue(any(c["key"] == "first_person" for c in res["checks"]))  # 후기형 점검 포함


class NewRuleTests(unittest.TestCase):
    def test_hashtag_range_is_five_to_ten(self):
        def n_tags(n):
            tags = " ".join(f"#태그{i}" for i in range(n))
            res = ev.evaluate("info", "본문입니다.\n\n" + tags, ["본문"])
            return next(c for c in res["checks"] if c["key"] == "hashtags")["ok"]
        self.assertFalse(n_tags(4))
        self.assertTrue(n_tags(5))
        self.assertTrue(n_tags(10))
        self.assertFalse(n_tags(11))

    def test_keyword_density_needs_at_least_four_per_thousand(self):
        filler = "정보를 전달하는 보통 길이의 문장이라서 읽는 흐름을 자연스럽게 이어 주는 역할을 합니다. " * 12
        low = ev.evaluate("info", body([filler + "놉스가 있습니다."] * 3), ["놉스"])
        high = ev.evaluate("info", body([filler + "놉스 놉스 놉스 놉스 매장입니다."] * 3), ["놉스"])
        self.assertFalse(next(c for c in low["checks"] if c["key"] == "kw_density")["ok"])
        self.assertTrue(next(c for c in high["checks"] if c["key"] == "kw_density")["ok"])

    def test_info_endings_accept_mixed_tone(self):
        mixed = "이 부분은 꼭 확인해야 합니다. 저는 이렇게 하고 있어요. 순서는 이렇습니다. 어렵지 않더라고요."
        res = ev.evaluate("info", body([mixed] * 4), ["부분"])
        self.assertTrue(next(c for c in res["checks"] if c["key"] == "endings")["ok"])


class AdCheckTests(unittest.TestCase):
    RISKY = "NMN은 노화 방지에 효과가 있습니다.\n\n효과를 약속하는 글은 아닙니다. 치료 목적이 아닙니다.\n\n#NMN효능 #항산화"

    def test_scan_levels_and_soft_context(self):
        import adcheck
        hits = adcheck.scan("", self.RISKY)
        by = {(h["match"], h["soft"]) for h in hits}
        self.assertIn(("노화 방지", False), by)
        self.assertIn(("효과", False), by)      # 단정 문장
        self.assertIn(("효과", True), by)       # '아닙니다' 설명 문장은 참고
        self.assertIn(("치료", True), by)
        self.assertIn(("효능", False), by)      # 해시태그도 검사
        sm = adcheck.summarize(hits)
        self.assertEqual(sm["high"], 0)
        self.assertGreaterEqual(sm["warn"], 3)

    def test_high_level_and_title(self):
        import adcheck
        hits = adcheck.scan("당뇨 치료에 좋은 영양제", "본문입니다.")
        self.assertTrue(any(h["level"] == "high" and h["where"] == "제목" for h in hits))

    def test_evaluate_adds_ad_check_only_when_enabled(self):
        off = ev.evaluate("info", body([self.RISKY.split("\n\n")[0]]), ["NMN"])
        self.assertFalse(any(c["key"] == "ad" for c in off["checks"]))
        on = ev.evaluate("info", body([self.RISKY.split("\n\n")[0]]), ["NMN"], ad_check=True)
        ad = next(c for c in on["checks"] if c["key"] == "ad")
        self.assertFalse(ad["ok"])
        self.assertTrue(ad["hits"])
        self.assertTrue(any("노화 방지" in i for i in on["issues"]))  # 다시 쓰기 지시에 포함

    def test_clean_text_passes(self):
        on = ev.evaluate("info", body(["라벨에서 인정된 기능성 표시가 있는지 확인합니다."]), ["라벨"], ad_check=True)
        self.assertTrue(next(c for c in on["checks"] if c["key"] == "ad")["ok"])


if __name__ == "__main__":
    unittest.main()
