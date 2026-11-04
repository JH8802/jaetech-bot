import json
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

PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


class VideoPostprocessTest(unittest.TestCase):
    def test_markers_cleaned_and_missing_added_before_closing(self):
        raw = ("인트로예요.\n\n1. 입구\n\n입구가 넓었어요. <동영상2>\n\n<동영상2>\n\n<동영상9>\n\n"
               "한 줄 평: 아이가 좋아했어요.\n\n#a #b #c #d #e")
        fin = pp.finalize("hotel", raw, {"name": "동물원"}, ["동물원"], video_count=2)
        paras = pp.split_paragraphs(fin["body"])
        self.assertEqual(paras.count("<동영상2>"), 1)
        self.assertNotIn("<동영상9>", fin["body"])
        i = paras.index("<동영상1>")
        self.assertTrue(paras[i + 1].startswith("한 줄 평"))  # 빠진 1번은 맺음 앞
        self.assertTrue(any("동영상 1번" in n for n in fin["notes"]))
        self.assertEqual(pp.count_chars("가나다\n\n<동영상1>\n\n#a #b #c"), 3)  # 동영상 자리는 글자 수에 안 셈

    def test_video_rules_and_block(self):
        self.assertIn("[동영상 자리 규칙]", prompts.build_system("food", False, "strict", video_count=1))
        self.assertNotIn("[동영상 자리 규칙]", prompts.build_system("food", False, "strict"))
        b = prompts.video_block([{"n": 1, "name": "IMG_1.mp4", "duration": 75, "desc": "입구 장면"}, {"n": 2, "name": "IMG_2.mov"}])
        self.assertIn("동영상 1 (파일명 IMG_1.mp4, 길이 1:15): 입구 장면", b)
        self.assertIn("동영상 2 (파일명 IMG_2.mov): 장면을 읽지 못함", b)


class VideoApiTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()

    def test_read_videos(self):
        v = A.read_videos({"videos": [{"frame": PIXEL, "name": "a.mp4", "duration": "12.34"}, {"frame": "", "name": "b.mov"}]}, "food")
        self.assertEqual(v[0]["image"]["media_type"], "image/png")
        self.assertEqual(v[0]["duration"], 12.3)
        self.assertIsNone(v[1]["image"])
        self.assertEqual(A.read_videos({"videos": [{"name": "a"}]}, "invest"), [])
        with self.assertRaises(ValueError):
            A.read_videos({"videos": [{"name": "a"}] * 11}, "food")

    def test_stream_places_videos_and_saves_names(self):
        r = self.c.post("/api/articles/stream", json={
            "kind": "hotel", "title": "동물원 후기", "memo": "IMG_1 영상은 입구, IMG_2 영상은 카피바라", "place": {"name": "동물원"},
            "videos": [{"frame": PIXEL, "name": "IMG_1.mp4", "duration": 8}, {"frame": "", "name": "IMG_2.mp4", "duration": 15}]})
        done = json.loads([b for b in r.get_data(as_text=True).strip().split("\n\n") if b.startswith("event: done")][0].split("data: ", 1)[1])
        self.assertIn("<동영상1>", done["body"])
        self.assertIn("<동영상2>", done["body"])
        self.assertEqual([v["name"] for v in done["videos"]], ["IMG_1.mp4", "IMG_2.mp4"])
        self.assertTrue(done["videos"][0]["desc"])  # 장면이 있는 동영상은 설명이 붙음
        self.assertEqual(done["videos"][1]["desc"], "")  # 장면이 없으면 파일명·길이만
        art = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(art["options"]["videos"][1]["name"], "IMG_2.mp4")


if __name__ == "__main__":
    unittest.main()
