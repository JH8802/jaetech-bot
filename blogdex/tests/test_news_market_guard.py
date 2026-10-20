import json
import os
import sys
import tempfile
import unittest

os.environ["BLOGDEX_MOCK"] = "1"
os.environ.setdefault("BLOGDEX_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402

import invest_guard
import market
import news
import postprocess as pp
import prompts

NAVER_HTML = '''<html><head><title>x</title><meta property="og:title" content="미 연준, 금리 동결">
<meta property="og:article:author" content="연합뉴스 | 네이버"></head><body>
<header><p>메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴</p></header>
<span data-date-time="2026-10-19 08:12:00"></span>
<article id="dic_area">미국 연방준비제도가 기준금리를 동결했다.<br>파월 의장은 "연내 인하 가능성"을 언급했다.<img src="a.jpg"><br>
<script>var a = 1;</script>나스닥은 1.2% 올랐다. 이 문장은 본문 길이를 채우기 위한 문장입니다.</article>
<div>관련 기사 광고 문구 관련 기사 광고 문구</div></body></html>'''


class NewsTest(unittest.TestCase):
    def test_parse_naver_article(self):
        a = news.parse_article(NAVER_HTML, "https://n.news.naver.com/article/001/1")
        self.assertEqual(a["title"], "미 연준, 금리 동결")
        self.assertEqual(a["source"], "연합뉴스")
        self.assertTrue(a["published"].startswith("2026-10-19"))
        self.assertIn("기준금리를 동결했다", a["text"])
        self.assertIn("나스닥은 1.2% 올랐다", a["text"])
        self.assertNotIn("var a", a["text"])
        self.assertNotIn("광고 문구", a["text"])

    def test_generic_site_uses_paragraphs_and_euc_kr(self):
        body = "<p>" + "경제 기사 문단입니다. " * 5 + "</p>"
        html = f'<html><head><meta charset="euc-kr"><title>제목</title></head><body>{body * 3}</body></html>'
        text = news._decode(html.encode("cp949"), "text/html")
        a = news.parse_article(text, "https://example.com/a")
        self.assertIn("경제 기사 문단입니다", a["text"])

    def test_url_check_rejects_bad_scheme_and_local(self):
        with self.assertRaises(news.FetchError):
            news.check_url("ftp://example.com")
        with self.assertRaises(news.FetchError):
            news.check_url("http://127.0.0.1/x")

    def test_read_news_list_limits(self):
        self.assertEqual(news.read_news_list(None), [])
        with self.assertRaises(ValueError):
            news.read_news_list([{"text": "a"}] * 4)
        self.assertEqual(len(news.read_news_list([{"text": "본문", "title": "t"}, {"text": ""}])), 1)


class MarketTest(unittest.TestCase):
    CHART = {"chart": {"result": [{"meta": {"gmtoffset": 32400}, "timestamp": [1760900000, 1760986400, 1761072800],
                                   "indicators": {"quote": [{"close": [2600.0, None, 2613.0]}]}}]}}

    def test_parse_and_memo(self):
        q = market.parse_chart(self.CHART)
        self.assertAlmostEqual(q["pct"], 0.5)
        snap = market.fetch_snapshot(get_json=lambda url: self.CHART)
        memo = market.to_memo(snap)
        self.assertTrue(memo.startswith("[자동 시황 - "))
        self.assertIn("- 코스피 2,613.00 (+0.50%", memo)
        self.assertIn("원/달러 환율 2,613.0원", memo)

    def test_failures_are_listed(self):
        def boom(url):
            raise OSError("blocked")
        snap = market.fetch_snapshot(get_json=boom)
        self.assertEqual(snap["items"], [])
        self.assertEqual(len(snap["failed"]), len(market.SYMBOLS))


class InvestFormatAndGuardTest(unittest.TestCase):
    RAW = ("요즘 시장이 불안해요. 그래도 원칙은 지킵니다! 나스닥이 1.2% 올랐다는 기사를 봤어요.\n\n1. 요즘 시장\n\n"
           "이 종목은 무조건 오릅니다. 지금이 기회라서 매수하세요. 저는 천천히 나눠 사려고 해요.\n\n"
           "한 줄 정리: 흔들려도 원칙대로 가려고요.\n\n#주식 #투자일기 #원칙 #시장 #마음")

    def test_one_sentence_per_line_and_source_block(self):
        news_list = [{"source": "연합뉴스", "title": "금리 동결", "published": "2026-10-19 08:12", "url": "https://x"}]
        body = pp.finalize("invest", self.RAW, None, [], news=news_list)["body"]
        self.assertIn("요즘 시장이 불안해요.\n그래도 원칙은 지킵니다!\n나스닥이 1.2% 올랐다는 기사를 봤어요.", body)
        paras = pp.split_paragraphs(body)
        self.assertTrue(paras[-2].startswith(pp.SOURCE_HEAD))
        self.assertIn("연합뉴스 「금리 동결」 (2026-10-19) https://x", paras[-2])
        # 다시 정리해도 참고 기사 문단은 하나뿐
        again = pp.finalize("invest", body, None, [], news=news_list)["body"]
        self.assertEqual(again.count(pp.SOURCE_HEAD), 1)

    def test_remove_violations_and_disclaimer(self):
        body = pp.finalize("invest", self.RAW, None, [])["body"]
        self.assertTrue(invest_guard.violations(body))
        cleaned, removed = invest_guard.remove_violations(body)
        self.assertEqual(len(removed), 2)
        self.assertEqual(invest_guard.violations(cleaned), [])
        self.assertIn("저는 천천히 나눠 사려고 해요.", cleaned)
        withd, added = invest_guard.ensure_disclaimer(cleaned)
        self.assertTrue(added)
        paras = pp.split_paragraphs(withd)
        i = next(i for i, p in enumerate(paras) if p.startswith("한 줄 정리"))
        self.assertEqual(paras[i - 1], invest_guard.DISCLAIMER)
        self.assertFalse(invest_guard.ensure_disclaimer(withd)[1])  # 이미 있으면 다시 넣지 않음

    def test_soft_context_does_not_hide_imperative(self):
        hits = invest_guard.violations("놓치지 않으려면 지금 매수하세요.")
        self.assertTrue(hits)
        self.assertEqual(invest_guard.violations("무조건 오른다고 단정하지 않습니다."), [])


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        patcher = mock.patch.dict(os.environ, {"BLOGDEX_MOCK": "1"})  # 다른 테스트가 환경을 바꿔도 샘플 모드로
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app_mod = A
        self.c = A.app.test_client()

    def test_style_per_kind_falls_back_to_common(self):
        self.c.put("/api/style", json={"style_sample": "공통 말투"})
        self.c.put("/api/style", json={"scope": "invest", "style_sample": "투자 말투"})
        self.assertEqual(self.app_mod.style_for("invest"), "투자 말투")
        self.assertEqual(self.app_mod.style_for("food"), "공통 말투")
        d = self.c.get("/api/style").get_json()
        self.assertEqual(d["samples"]["invest"]["text"], "투자 말투")
        self.assertEqual(d["style_sample"], "공통 말투")
        self.c.put("/api/style", json={"scope": "invest", "style_sample": ""})
        self.assertEqual(self.app_mod.style_for("invest"), "공통 말투")
        self.assertEqual(self.c.put("/api/style", json={"scope": "bad", "style_sample": "x"}).status_code, 400)

    def test_invest_guard_is_forced_and_title_checked(self):
        c = self.app_mod.read_common({"kind": "invest", "guardrail": False})
        self.assertTrue(c["guardrail"])
        r = self.c.post("/api/articles/stream", json={"kind": "invest", "title": "무조건 오르는 종목", "memo": "메모"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("무조건", r.get_json()["error"])

    def test_market_and_news_preview_mock(self):
        d = self.c.get("/api/market").get_json()
        self.assertIn("[자동 시황", d["memo"])
        a = self.c.post("/api/news/preview", json={"url": "https://example.com"}).get_json()["article"]
        self.assertTrue(a["text"])

    def test_news_saved_with_article(self):
        art = {"url": "https://x", "title": "금리 동결", "source": "연합뉴스", "published": "2026-10-19", "text": "기사 본문"}
        r = self.c.post("/api/articles/stream", json={"kind": "invest", "title": "요즘 시장 생각", "memo": "불안했다", "news": [art]})
        self.assertEqual(r.status_code, 200)
        events = [b for b in r.get_data(as_text=True).strip().split("\n\n") if b.startswith("event: done")]
        done = json.loads(events[0].split("data: ", 1)[1])
        self.assertIn("참고한 기사", done["body"])
        full = self.c.get(f"/api/articles/{done['article_id']}").get_json()["article"]
        self.assertEqual(full["options"]["news"][0]["source"], "연합뉴스")
        self.assertIn("투자 판단과 책임", full["body"])  # 안내 문장 보장


if __name__ == "__main__":
    unittest.main()
