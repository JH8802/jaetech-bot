import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402
import prompts  # noqa: E402
from tests.test_api import parse_sse  # noqa: E402


class PlanUnitTest(unittest.TestCase):
    def test_split_title_plan(self):
        text = ("서울상상나라 6세 아이와 실내 체험 후기\n두 번째 제목\n\n**메인 키워드**: `6세 아이와 가볼만한곳 실내`\n"
                "- 세부 키워드: 서울상상나라 후기, 서울 실내 아이와\n검색자 니즈: 비 오는 주말 6세가 지루해하지 않을 곳")
        lines, plan = prompts.split_title_plan(text)
        self.assertEqual([l for l in lines if l.strip()], ["서울상상나라 6세 아이와 실내 체험 후기", "두 번째 제목"])
        self.assertEqual(plan, {"main": "6세 아이와 가볼만한곳 실내", "subs": ["서울상상나라 후기", "서울 실내 아이와"],
                                "needs": "비 오는 주말 6세가 지루해하지 않을 곳"})

    def test_title_prompt_asks_plan_except_invest(self):
        self.assertIn("검색자 니즈:", prompts.build_title_prompt("food", "놉스", "메모", None, [], False))
        self.assertNotIn("검색자 니즈:", prompts.build_title_prompt("invest", "", "메모", None, [], True))

    def test_plan_in_article_prompt(self):
        plan = {"main": "연말정산 미리보기", "subs": ["체크카드 공제율"], "needs": "남은 두 달 카드 전략"}
        user = prompts.build_article_prompt("info", "제목", ["연말정산"], "메모", None, plan=plan)
        self.assertIn("[검색 기획", user)
        self.assertIn("검색자 니즈: 남은 두 달 카드 전략", user)
        self.assertNotIn("[검색 기획", prompts.build_article_prompt("info", "제목", [], "메모", None))
        self.assertNotIn("[검색 기획", prompts.build_article_prompt("invest", "제목", [], "메모", None, plan=plan))
        self.assertIn("[검색 기획", prompts.build_rewrite_prompt("info", "본문", ["x"], [], plan=plan))
        self.assertIsNone(prompts.read_plan({"main": "", "needs": ""}))

    def test_photo_prompt_reads_menu_and_hours(self):
        self.assertIn("영업·운영 시간", prompts.build_photo_analysis_prompt("food", "t", None, 2))


class PlanApiTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()

    def test_titles_return_plan_and_keywords(self):
        d = self.c.post("/api/titles", json={"kind": "food", "keyword": "놉스 사당점 후기", "memo": "삼겹살", "place": {"name": "놉스 사당점"}}).get_json()
        self.assertEqual(d["plan"]["main"], "샘플 메인 키워드")
        self.assertEqual(d["keywords"][0], "놉스 사당점")          # 맛집은 장소 이름이 먼저
        self.assertIn("샘플 메인 키워드", d["keywords"])
        self.assertFalse(any("키워드" in t or "니즈" in t for t in d["titles"]))
        d2 = self.c.post("/api/titles", json={"kind": "info", "keyword": "연말정산", "memo": "메모"}).get_json()
        self.assertEqual(d2["keywords"][0], "샘플 메인 키워드")    # 정보글은 기획한 메인 키워드가 먼저

    def test_stream_saves_plan_and_note(self):
        plan = {"main": "연말정산 미리보기", "subs": ["체크카드"], "needs": "남은 두 달 카드 전략"}
        r = self.c.post("/api/articles/stream", json={"kind": "info", "title": "연말정산 미리보기", "memo": "메모", "plan": plan})
        done = parse_sse(r.get_data(as_text=True))[-1][1]
        self.assertTrue(done["notes"][0].startswith("이번 글 구성: 소제목"))
        self.assertIn("남은 두 달 카드 전략", done["notes"][0])
        saved = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(saved["options"]["plan"]["main"], "연말정산 미리보기")


if __name__ == "__main__":
    unittest.main()
