"""
tests/test_ai_metrics.py
Phase 3 — AI observability metrics.

Verifies the additive AI-pipeline metrics record correctly through the REAL
backend path for representative routes, that labels are bounded, and that the
LLM framework metrics stay wired even while synthesis/explanation is disabled —
without changing any application behavior.

Run: pytest tests/test_ai_metrics.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from prometheus_client import REGISTRY

from backend.entrypoint import handle_user_query
from state.context_manager import clear_context
from telemetry import metrics


def _val(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _sum(name: str) -> float:
    """Sum a counter across all label sets (…_total) or a histogram's _count."""
    total = 0.0
    for m in REGISTRY.collect():
        for s in m.samples:
            if s.name == name:
                total += s.value
    return total


class TestAiMetricsRecorded(unittest.TestCase):
    def test_routing_latency_recorded(self):
        before = _sum("ai_routing_duration_seconds_count")
        clear_context("ai-r"); handle_user_query("who is the advisor for physical therapy", "ai-r")
        self.assertGreater(_sum("ai_routing_duration_seconds_count"), before)

    def test_retrieval_metrics_recorded(self):
        before = _sum("ai_retrieval_requests_total")
        clear_context("ai-ret"); handle_user_query("what is the deadline for public health", "ai-ret")
        # A topic route drives the Chroma retriever → a hit or empty outcome.
        after = _sum("ai_retrieval_requests_total")
        self.assertGreater(after, before)
        # top_score + per-doc score histograms observed too.
        self.assertGreater(_sum("ai_retrieval_top_score_count"), 0)

    def test_answer_metrics_recorded(self):
        before = _sum("ai_answer_total")
        clear_context("ai-a")
        handle_user_query("What funding opportunities are available for graduate students", "ai-a")
        self.assertGreater(_sum("ai_answer_total"), before)
        self.assertGreater(_sum("ai_answer_duration_seconds_count"), 0)

    def test_recommendation_metrics_recorded(self):
        before = _sum("ai_recommendation_behavior_total")
        clear_context("ai-rec")
        handle_user_query("I want to become a nurse practitioner and pursue a DNP.", "ai-rec")
        self.assertGreater(_sum("ai_recommendation_behavior_total"), before)
        # recommend behavior for this query → a candidate + confidence recorded.
        self.assertGreater(_sum("ai_recommendation_candidates_count"), 0)


class TestLlmFrameworkAlwaysWired(unittest.TestCase):
    def test_explanation_disabled_metric_when_flag_off(self):
        # With the explanation flag OFF (default), a recommend still records the
        # explanation DEMAND as outcome="disabled" — proving the framework metric
        # is wired even when the LLM never runs.
        before = _val("ai_recommendation_explanation_total", outcome="disabled")
        import agents.recommendation_explainer as expl
        with mock.patch.object(expl, "_ENABLED", False):
            clear_context("ai-d")
            handle_user_query("I want to become a nurse practitioner and pursue a DNP.", "ai-d")
        self.assertGreater(_val("ai_recommendation_explanation_total", outcome="disabled"), before)

    def test_llm_metrics_recorded_on_synthesis(self):
        # Force the synthesis path with the network mocked → success metric.
        import agents.llm_synthesizer as llm
        before = _val("ai_llm_requests_total", model=llm._MODEL, operation="synthesis", outcome="success")
        with mock.patch.object(llm, "_ENABLED", True), \
             mock.patch.object(llm, "_call_ollama", return_value="ok"), \
             mock.patch.object(llm, "_validate", return_value={"answer": "ok", "confidence": "high"}):
            llm.synthesize_answer("q", {"answer": "ctx"}, "f.json", source_url="https://x")
        self.assertEqual(
            _val("ai_llm_requests_total", model=llm._MODEL, operation="synthesis", outcome="success") - before,
            1.0)

    def test_llm_error_and_retry_metrics(self):
        import agents.llm_synthesizer as llm
        err_before = _sum("ai_llm_errors_total")
        with mock.patch.object(llm, "_ENABLED", True), \
             mock.patch.object(llm, "_call_ollama", side_effect=RuntimeError("boom")):
            out = llm.synthesize_answer("q", {"answer": "ctx"}, "f.json")
        self.assertIsNone(out)                                  # fallback preserved
        self.assertGreater(_sum("ai_llm_errors_total"), err_before)


class TestBoundedCardinality(unittest.TestCase):
    def test_no_high_cardinality_ai_labels(self):
        # Drive a distinctive session + query, then assert neither leaks into any
        # ai_* metric label (they belong in logs/traces).
        clear_context("SECRET-AI-SESSION")
        handle_user_query("who is the advisor for physical therapy", "SECRET-AI-SESSION")
        for m in REGISTRY.collect():
            if not m.name.startswith("ai_"):
                continue
            for s in m.samples:
                for lv in s.labels.values():
                    self.assertNotIn("SECRET-AI-SESSION", lv)
                    self.assertNotIn("physical therapy", lv)


if __name__ == "__main__":
    unittest.main()
