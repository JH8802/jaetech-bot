import json
import os
import sys
import tempfile
import unittest

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402
import eval_style  # noqa: E402
import invest_guard  # noqa: E402
import prompts  # noqa: E402
import register as reg  # noqa: E402

USER_SAMPLE = "'~라고 본다. ~생각한다. ~있다. ~된다. ~했다. ~이다. ~였다. ~하다. 일까?. 위해서다. ~것이다.'"


class RegisterDetectTest(unittest.TestCase):
    def test_detect_from_samples(self):
        self.assertEqual(reg.detect_register(USER_SAMPLE), "plain")
        self.assertEqual(reg.detect_register("좋았습니다. 맛있었습니다. 다시 갈 생각입니다."), "formal")
        self.assertEqual(reg.detect_register("좋더라고요. 맛있었어요. 또 갈래요."), "polite")
        self.assertEqual(reg.detect_register("좋았다. 맛있었어요. 괜찮습니다."), "")  # 섞여 있으면 판단 안 함
        self.assertEqual(reg.detect_register(""), "")

    def test_sentence_and_ratio(self):
        self.assertEqual(reg.sentence_register("오를 것이다."), "plain")
        self.assertEqual(reg.sentence_register("그렇지 않을까?"), "plain")
        self.assertEqual(reg.sentence_register("{{bold}}버텼다{{/bold}}."), "plain")
        self.assertEqual(reg.sentence_register("좋았습니다."), "formal")
        self.assertEqual(reg.sentence_register("버텼죠."), "polite")
        self.assertEqual(reg.sentence_register("1. 마음이 흔들린 날"), "")
        body = "시장이 흔들렸다.\n불안했어요.\n그래도 버틴다.\n\n1. 소제목\n\n원칙을 지킨다.\n\n#주식 #투자 #마음"
        share, wrong = reg.match_ratio(body, "plain")
        self.assertAlmostEqual(share, 0.75)
        self.assertEqual(wrong, ["불안했어요."])


class RegisterPromptTest(unittest.TestCase):
    def test_register_overrides_fixed_mix_only_when_detected(self):
        on = prompts.build_system("invest", True, "strict", style_sample=USER_SAMPLE, register="plain")
        self.assertIn("[종결어미 - 최우선 규칙", on)
        self.assertNotIn("합니다체 약 45%", on)
        self.assertNotIn("합니다체와 해요체를 자연스럽게 섞습니다", on)
        self.assertLess(on.index("[종결어미"), on.index("[글 종류: 투자 생각"))
        off = prompts.build_system("invest", True, "strict")
        self.assertIn("합니다체 약 45%", off)
        self.assertNotIn("[종결어미", off)
        p = prompts.build_register_fix_prompt("본문이에요.", "plain", ["본문이에요."])
        self.assertIn("[어미 바꾸기]", p)
        self.assertIn("한다체", p)

    def test_plain_disclaimer_and_eval(self):
        body = "시장이 흔들렸다.\n그래도 버틴다.\n\n한 줄 정리: 원칙대로 간다.\n\n#주식 #투자 #마음"
        out, added = invest_guard.ensure_disclaimer(body, "plain")
        self.assertTrue(added)
        self.assertTrue(any(d in out for d in invest_guard.DISCLAIMERS_BY_REGISTER["plain"]))
        self.assertEqual(reg.match_ratio(out, "plain")[0], 1.0)
        ev = eval_style.evaluate("invest", out, [], register="plain")
        end = next(c for c in ev["checks"] if c["key"] == "endings")
        self.assertIn("한다체", end["label"])
        self.assertTrue(end["ok"])


class RegisterApiTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()
        self.addCleanup(lambda: self.c.put("/api/style", json={"scope": "invest", "style_sample": ""}))

    def test_invest_uses_sample_register(self):
        self.c.put("/api/style", json={"scope": "invest", "style_sample": USER_SAMPLE})
        r = self.c.post("/api/articles/stream", json={"kind": "invest", "title": "요즘 시장 생각", "memo": "불안했다"})
        events = [b for b in r.get_data(as_text=True).strip().split("\n\n") if b.startswith("event: done")]
        done = json.loads(events[0].split("data: ", 1)[1])
        self.assertTrue(any("말투 샘플 어미(한다체" in n for n in done["notes"]))
        end = next(c for c in done["quality"]["checks"] if c["key"] == "endings")
        self.assertIn("한다체", end["label"])
        art = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(art["options"]["register"], "plain")


if __name__ == "__main__":
    unittest.main()
