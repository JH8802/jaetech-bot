import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402
import place_info as P  # noqa: E402
import postprocess as pp  # noqa: E402
import prompts  # noqa: E402

PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


class PlaceInfoUnitTest(unittest.TestCase):
    def test_parse_and_details(self):
        info = P.parse("설명\n" + P.MOCK_JSON + "\n끝")
        self.assertEqual(info["phone"], "02-123-4567")
        d = P.to_details(info)
        self.assertIn("영업시간: 평일 11:30~22:00", d)
        self.assertIn("휴무: 매주 월요일", d)
        self.assertIn("메뉴·가격: 삼겹살 200g 17,000원", d)
        self.assertNotIn("02-123-4567", d)  # 전화·주소는 각자 칸으로

    def test_parse_bad_json(self):
        info = P.parse("모르겠어요")
        self.assertFalse(any(info.values()))

    def test_clean_link(self):
        self.assertEqual(P.clean_link("https://naver.me/abc123"), "https://naver.me/abc123")
        self.assertEqual(P.clean_link("[네이버 지도]\n가게\nhttps://naver.me/xY9z"), "https://naver.me/xY9z")
        self.assertEqual(P.clean_link("https://map.naver.com/p/entry/place/123?c=1"), "https://map.naver.com/p/entry/place/123?c=1")
        self.assertEqual(P.clean_link("https://evil.example.com/naver.me"), "")
        self.assertEqual(P.clean_link(""), "")


class PlaceLinkPostprocessTest(unittest.TestCase):
    RAW = ("인트로예요.\n\n📋 놉스 사당점\n📍 서울 동작구 1\n⏰ 11:00~22:00\n\n1. 메뉴\n\n고기가 맛있었어요.\n\n2. 총평\n\n또 갈래요.\n\n"
           "한 줄 평: 또 가고 싶은 집이에요.\n\n#놉스 #사당맛집 #a #b #c")

    def test_link_goes_into_box(self):
        fin = pp.finalize("food", self.RAW, {"name": "놉스 사당점", "link": "https://naver.me/abc"}, ["놉스"])
        box = next(p for p in pp.split_paragraphs(fin["body"]) if p.startswith("📋"))
        self.assertTrue(box.endswith("🔗 https://naver.me/abc"))
        self.assertEqual(fin["body"].count("https://naver.me/abc"), 1)

    def test_link_without_box_after_map_line(self):
        raw = self.RAW.replace("📋 놉스 사당점\n📍 서울 동작구 1\n⏰ 11:00~22:00\n\n", "")
        fin = pp.finalize("food", raw, {"name": "놉스 사당점", "link": "https://naver.me/abc"}, ["놉스"])
        paras = pp.split_paragraphs(fin["body"])
        i = next(i for i, p in enumerate(paras) if pp.MAP_LINE_MARK in p)
        self.assertEqual(paras[i + 1], "🔗 네이버 지도 https://naver.me/abc")

    def test_no_link_no_line(self):
        fin = pp.finalize("food", self.RAW, {"name": "놉스 사당점"}, ["놉스"])
        self.assertNotIn("🔗", fin["body"])

    def test_details_in_prompt(self):
        b = prompts._place_block({"name": "놉스", "details": "영업시간: 평일 11:00~22:00"})
        self.assertIn("[네이버 지도 정보", b)
        self.assertIn("영업시간: 평일 11:00~22:00", b)
        self.assertIn("메뉴판 사진(방문 당시 정보)을 우선", b)
        self.assertNotIn("네이버 지도 정보", prompts._place_block({"name": "놉스"}))


class PlaceInfoApiTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})  # 다른 테스트가 환경을 바꿔도 샘플 모드로
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()

    def test_read_from_capture(self):
        r = self.c.post("/api/place-info", json={"kind": "food", "name": "샘플", "images": [PIXEL]})
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertEqual(d["info"]["address"], "서울 마포구 샘플로 12 1층")
        self.assertIn("메뉴·가격:", d["details"])

    def test_requires_input(self):
        r = self.c.post("/api/place-info", json={"kind": "food", "name": "샘플"})
        self.assertEqual(r.status_code, 400)

    def test_too_many_captures(self):
        r = self.c.post("/api/place-info", json={"kind": "food", "images": [PIXEL] * 5})
        self.assertEqual(r.status_code, 400)

    def test_read_place_link_validation(self):
        p = A.read_place({"name": "놉스", "link": "https://naver.me/abc", "details": "휴무: 월"})
        self.assertEqual(p["link"], "https://naver.me/abc")
        self.assertEqual(p["details"], "휴무: 월")
        with self.assertRaises(ValueError):
            A.read_place({"name": "놉스", "link": "https://example.com/x"})


if __name__ == "__main__":
    unittest.main()
