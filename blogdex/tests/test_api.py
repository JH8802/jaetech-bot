import json
import os
import sys
import tempfile
import unittest

os.environ["BLOGDEX_MOCK"] = "1"
_tmp = tempfile.mkdtemp()
os.environ["BLOGDEX_DB"] = os.path.join(_tmp, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402


def parse_sse(raw):
    events = []
    for block in raw.strip().split("\n\n"):
        ev = block.split("\n")[0].replace("event: ", "")
        data = json.loads(block.split("data: ", 1)[1])
        events.append((ev, data))
    return events


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.c = A.app.test_client()

    def test_titles_food_returns_keywords(self):
        r = self.c.post("/api/titles", json={"kind": "food", "keyword": "마포 고깃집", "place": {"name": "락희옥 마포본점", "address": "서울 마포구 백범로 170"}})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(len(d["titles"]), 5)
        self.assertIn("락희옥 마포본점", d["keywords"])

    def test_validation_errors(self):
        self.assertEqual(self.c.post("/api/titles", json={"kind": "zzz", "keyword": "x"}).status_code, 400)
        self.assertEqual(self.c.post("/api/titles", json={"kind": "info", "keyword": ""}).status_code, 400)
        self.assertEqual(self.c.post("/api/articles/stream", json={"kind": "info", "title": ""}).status_code, 400)
        self.assertEqual(self.c.post("/api/articles/stream", json={"kind": "info", "title": "x", "memo": "가" * 5000}).status_code, 400)
        self.assertEqual(self.c.post("/api/articles/stream", json={"kind": "info", "title": "x", "evidence_mode": "bad"}).status_code, 400)
        self.assertEqual(self.c.get("/nope").status_code, 404)

    def _generate(self, kind, title, **extra):
        r = self.c.post("/api/articles/stream", json={"kind": kind, "title": title, **extra})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "text/event-stream")
        return parse_sse(r.get_data(as_text=True))

    def test_stream_food_pipeline(self):
        events = self._generate("food", "직장인 회식 괜찮은 고깃집 락희옥 마포본점", memo="항정살이 맛있었고 직원이 친절했다",
                                place={"name": "락희옥 마포본점", "address": "서울 마포구 백범로 170"})
        names = [e for e, _ in events]
        self.assertEqual(names[0], "status")
        self.assertIn("chunk", names)
        self.assertEqual(names[-1], "done")
        done = events[-1][1]
        self.assertIn("플레이스 지도 삽입", done["body"])           # 맛집글은 지도 줄이 들어감
        self.assertEqual(done["body"].count("{{highlight}}"), 2)   # 형광펜은 정확히 2곳
        self.assertGreaterEqual(done["body"].count("#"), 28)
        self.assertIn("checks", done["quality"])
        saved = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(saved["kind"], "food")
        self.assertEqual(saved["memo"], "항정살이 맛있었고 직원이 친절했다")

    def test_stream_info_has_no_map_line_and_uses_guardrail_option(self):
        events = self._generate("info", "NMN 건강기능식품 고르는 법", guardrail=True)
        done = events[-1][1]
        self.assertNotIn("지도 삽입", done["body"])
        saved = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertTrue(saved["options"]["guardrail"])
        self.assertTrue(saved["keywords"])

    def test_system_prompts_differ_by_kind(self):
        import prompts
        info = prompts.build_system("info", True, "strict")
        food = prompts.build_system("food", False, "template")
        self.assertIn("정보글", info)
        self.assertIn("맛집글", food)
        self.assertIn("가드레일", info)
        self.assertNotIn("가드레일", food)
        self.assertIn("메모에 없는 구체 사실", info)
        self.assertIn("템플릿형", food)

    def test_list_rewrite_and_delete(self):
        done = self._generate("info", "리라이트 테스트")[-1][1]
        listing = self.c.get("/api/articles").get_json()["articles"]
        self.assertTrue(any(a["id"] == done["article_id"] for a in listing))
        rew = self.c.post(f"/api/articles/{done['article_id']}/rewrite")
        self.assertEqual(rew.status_code, 200)
        rdone = parse_sse(rew.get_data(as_text=True))[-1][1]
        saved = self.c.get(f"/api/articles/{rdone['article_id']}").get_json()["article"]
        self.assertEqual(saved["parent_id"], done["article_id"])
        res = self.c.delete("/api/articles", json={"ids": [done["article_id"], rdone["article_id"]]})
        self.assertEqual(res.get_json()["deleted"], 2)
        self.assertEqual(self.c.get(f"/api/articles/{done['article_id']}").status_code, 404)


    PIXEL = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

    def _stream(self, **extra):
        body = {"kind": "food", "title": "마포 삼겹살 테스트", "keywords": ["마포 삼겹살"], "memo": "금요일 붐빔",
                "place": {"name": "테스트 마포점"}, "guardrail": False, "evidence_mode": "strict"}
        body.update(extra)
        r = self.c.post("/api/articles/stream", json=body)
        return r, parse_sse(r.get_data(as_text=True)) if r.status_code == 200 else None

    def test_photos_are_analyzed_and_markers_placed(self):
        r, events = self._stream(photos=[self.PIXEL, self.PIXEL, self.PIXEL])
        self.assertEqual(r.status_code, 200)
        kinds = [e for e, _ in events]
        self.assertIn("photos", kinds)
        self.assertLess(kinds.index("photos"), kinds.index("chunk"))
        done = dict(events)["done"]
        self.assertEqual(len(done["photos"]), 3)
        body_paras = done["body"].split("\n\n")
        marks = [p for p in body_paras if p.startswith("<사진")]
        self.assertEqual(marks, ["<사진1>", "<사진2>", "<사진3>"])  # 모두 한 번씩, 번호 순서
        # 재작성에도 같은 사진 정보가 쓰이고 마커가 유지된다
        self.assertEqual(self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]["options"]["photos"], done["photos"])

    def test_no_photos_means_no_photo_markers(self):
        _, events = self._stream()
        self.assertNotIn("photos", [e for e, _ in events])
        self.assertNotIn("<사진", dict(events)["done"]["body"])

    def test_photo_validation(self):
        self.assertEqual(self._stream(photos=["not-a-data-url"])[0].status_code, 400)
        self.assertEqual(self._stream(photos=[self.PIXEL] * 16)[0].status_code, 400)
        self.assertEqual(self._stream(photos=["data:application/pdf;base64,AAAA"])[0].status_code, 400)

    def test_system_prompt_photo_rules(self):
        import prompts
        self.assertIn("<사진N>", prompts.build_system("food", False, "strict", 2))
        self.assertIn("사진이 없습니다", prompts.build_system("food", False, "strict", 0))
        self.assertIn("다른 가게 이름", prompts.build_system("food", False, "strict", 2))
        self.assertIn("옆 가게 간판", prompts.VISION_SYSTEM)


    def test_update_body_recomputes_quality_and_persists(self):
        _, events = self._stream()
        done = dict(events)["done"]
        self.assertIn("[확인 필요: 가격]", done["body"])
        new_body = done["body"].replace("[확인 필요: 가격]", "18,000원")
        r = self.c.put(f"/api/articles/{done['article_id']}/body", json={"body": new_body})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        todo = next(c for c in d["quality"]["checks"] if c["key"] == "todo")
        self.assertTrue(todo["ok"])  # 남은 확인 필요 0곳
        saved = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertIn("18,000원", saved["body"])
        self.assertEqual(saved["chars"], d["chars"])

    def test_update_body_validation(self):
        self.assertEqual(self.c.put("/api/articles/999999/body", json={"body": "x"}).status_code, 400)
        _, events = self._stream()
        aid = dict(events)["done"]["article_id"]
        self.assertEqual(self.c.put(f"/api/articles/{aid}/body", json={"body": "  "}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
