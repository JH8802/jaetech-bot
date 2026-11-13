import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402
import eval_style  # noqa: E402
import outline  # noqa: E402
import prompts  # noqa: E402
from tests.test_api import parse_sse  # noqa: E402

SAMPLE = """**📈 [주제 1] 11월 연말정산 미리보기: 신용카드 vs 체크카드 황금비율**

- **메인 키워드**: `연말정산 미리보기 신용카드 체크카드`
- **세부/연관 키워드**: `연말정산 총급여 25% 계산`, `신용카드 체크카드 소득공제율`, `홈택스 연말정산 모의계산`
- **검색자 니즈**: 남은 11~12월에 무슨 카드를 얼마나 써야 환급금을 최대로 뽑아내는지 행동 지침을 원함.

**[소제목 목차 구성]**
1. **홈택스 연말정산 미리보기, 11월에 열자마자 확인해야 하는 이유**
   - 1~9월 누적 카드 사용액 조회 방법
2. **기본 원칙: '총급여의 25%' 문턱부터 넘었는지 체크하기**
   - 25%까지는 공제가 안 되니 신용카드가 이득인 이유
3. **[비교 1] 11~12월 카드 황금비율: 신용카드(15%) vs 체크카드·현금(30%)**
4. **한도 채운 후 추가 꿀팁: 전통시장(40%)과 대중교통(80%) 활용**
5. **3줄 요약: 남은 두 달, 내 지갑 속 카드 사용 체크리스트**
"""


class OutlineParseTest(unittest.TestCase):
    def test_parse(self):
        p = outline.parse(SAMPLE)
        self.assertEqual(p["topic"], "11월 연말정산 미리보기: 신용카드 vs 체크카드 황금비율")
        self.assertEqual(p["main"], "연말정산 미리보기 신용카드 체크카드")
        self.assertEqual(p["subs"], ["연말정산 총급여 25% 계산", "신용카드 체크카드 소득공제율", "홈택스 연말정산 모의계산"])
        self.assertTrue(p["needs"].startswith("남은 11~12월"))
        self.assertEqual(len(p["sections"]), 5)
        self.assertEqual(p["sections"][0]["points"], ["1~9월 누적 카드 사용액 조회 방법"])
        self.assertEqual(p["sections"][2]["heading"], "[비교 1] 11~12월 카드 황금비율: 신용카드(15%) vs 체크카드·현금(30%)")

    def test_plain_format(self):
        p = outline.parse("주제: 제주 맛집\n메인 키워드: 제주 흑돼지\n1) 위치\n2) 메뉴")
        self.assertEqual((p["topic"], p["main"], [s["heading"] for s in p["sections"]]), ("제주 맛집", "제주 흑돼지", ["위치", "메뉴"]))

    def test_coverage(self):
        heads = outline.headings(SAMPLE)
        body_heads = ["1. 홈택스 연말정산 미리보기, 11월에 확인할 이유", "2. 기본 원칙: 총급여 25% 문턱 넘었는지 체크",
                      "3. [비교 1] 11~12월 카드 황금비율", "4. 한도 채운 뒤 전통시장과 대중교통 활용"]
        self.assertEqual(outline.coverage(heads, body_heads), [heads[4]])

    def test_prompt_block_and_rules(self):
        user = prompts.build_article_prompt("info", "제목", ["연말정산"], "메모", None, outline_text=SAMPLE)
        self.assertIn("[글 구성 - 작성자가 기획한 설계도. 사실 자료가 아님]", user)
        self.assertIn("  5. 3줄 요약: 남은 두 달, 내 지갑 속 카드 사용 체크리스트", user)
        self.assertIn("구성에 적힌 숫자", user)
        self.assertNotIn("[글 구성", prompts.build_article_prompt("info", "제목", [], "메모", None))
        self.assertNotIn("[글 구성", prompts.build_article_prompt("invest", "제목", [], "메모", None, outline_text=SAMPLE))
        self.assertIn("[글 구성", prompts.build_rewrite_prompt("info", "본문", ["고칠 점"], [], outline_text=SAMPLE))

    def test_eval_check(self):
        body = "인트로 연말정산.\n\n1. 홈택스 연말정산 미리보기, 11월에 확인할 이유\n\n본문이다.\n\n#a #b #c #d #e"
        q = eval_style.evaluate("info", body, ["연말정산"], outline_heads=outline.headings(SAMPLE))
        c = next(c for c in q["checks"] if c["key"] == "outline")
        self.assertFalse(c["ok"])
        self.assertEqual(c["value"], "1/5개")
        q2 = eval_style.evaluate("info", body, ["연말정산"])
        self.assertFalse(any("글 구성" in c["label"] for c in q2["checks"]))


class OutlineApiTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})
        p.start()
        self.addCleanup(p.stop)
        self.c = A.app.test_client()

    def test_parse_api(self):
        r = self.c.post("/api/outline/parse", json={"text": SAMPLE})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["main"], "연말정산 미리보기 신용카드 체크카드")
        self.assertEqual(self.c.post("/api/outline/parse", json={"text": "아무 말"}).status_code, 400)

    def test_stream_saves_outline_and_checks(self):
        r = self.c.post("/api/articles/stream", json={"kind": "info", "title": "연말정산 미리보기", "memo": "메모", "outline": SAMPLE})
        events = parse_sse(r.get_data(as_text=True))
        done = events[-1][1]
        self.assertTrue(any("글 구성" in c["label"] for c in done["quality"]["checks"]))
        saved = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(saved["options"]["outline"], SAMPLE.strip())
        self.assertEqual(self.c.post("/api/articles/stream", json={"kind": "info", "title": "x", "outline": "가" * 5000}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
