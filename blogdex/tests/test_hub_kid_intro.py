import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402
import postprocess as pp  # noqa: E402
import prompts  # noqa: E402
import storage  # noqa: E402
from tests.test_api import parse_sse  # noqa: E402

RAW = ("인트로예요.\n\n📋 비발디파크\n📍 홍천\n\n1. 객실\n\n넓었어요.\n\n2. 식당\n\n맛있었어요.\n\n"
       "한 줄 평: 또 가고 싶어요.\n\n#비발디파크 #홍천 #a #b #c")


class SeriesListTest(unittest.TestCase):
    def test_other_parts_block_after_intro(self):
        series = {"name": "비발디파크", "part": 3, "others": [{"part": 1, "title": "오션월드 실내"}, {"part": 2, "title": "객실 후기"}]}
        fin = pp.finalize("hotel", RAW, {"name": "비발디파크"}, ["비발디파크"], series=series)
        paras = pp.split_paragraphs(fin["body"])
        i = next(i for i, p in enumerate(paras) if p.startswith("📚"))
        self.assertEqual(paras[i].split("\n")[1:], ["① 1편 오션월드 실내", "② 2편 객실 후기"])
        self.assertTrue(paras[i + 1].startswith("📋"))   # 인트로 바로 뒤, 박스 앞
        self.assertIn("〈비발디파크〉 다른 편)", fin["body"])  # 글 끝 자리도 그대로
        again = pp.finalize("hotel", fin["body"], {"name": "비발디파크"}, ["비발디파크"], series=series)
        self.assertEqual(again["body"].count("📚"), 1)

    def test_hub_links_filled(self):
        raw = ("인트로.\n\n📋 한눈에 보기\n일정: 1박 2일\n\n1. 오션월드\n\n좋았다.\n\n(관련 글 링크 삽입: 〈오션월드〉)\n\n"
               "2. 객실\n\n넓었다.\n\n3. 총평\n\n추천.\n\n한 줄 평: 좋다.\n\n#a #b #c #d #e")
        series = {"name": "", "hub": True, "hub_titles": ["오션월드", "객실"]}
        fin = pp.finalize("hotel", raw, {}, ["비발디파크"], series=series)
        paras = pp.split_paragraphs(fin["body"])
        self.assertEqual(fin["body"].count("관련 글 링크 삽입"), 2)
        j = paras.index("(관련 글 링크 삽입: 〈객실〉)")
        self.assertTrue(pp.HEADING_RE.match(paras[j + 1]))    # 2번 섹션 끝(3번 소제목 앞)
        self.assertNotIn("내 다른 글", fin["body"])


class KidMemoTest(unittest.TestCase):
    def test_clean(self):
        memo = "맛있었다\n\n" + prompts.KID_TEMPLATE_HEAD + "\n아이 나이: 6세\n유아의자: \n키즈 메뉴: 돈가스 9,000원\n주차:"
        out = prompts.clean_kid_memo(memo)
        self.assertIn("아이 나이: 6세", out)
        self.assertIn("키즈 메뉴: 돈가스 9,000원", out)
        self.assertNotIn("유아의자", out)
        self.assertNotIn("주차", out)
        self.assertIn(prompts.KID_TEMPLATE_HEAD, out)
        empty = prompts.clean_kid_memo("맛있었다\n" + prompts.KID_TEMPLATE_HEAD + "\n유아의자:\n주차: ")
        self.assertEqual(empty, "맛있었다")


class IntroPromptTest(unittest.TestCase):
    def test_system_block(self):
        sys_ = prompts.build_system("food", False, "strict", blog_intro="아이 손 잡고 다니는 서울 아빠")
        self.assertIn("[블로그 정체성", sys_)
        self.assertNotIn("[블로그 정체성", prompts.build_system("food", False, "strict"))
        self.assertIn("'오션월드 겨울'", prompts.build_title_prompt("hotel", "오션월드", "메모", None, [], False))


class ApiTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()

    def _write(self, title, part):
        r = self.c.post("/api/articles/stream", json={"kind": "hotel", "title": title, "memo": "좋았다",
                                                      "place": {"name": "비발디파크"}, "series": {"name": "비발디파크테스트", "part": part}})
        return parse_sse(r.get_data(as_text=True))[-1][1]

    def test_series_others_and_hub(self):
        d1 = self._write("오션월드 실내", 1)
        d2 = self._write("객실 후기", 2)
        self.assertIn("① 1편 오션월드 실내", d2["body"])
        lst = self.c.get("/api/articles").get_json()["articles"]
        self.assertEqual(next(a for a in lst if a["id"] == d2["article_id"])["series"], {"name": "비발디파크테스트", "part": 2})
        r = self.c.post("/api/hub/stream", json={"ids": [d1["article_id"], d2["article_id"]]})
        done = parse_sse(r.get_data(as_text=True))[-1][1]
        self.assertEqual(done["title"], "비발디파크테스트 총정리")
        self.assertIn("관련 글 링크 삽입", done["body"])
        self.assertEqual(self.c.post("/api/hub/stream", json={"ids": [d1["article_id"]]}).status_code, 400)

    def test_kid_memo_cleaned_on_save(self):
        memo = "좋았다\n" + prompts.KID_TEMPLATE_HEAD + "\n유아의자: 있음\n주차: "
        r = self.c.post("/api/articles/stream", json={"kind": "food", "title": "놉스", "memo": memo, "place": {"name": "놉스"}})
        done = parse_sse(r.get_data(as_text=True))[-1][1]
        saved = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertIn("유아의자: 있음", saved["memo"])
        self.assertNotIn("주차", saved["memo"])

    def test_blog_intro_api(self):
        self.assertEqual(self.c.put("/api/blog-intro", json={"blog_intro": "  서울 아빠  "}).get_json()["blog_intro"], "서울 아빠")
        self.assertEqual(self.c.get("/api/blog-intro").get_json()["blog_intro"], "서울 아빠")
        self.assertEqual(self.c.put("/api/blog-intro", json={"blog_intro": "가" * 81}).status_code, 400)
        storage.set_setting("blog_intro", "")


if __name__ == "__main__":
    unittest.main()
