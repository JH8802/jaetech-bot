"""실제 API 대신 가짜 클라이언트로 llm.py 의 SDK 사용 방식(스트리밍, 토큰 기록, 거절 처리)을 확인합니다."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm  # noqa: E402


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.text_stream = iter(chunks)
        self._final = SimpleNamespace(stop_reason=stop_reason, model="claude-opus-5-5",
                                      usage=SimpleNamespace(input_tokens=2000, output_tokens=5000))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._final


def fake_client(stream):
    calls = {}

    def make(**kw):
        calls.update(kw)
        return stream
    client = SimpleNamespace(messages=SimpleNamespace(stream=make), beta=SimpleNamespace(messages=SimpleNamespace(stream=make)))
    return client, calls


class LlmTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("BLOGDEX_MOCK", None)

    def test_stream_collects_text_and_usage_with_fallbacks(self):
        client, calls = fake_client(FakeStream(["가나", "다라"]))
        usage = {}
        with mock.patch.object(llm, "get_client", return_value=client):
            text = "".join(llm.stream_text("sys", "user", usage=usage))
        self.assertEqual(text, "가나다라")
        self.assertEqual(usage["input_tokens"], 2000)
        self.assertAlmostEqual(usage["cost_usd"], (2000 * 4 + 5000 * 20) / 1_000_000)
        self.assertEqual(calls["fallbacks"], "default")
        self.assertEqual(calls["output_config"], {"effort": llm.EFFORT})

    def test_refusal_raises(self):
        client, _ = fake_client(FakeStream(["x"], stop_reason="refusal"))
        with mock.patch.object(llm, "get_client", return_value=client):
            with self.assertRaises(llm.RefusedError):
                list(llm.stream_text("sys", "user"))

    def test_max_tokens_raises(self):
        client, _ = fake_client(FakeStream(["x"], stop_reason="max_tokens"))
        with mock.patch.object(llm, "get_client", return_value=client):
            with self.assertRaises(llm.TruncatedError):
                list(llm.stream_text("sys", "user"))

    def test_estimate_cost_unknown_model(self):
        self.assertIsNone(llm.estimate_cost("unknown", 1, 1))

    def test_placeholder_key_gives_clear_error(self):
        llm._client = None
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-여기에_API_키_입력"}):
            with self.assertRaises(RuntimeError) as cm:
                llm.get_client()
        self.assertIn("예시 문구", str(cm.exception))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                llm.get_client()


if __name__ == "__main__":
    unittest.main()
