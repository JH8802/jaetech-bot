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

    def test_version_endpoint(self):
        r = self.c.get("/api/version")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["version"])

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
        tags = done["body"].split("\n\n")[-1]
        self.assertTrue(5 <= tags.count("#") <= 10)  # 해시태그는 5~10개
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
        rules = prompts.build_system("food", False, "strict", 2)
        self.assertIn("올린 순서일 뿐 글의 순서가 아닙니다", rules)      # 번호 순서 강제 제거
        self.assertNotIn("사진 1 → 2 → 3 순서", rules)
        self.assertIn("인트로(첫 소제목 앞)에는 사진을 두지 않습니다", rules)
        self.assertIn("분량을 채우는 수단이 아니", rules)               # 쓸모없는 사물 묘사 금지
        self.assertIn("배경 소품", prompts.VISION_SYSTEM)


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


    def test_persona_in_both_kinds_and_new_hashtag_and_keyword_rules(self):
        import prompts
        for kind in ("info", "food"):
            sysmsg = prompts.build_system(kind, False, "strict")
            self.assertIn("30대 직장인 부부", sysmsg)
            self.assertIn("딸 한 명", sysmsg)
            self.assertIn("유머", sysmsg)
            self.assertIn("긍정", sysmsg)
            self.assertIn("딸과 함께 갔다", sysmsg)         # 지어내기 금지 예시
            self.assertIn("5~10개", sysmsg)                # 해시태그
            self.assertNotIn("28~30개", sysmsg)
            self.assertIn("1,000자당 4~6회", sysmsg)       # 키워드

    def test_hashtags_are_core_keywords_first_and_at_most_ten(self):
        for kind, extra in (("food", {"place": {"name": "놉스 사당점", "address": "서울 동작구 동작대로5길 8"}}), ("info", {"place": {}})):
            _, events = self._stream(kind=kind, keywords=["놉스 사당점", "사당 스테이크"], **extra)
            tags = dict(events)["done"]["body"].split("\n\n")[-1].split()
            self.assertLessEqual(len(tags), 10)
            self.assertGreaterEqual(len(tags), 5)
            self.assertIn("#놉스사당점", tags[:4])          # 핵심 키워드 태그가 앞쪽
            self.assertEqual(len(tags), len(set(tags)))

    def test_short_food_with_photos_gets_one_expansion_pass(self):
        _, events = self._stream(photos=[self.PIXEL, self.PIXEL])
        done = dict(events)["done"]
        self.assertGreaterEqual(done["chars"], 2100)
        self.assertTrue(any("보강" in n for n in done["notes"]))
        self.assertEqual([p for p in done["body"].split("\n\n") if p.startswith("<사진")], ["<사진1>", "<사진2>"])  # 사진 자리 유지
        self.assertTrue(done["body"].split("\n\n")[-1].startswith("#"))  # 해시태그는 마지막

    def test_no_expansion_when_material_is_thin(self):
        _, events = self._stream(memo="금요일 붐빔")  # 메모 짧고 사진 없음 → 늘리지 않는다
        done = dict(events)["done"]
        self.assertLess(done["chars"], 1900)
        self.assertFalse(any("보강" in n for n in done["notes"]))

    def test_expand_prompt_carries_keywords_and_blocks_new_feelings(self):
        import prompts
        up = prompts.build_expand_prompt("food", "본문", 1500, 2400, "메모", [{"n": 1, "category": "음식", "desc": "스테이크", "text": ""}], ["놉스 사당점", "사당 스테이크"])
        self.assertIn("[핵심 키워드]\n놉스 사당점, 사당 스테이크", up)
        self.assertIn("1,000자당 4~6회", up)
        self.assertIn("새로운 감정", up)

    def test_expansion_failure_keeps_original(self):
        from unittest import mock
        with mock.patch.object(A.llm, "ask_text", side_effect=RuntimeError("boom")):
            _, events = self._stream(photos=[self.PIXEL])
        done = dict(events)["done"]
        self.assertTrue(any("실패" in n for n in done["notes"]))
        self.assertIn("<사진1>", done["body"])

    def test_info_kind_is_not_expanded(self):
        _, events = self._stream(kind="info", photos=[self.PIXEL], place={})
        self.assertFalse(any("보강" in n for n in dict(events)["done"]["notes"]))


if __name__ == "__main__":
    unittest.main()
