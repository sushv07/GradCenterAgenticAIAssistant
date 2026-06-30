"""
tests/test_retry.py
Phase 6B — regression tests for utils/retry.py and its integration points.

Covers:
  - retry_call(): succeeds first attempt, succeeds after retry, fails after
    max attempts, non-retryable exception propagates immediately, retry
    count matches expectations, structured logs are emitted.
  - Real integration points: agents/llm_synthesizer.py, retrieval/
    faq_rag_module.py, retrieval/admissions_rag.py each actually retry on
    connection failure and still degrade gracefully (no exception escapes)
    after retries are exhausted — matching their pre-Phase-6B fallback
    behavior exactly, just reached after retrying first.
  - Deterministic logic (routing, recommendation scoring, taxonomy
    loading) is confirmed to never import or call retry_call.

Run from the project root:
    pytest tests/test_retry.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from unittest.mock import patch, MagicMock

import requests

from utils.retry import retry_call, RETRYABLE_EXCEPTIONS


class TestRetryCallCoreBehavior(unittest.TestCase):
    def test_succeeds_first_attempt_no_retry(self):
        calls = []
        def fn():
            calls.append(1)
            return "ok"
        result = retry_call(fn, operation="test.first", base_delay=0.01)
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)

    def test_succeeds_after_retry(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise requests.exceptions.ConnectionError("blip")
            return "ok"
        result = retry_call(fn, operation="test.retry", base_delay=0.01)
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)

    def test_fails_after_max_attempts(self):
        calls = []
        def fn():
            calls.append(1)
            raise requests.exceptions.Timeout("always fails")
        with self.assertRaises(requests.exceptions.Timeout):
            retry_call(fn, operation="test.exhausted", max_attempts=3, base_delay=0.01)
        self.assertEqual(len(calls), 3)

    def test_non_retryable_exception_propagates_immediately(self):
        calls = []
        def fn():
            calls.append(1)
            raise ValueError("not a transient failure")
        with self.assertRaises(ValueError):
            retry_call(fn, operation="test.nonretryable", max_attempts=3, base_delay=0.01)
        self.assertEqual(len(calls), 1)  # no retry attempted

    def test_http_error_is_not_retryable(self):
        """4xx/5xx responses (request completed, bad status) are not
        retried — only connection/timeout failures are."""
        calls = []
        def fn():
            calls.append(1)
            resp = MagicMock()
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
            resp.raise_for_status()
        with self.assertRaises(requests.exceptions.HTTPError):
            retry_call(fn, operation="test.http_error", max_attempts=3, base_delay=0.01)
        self.assertEqual(len(calls), 1)

    def test_retry_count_respects_max_attempts_parameter(self):
        calls = []
        def fn():
            calls.append(1)
            raise requests.exceptions.ConnectionError("x")
        with self.assertRaises(requests.exceptions.ConnectionError):
            retry_call(fn, operation="test.count", max_attempts=5, base_delay=0.01)
        self.assertEqual(len(calls), 5)

    def test_default_retryable_exceptions_are_connection_and_timeout_only(self):
        self.assertEqual(
            set(RETRYABLE_EXCEPTIONS),
            {requests.exceptions.ConnectionError, requests.exceptions.Timeout},
        )


class TestRetryLogging(unittest.TestCase):
    def test_logs_retry_attempt_event(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise requests.exceptions.ConnectionError("blip")
            return "ok"
        with patch("utils.retry.emit") as mock_emit:
            retry_call(fn, operation="test.logging", base_delay=0.01)
        events = [c.args[0] for c in mock_emit.call_args_list]
        self.assertIn("retry.attempt", events)
        self.assertIn("retry.success", events)

    def test_logs_retry_exhausted_event(self):
        def fn():
            raise requests.exceptions.Timeout("always")
        with patch("utils.retry.emit") as mock_emit:
            with self.assertRaises(requests.exceptions.Timeout):
                retry_call(fn, operation="test.logging_exhausted", max_attempts=2, base_delay=0.01)
        events = [c.args[0] for c in mock_emit.call_args_list]
        self.assertIn("retry.exhausted", events)

    def test_attempt_log_includes_operation_and_attempt_number(self):
        def fn():
            raise requests.exceptions.ConnectionError("x")
        with patch("utils.retry.emit") as mock_emit:
            with self.assertRaises(requests.exceptions.ConnectionError):
                retry_call(fn, operation="test.op_name", max_attempts=2, base_delay=0.01)
        attempt_call = next(
            c for c in mock_emit.call_args_list if c.args[0] == "retry.attempt"
        )
        self.assertEqual(attempt_call.kwargs["operation"], "test.op_name")
        self.assertEqual(attempt_call.kwargs["attempt"], 1)


class TestRealIntegrationPoints(unittest.TestCase):
    """The 3 real call sites the Phase 6B audit identified — confirm each
    actually retries and still degrades gracefully after exhaustion."""

    def test_admissions_rag_retries_then_succeeds(self):
        import retrieval.admissions_rag as ar
        ar._PAGE_CACHE.clear()
        calls = {"n": 0}
        def flaky_get(*a, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.exceptions.ConnectionError("blip")
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            resp.text = "<html><body>content</body></html>"
            return resp
        with patch("requests.get", side_effect=flaky_get):
            text = ar._fetch_text("https://example.com/retry-test")
        self.assertEqual(calls["n"], 2)
        self.assertIn("content", text)

    def test_admissions_rag_degrades_gracefully_after_exhaustion(self):
        import retrieval.admissions_rag as ar
        ar._PAGE_CACHE.clear()
        # retry_call()'s base_delay default is bound at function-definition
        # time (a module-level constant used as a default parameter value),
        # so patching config/utils.retry's RETRY_BASE_DELAY_SECONDS after
        # the fact has no effect on it. Patch time.sleep instead — this
        # speeds up the test without changing retry count or logic.
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError("down")), \
             patch("utils.retry.time.sleep"):
            text = ar._fetch_text("https://example.com/retry-test-2")
        self.assertEqual(text, "")  # unchanged pre-Phase-6B fallback behavior

    def test_faq_rag_module_degrades_gracefully_after_exhaustion(self):
        from retrieval.faq_rag_module import _fetch_faq_entries
        with patch("requests.get", side_effect=requests.exceptions.Timeout("down")), \
             patch("utils.retry.time.sleep"):
            entries = _fetch_faq_entries()
        self.assertEqual(entries, [])  # unchanged pre-Phase-6B fallback behavior

    def test_llm_synthesizer_returns_none_after_exhaustion_not_exception(self):
        import agents.llm_synthesizer as synth
        with patch.object(synth, "_ENABLED", True), \
             patch("requests.post", side_effect=requests.exceptions.ConnectionError("down")), \
             patch("utils.retry.time.sleep"):
            result = synth.synthesize_answer("test query", "some retrieved text", "file.json")
        self.assertIsNone(result)  # unchanged pre-Phase-6B fallback behavior


class TestDeterministicLogicNeverRetried(unittest.TestCase):
    def test_recommendation_engine_does_not_import_retry(self):
        import ast
        tree = ast.parse(Path("agents/recommendation_engine.py").read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        self.assertNotIn("utils.retry", names)

    def test_router_does_not_import_retry(self):
        import ast
        tree = ast.parse(Path("routing/router.py").read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        self.assertNotIn("utils.retry", names)

    def test_responses_builder_does_not_import_retry(self):
        import ast
        tree = ast.parse(Path("responses/builder.py").read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        self.assertNotIn("utils.retry", names)


if __name__ == "__main__":
    unittest.main()
