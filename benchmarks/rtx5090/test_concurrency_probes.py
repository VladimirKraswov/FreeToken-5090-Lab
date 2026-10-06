"""Transport and accounting regressions without a model, GPU or network."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import concurrency_fixed as fixed


def sse(content, tokens, finish="length", done=True):
    items = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": content}}]},
        {"choices": [{"delta": {}, "finish_reason": finish}],
         "usage": {"prompt_tokens": 10, "completion_tokens": tokens,
                   "total_tokens": 10 + tokens,
                   "prompt_tokens_details": {"cached_tokens": 0}}},
    ]
    data = b"".join(b"data: " + json.dumps(item).encode() + b"\n\n" for item in items)
    return data + (b"data: [DONE]\n\n" if done else b"")


class ProbeTests(unittest.TestCase):
    def call(self, response, quality=False):
        with patch.object(fixed.urllib.request, "urlopen", return_value=io.BytesIO(response)):
            return fixed.one("http://localhost", 3, 0, threading.Barrier(1), 0, "nonce", quality)

    def test_complete_stream_has_exact_budget(self):
        row = self.call(sse("answer", 3))
        self.assertTrue(row["done"] and row["fixed_output_ok"])
        self.assertEqual(row["usage"]["completion_tokens"], 3)

    def test_missing_done_is_not_a_success(self):
        row = self.call(sse("answer", 3, done=False))
        self.assertIn("incomplete stream", row["error"])

    def test_early_stop_is_not_fixed_work(self):
        row = self.call(sse("answer", 2, finish="stop"))
        self.assertFalse(row["fixed_output_ok"])

    def test_natural_json_is_valid_without_fixed_budget(self):
        answer = {"marker": "SESSION_0_nonce", "sum": 45, "needle": "VIOLET_0"}
        row = self.call(sse(json.dumps(answer), 17, finish="stop"), quality=True)
        self.assertTrue(row["quality_ok"] and row["fixed_output_ok"])
        wrong = self.call(sse(json.dumps({**answer, "sum": 46}), 17, finish="stop"), quality=True)
        self.assertFalse(wrong["quality_ok"])

    def test_contaminated_accounting_is_saved_and_rejected(self):
        before = {"instance_id": "same", "requests": {
            "active": 0, "completed": 0, "prompt_tokens_total": 0, "completion_tokens_total": 0}}
        after = {"instance_id": "same", "requests": {
            "active": 0, "completed": 2, "prompt_tokens_total": 20, "completion_tokens_total": 6}}
        row = self.call(sse("answer", 3))
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(base="http://localhost", tokens=3, quality=False,
                                   corpus_seed="transport-test", repeat=1, profile="test", out=folder)
            with patch.object(fixed, "get", side_effect=[before, after]), \
                    patch.object(fixed, "one", return_value=row), \
                    patch.object(fixed, "monitor_stats"), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    fixed.run_wave(args, 0, 1)
            report = json.loads((Path(folder) / "test-p0-c1.json").read_text())
            self.assertFalse(report["counters_ok"])
            self.assertTrue(report["rows"][0]["done"])


if __name__ == "__main__":
    unittest.main()
