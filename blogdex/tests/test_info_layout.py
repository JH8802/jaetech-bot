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
import postprocess as pp  # noqa: E402
import prompts  # noqa: E402

RATINGS = [{"label": "맛", "score": 4}, {"label": "가격", "score": 3}, {"label": "주차", "score": 2}]
RAW = ("시청역 근처 놉스에 다녀왔어요. 양이 많았습니다.\n\n"
       "📋 한눈에 보기\n위치: 서울 중구 세종대로 135\n영업시간: [확인 필요: 영업시간]\n주차: 불가\n\n"
       "1. 가는 길\n\n휴무: 매주 월요일\n대기: 주말 점심 20분\n\n"
       "① 앱에서 줄서기 등록\n② 알림 오면 입장\n\n광화문 ➡ 시청 ➡ 명동\n\n"
       "[별점 이유]\n맛: 고기가 부드럽고 양이 넉넉함\n주차: 근처 공영주차장 이용\n없는항목: 무시\n\n"
       "한 줄 평: 양 많은 시청 맛집입니다.\n\n#놉스 #시청맛집 #a #b #c")


class InfoLayoutTest(unittest.TestCase):
    def test_box_label_lines_steps_route_kept(self):
        body = pp.finalize("food", RAW, {"name": "놉스 시청점"}, ["놉스"], ratings=RATINGS)["body"]
        self.assertIn("📋 한눈에 보기\n위치: 서울 중구 세종대로 135\n영업시간: [확인 필요: 영업시간]\n주차: 불가", body)
        self.assertIn("휴무: 매주 월요일\n대기: 주말 점심 20분", body)
        self.assertIn("① 앱에서 줄서기 등록\n② 알림 오면 입장", body)
        self.assertIn("광화문 ➡ 시청 ➡ 명동", body)
        self.assertIn("시청역 근처 놉스에 다녀왔어요.\n양이 많았습니다.", body)  # 일반 문장은 여전히 한 줄에 한 문장

    def test_rating_reasons_moved_into_block_and_survive_refinalize(self):
        body = pp.finalize("food", RAW, {"name": "놉스 시청점"}, ["놉스"], ratings=RATINGS)["body"]
        self.assertNotIn("[별점 이유]", body)
        self.assertIn("맛 ★★★★☆ 4/5 — 고기가 부드럽고 양이 넉넉함", body)
        self.assertIn("가격 ★★★☆☆ 3/5\n", body)  # 이유가 없는 항목은 점수만
        self.assertIn("주차 ★★☆☆☆ 2/5 — 근처 공영주차장 이용", body)
        self.assertNotIn("없는항목", body)
        again = pp.finalize("food", body, {"name": "놉스 시청점"}, ["놉스"], ratings=RATINGS)["body"]
        self.assertIn("맛 ★★★★☆ 4/5 — 고기가 부드럽고 양이 넉넉함", again)  # 다시 정리해도 이유 유지
        self.assertEqual(again.count("★ 별점 한눈에 보기"), 1)

    def test_series_related_line_and_hashtag(self):
        s = {"name": "서울시티투어버스", "part": 1}
        body = pp.finalize("hotel", RAW, {"name": "타이거버스"}, ["타이거버스"], series=s)["body"]
        paras = pp.split_paragraphs(body)
        self.assertEqual(paras[-2], "(관련 글 링크 삽입: 〈서울시티투어버스〉 다른 편)")
        self.assertIn("#서울시티투어버스", paras[-1])
        self.assertEqual(pp.finalize("hotel", body, {"name": "타이거버스"}, ["타이거버스"], series=s)["body"].count("관련 글 링크 삽입"), 1)
        self.assertNotIn("관련 글 링크 삽입", pp.finalize("hotel", body, {"name": "타이거버스"}, ["타이거버스"])["body"])

    def test_eval_skips_box_and_counts_label_lines_separately(self):
        body = pp.finalize("food", RAW, {"name": "놉스 시청점"}, ["놉스"], ratings=RATINGS)["body"]
        self.assertTrue(eval_style.evaluate("food", body, ["놉스"])["checks"])
        self.assertEqual(eval_style._sentences("휴무: 월요일\n대기: 20분"), ["휴무: 월요일", "대기: 20분"])

    def test_prompts_have_layout_rules_except_invest(self):
        for kind in ("info", "food", "hotel"):
            self.assertIn("[정보 정리 형식", prompts.build_system(kind, False, "strict"))
        self.assertNotIn("[정보 정리 형식", prompts.build_system("invest", True, "strict", register="plain"))
        self.assertIn("[별점 이유]", prompts.build_system("food", False, "strict"))
        up = prompts.build_article_prompt("food", "t", ["k"], "m", None, series={"name": "서울시티투어버스", "part": 2})
        self.assertIn("'서울시티투어버스' 시리즈 2편", up)


class SeriesApiTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()

    def test_series_title_and_options(self):
        self.assertEqual(A.series_title("타이거버스 총정리", {"name": "x", "part": 1}), "타이거버스 총정리 (1편)")
        self.assertEqual(A.series_title("타이거버스 총정리 (1편)", {"name": "x", "part": 1}), "타이거버스 총정리 (1편)")
        self.assertIsNone(A.read_series({"series": {"name": "x"}}, "invest"))
        r = self.c.post("/api/articles/stream", json={"kind": "hotel", "title": "타이거버스 총정리", "memo": "탔다",
                                                      "place": {"name": "타이거버스"}, "series": {"name": "서울시티투어버스", "part": "1"}})
        done = json.loads([b for b in r.get_data(as_text=True).strip().split("\n\n") if b.startswith("event: done")][0].split("data: ", 1)[1])
        self.assertEqual(done["title"], "타이거버스 총정리 (1편)")
        self.assertIn("관련 글 링크 삽입", done["body"])
        art = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(art["options"]["series"], {"name": "서울시티투어버스", "part": 1})


if __name__ == "__main__":
    unittest.main()
