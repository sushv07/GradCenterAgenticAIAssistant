"""
tests/test_request_trace.py
Phase 8E — regression tests for the end-to-end request trace layer.

Covers:
  - Grouping events by request_id (including the "" bucket).
  - Event-to-stage normalization (stage_for_event()).
  - Trace stage reconstruction: routing, retrieval, recommendation, llm,
    tool, retry, error stages all populated correctly from fixture events.
  - Retrieval stage summary (ran/completed_count/returned_count/etc).
  - Recommendation stage summary (decision vs. clarify vs. redirect).
  - LLM stage summary (synthesis vs. explanation, fallback detection).
  - Error/fallback detection.
  - Missing request_id handling (excluded by default, includable on request).
  - Report generation (obs/trace_summary.py).
  - Event ordering preserved within a trace.
  - End-to-end: a real call through handle_user_query() reconstructs into
    one coherent trace with the expected route/query/stages — and proves
    the new request.started/.completed events don't change response
    content (the actual behavioral guarantee this phase must uphold).

Run from the project root:
    pytest tests/test_request_trace.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest

from obs.request_trace import (
    stage_for_event,
    group_events_by_request_id,
    build_trace,
    reconstruct_traces,
    RequestTrace,
)
from obs.trace_summary import summarize_traces, format_console_summary


def _write_fixture_log(records: list[dict]) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8")
    for r in records:
        f.write(json.dumps(r) + "\n")
    f.close()
    return Path(f.name)


class TestStageNormalization(unittest.TestCase):
    def test_known_prefixes_map_correctly(self):
        cases = {
            "request.started":          "request",
            "request.complete":         "request",
            "route.decision":            "routing",
            "retrieval.completed":      "retrieval",
            "retrieval.failed":          "retrieval",
            "keyword.retrieval":         "retrieval",
            "faq_rag.query":             "retrieval",
            "advisor.match":             "retrieval",
            "tool.result":                "tool",
            "recommendation.decision":   "recommendation",
            "recommendation.clarify":    "recommendation",
            "llm.synthesis.result":      "llm",
            "llm.explanation.start":     "llm",
            "retry.attempt":              "retry",
            "store.lifecycle":            "infrastructure",
            "taxonomy.load_failed":       "error",
            "backend.unhandled_exception": "error",
        }
        for event_name, expected_stage in cases.items():
            self.assertEqual(stage_for_event(event_name), expected_stage, event_name)

    def test_unknown_prefix_maps_to_other(self):
        self.assertEqual(stage_for_event("totally_unknown.event"), "other")
        self.assertEqual(stage_for_event("no_dot_at_all"), "other")


class TestGroupingByRequestId(unittest.TestCase):
    def test_groups_by_request_id(self):
        events = [
            {"request_id": "a", "event": "route.decision"},
            {"request_id": "b", "event": "route.decision"},
            {"request_id": "a", "event": "retrieval.completed"},
        ]
        groups = group_events_by_request_id(events)
        self.assertEqual(set(groups), {"a", "b"})
        self.assertEqual(len(groups["a"]), 2)
        self.assertEqual(len(groups["b"]), 1)

    def test_missing_request_id_groups_under_empty_string(self):
        events = [
            {"event": "store.lifecycle"},
            {"request_id": "", "event": "recommendation.score"},
        ]
        groups = group_events_by_request_id(events)
        self.assertIn("", groups)
        self.assertEqual(len(groups[""]), 2)

    def test_preserves_event_order_within_group(self):
        events = [
            {"request_id": "x", "event": "request.started", "ts": "1"},
            {"request_id": "x", "event": "route.decision", "ts": "2"},
            {"request_id": "x", "event": "retrieval.completed", "ts": "3"},
            {"request_id": "x", "event": "request.completed", "ts": "4"},
        ]
        groups = group_events_by_request_id(events)
        ordered_names = [e["event"] for e in groups["x"]]
        self.assertEqual(ordered_names,
                          ["request.started", "route.decision", "retrieval.completed", "request.completed"])


class TestTraceStageReconstruction(unittest.TestCase):
    def _basic_events(self) -> list[dict]:
        return [
            {"request_id": "r1", "event": "request.started", "ts": "2026-01-01T00:00:00.000Z",
             "session_id": "s1", "query": "when is the deadline", "level": "INFO"},
            {"request_id": "r1", "event": "route.decision", "ts": "2026-01-01T00:00:00.100Z",
             "route": "deadlines", "reason": "deadline_signal", "level": "INFO"},
            {"request_id": "r1", "event": "retrieval.started", "ts": "2026-01-01T00:00:00.200Z", "level": "INFO"},
            {"request_id": "r1", "event": "retrieval.completed", "ts": "2026-01-01T00:00:00.300Z",
             "returned_count": 3, "top_score": 0.61, "chunk_ids": ["c1", "c2", "c3"], "level": "INFO"},
            {"request_id": "r1", "event": "tool.result", "ts": "2026-01-01T00:00:00.400Z",
             "tool": "deadlines_tool", "found": True, "level": "INFO"},
            {"request_id": "r1", "event": "request.completed", "ts": "2026-01-01T00:00:00.500Z",
             "session_id": "s1", "route": "deadlines", "elapsed_ms": 500.0, "had_error": False, "level": "INFO"},
        ]

    def test_routing_stage_populated(self):
        trace = build_trace("r1", self._basic_events())
        self.assertIn("routing", trace.stages)
        self.assertEqual(len(trace.stages["routing"]), 1)
        self.assertEqual(trace.route, "deadlines")

    def test_retrieval_stage_populated(self):
        trace = build_trace("r1", self._basic_events())
        self.assertIn("retrieval", trace.stages)
        self.assertEqual(len(trace.stages["retrieval"]), 2)

    def test_tool_stage_populated(self):
        trace = build_trace("r1", self._basic_events())
        self.assertIn("tool", trace.stages)

    def test_query_and_session_id_inferred(self):
        trace = build_trace("r1", self._basic_events())
        self.assertEqual(trace.query, "when is the deadline")
        self.assertEqual(trace.session_id, "s1")

    def test_total_elapsed_from_request_completed(self):
        trace = build_trace("r1", self._basic_events())
        self.assertEqual(trace.total_elapsed_ms, 500.0)

    def test_started_completed_timestamps(self):
        trace = build_trace("r1", self._basic_events())
        self.assertEqual(trace.started_at, "2026-01-01T00:00:00.000Z")
        self.assertEqual(trace.completed_at, "2026-01-01T00:00:00.500Z")

    def test_event_count(self):
        trace = build_trace("r1", self._basic_events())
        self.assertEqual(trace.event_count, 6)


class TestRetrievalStageSummary(unittest.TestCase):
    def test_summary_when_retrieval_ran_successfully(self):
        events = [
            {"event": "retrieval.completed", "returned_count": 2, "top_score": 0.5, "chunk_ids": ["a", "b"]},
        ]
        trace = build_trace("r1", events)
        self.assertTrue(trace.retrieval_summary["ran"])
        self.assertEqual(trace.retrieval_summary["returned_count"], 2)
        self.assertEqual(trace.retrieval_summary["chunk_ids"], ["a", "b"])

    def test_summary_when_retrieval_failed(self):
        events = [{"event": "retrieval.failed", "reason": "store_unavailable"}]
        trace = build_trace("r1", events)
        self.assertTrue(trace.retrieval_summary["ran"])
        self.assertEqual(trace.retrieval_summary["failure_reasons"], ["store_unavailable"])

    def test_summary_when_no_retrieval(self):
        trace = build_trace("r1", [{"event": "route.decision", "route": "advisor"}])
        self.assertFalse(trace.retrieval_summary["ran"])


class TestRecommendationStageSummary(unittest.TestCase):
    def test_decision_outcome(self):
        events = [{"event": "recommendation.decision", "behavior": "recommend",
                   "confidence": "high", "recommended_programs": ["dnp-nursing"]}]
        trace = build_trace("r1", events)
        self.assertEqual(trace.recommendation_summary["behavior"], "recommend")
        self.assertEqual(trace.final_behavior, "recommend")

    def test_clarify_outcome(self):
        events = [{"event": "recommendation.clarify", "clarification_question": "What's your degree?"}]
        trace = build_trace("r1", events)
        self.assertEqual(trace.recommendation_summary["behavior"], "clarify")
        self.assertEqual(trace.final_behavior, "clarify")

    def test_redirect_outcome(self):
        events = [{"event": "recommendation.redirect", "redirect_reason": "out_of_scope"}]
        trace = build_trace("r1", events)
        self.assertEqual(trace.recommendation_summary["behavior"], "redirect")


class TestLLMStageSummary(unittest.TestCase):
    def test_synthesis_success(self):
        events = [{"event": "llm.synthesis.start"}, {"event": "llm.synthesis.result", "confidence": "high", "elapsed_ms": 100.0}]
        trace = build_trace("r1", events)
        self.assertTrue(trace.llm_summary["synthesis_ran"])
        self.assertEqual(trace.llm_summary["synthesis_confidence"], "high")
        self.assertNotIn("synthesis_fell_back", trace.llm_summary)

    def test_synthesis_fallback_detected(self):
        events = [{"event": "llm.synthesis.start"}, {"event": "llm.synthesis.error", "error": "timeout"}]
        trace = build_trace("r1", events)
        self.assertTrue(trace.llm_summary["synthesis_fell_back"])

    def test_explanation_tracked_separately_from_synthesis(self):
        events = [{"event": "llm.explanation.start"}, {"event": "llm.explanation.result", "elapsed_ms": 50.0}]
        trace = build_trace("r1", events)
        self.assertTrue(trace.llm_summary["explanation_ran"])
        self.assertFalse(trace.llm_summary["synthesis_ran"])


class TestErrorAndFallbackDetection(unittest.TestCase):
    def test_error_level_events_collected(self):
        events = [
            {"event": "backend.unhandled_exception", "level": "ERROR", "error_type": "ValueError"},
            {"event": "route.decision", "level": "INFO"},
        ]
        trace = build_trace("r1", events)
        self.assertEqual(len(trace.errors), 1)
        self.assertEqual(trace.errors[0]["event"], "backend.unhandled_exception")

    def test_fallback_events_collected(self):
        events = [
            {"event": "retry.exhausted", "level": "ERROR"},
            {"event": "retrieval.failed", "level": "ERROR"},
            {"event": "llm.synthesis.error", "level": "WARNING"},
        ]
        trace = build_trace("r1", events)
        self.assertEqual(len(trace.fallbacks), 3)

    def test_no_errors_or_fallbacks_for_clean_trace(self):
        events = [{"event": "route.decision", "level": "INFO", "route": "deadlines"}]
        trace = build_trace("r1", events)
        self.assertEqual(trace.errors, [])
        self.assertEqual(trace.fallbacks, [])


class TestMissingRequestIdHandling(unittest.TestCase):
    def test_excluded_by_default(self):
        records = [
            {"request_id": "", "event": "store.lifecycle"},
            {"request_id": "r1", "event": "route.decision", "route": "deadlines"},
        ]
        path = _write_fixture_log(records)
        traces = reconstruct_traces(path)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].request_id, "r1")
        path.unlink()

    def test_includable_on_request(self):
        records = [
            {"request_id": "", "event": "store.lifecycle"},
            {"request_id": "r1", "event": "route.decision", "route": "deadlines"},
        ]
        path = _write_fixture_log(records)
        traces = reconstruct_traces(path, include_empty_request_id=True)
        self.assertEqual(len(traces), 2)
        self.assertIn("", [t.request_id for t in traces])
        path.unlink()


class TestReportGeneration(unittest.TestCase):
    def _fixture_log(self) -> Path:
        records = [
            {"request_id": "r1", "event": "request.started", "ts": "t0", "query": "q1"},
            {"request_id": "r1", "event": "route.decision", "ts": "t1", "route": "deadlines"},
            {"request_id": "r1", "event": "retrieval.completed", "ts": "t2", "returned_count": 2},
            {"request_id": "r1", "event": "request.completed", "ts": "t3", "route": "deadlines", "elapsed_ms": 120.0},
            {"request_id": "r2", "event": "request.started", "ts": "t0", "query": "q2"},
            {"request_id": "r2", "event": "route.decision", "ts": "t1", "route": "advisor"},
            {"request_id": "r2", "event": "request.completed", "ts": "t2", "route": "advisor", "elapsed_ms": 40.0},
        ]
        return _write_fixture_log(records)

    def test_summarize_traces_counts(self):
        path = self._fixture_log()
        summary = summarize_traces(path)
        self.assertEqual(summary["total_traces"], 2)
        self.assertEqual(summary["traces_with_retrieval"], 1)
        self.assertEqual(summary["average_total_elapsed_ms"], 80.0)
        path.unlink()

    def test_slowest_traces_sorted_descending(self):
        path = self._fixture_log()
        summary = summarize_traces(path, slowest_n=2)
        elapsed = [t["elapsed_ms"] for t in summary["slowest_traces"]]
        self.assertEqual(elapsed, sorted(elapsed, reverse=True))
        path.unlink()

    def test_format_console_summary_does_not_raise(self):
        path = self._fixture_log()
        summary = summarize_traces(path)
        text = format_console_summary(summary)
        self.assertIn("Request Trace Summary", text)
        path.unlink()

    def test_empty_log_produces_zeroed_summary(self):
        summary = summarize_traces(Path("/tmp/definitely_does_not_exist_8e.log"))
        self.assertEqual(summary["total_traces"], 0)
        self.assertEqual(summary["average_total_elapsed_ms"], 0.0)


class TestEndToEndReconstruction(unittest.TestCase):
    """Exercises the real backend.entrypoint.handle_user_query() and
    reconstructs the resulting log lines back into a trace — the actual
    integration this whole phase exists to support."""

    def test_real_request_reconstructs_into_one_coherent_trace(self):
        from gradcenter_logging import new_request_id, set_request_id, get_request_id
        from backend.entrypoint import handle_user_query
        from state.context_manager import clear_context
        import tempfile, gradcenter_logging

        sid = "e2e-trace-test"
        clear_context(sid)
        rid = new_request_id()
        set_request_id(rid)

        response = handle_user_query("when is the application deadline", session_id=sid)
        clear_context(sid)

        traces = reconstruct_traces(include_empty_request_id=False)
        matching = [t for t in traces if t.request_id == rid]
        self.assertEqual(len(matching), 1)
        trace = matching[0]

        self.assertEqual(trace.route, response["route"])
        self.assertEqual(trace.session_id, sid)
        self.assertIn("routing", trace.stages)
        self.assertIn("retrieval", trace.stages)
        self.assertIn("tool", trace.stages)
        self.assertIsNotNone(trace.total_elapsed_ms)

    def test_response_content_unaffected_by_new_request_events(self):
        """The actual behavioral guarantee Phase 8E must uphold: adding
        request.started/.completed must not change what handle_user_query()
        returns."""
        from unittest.mock import patch
        from backend.entrypoint import handle_user_query
        from state.context_manager import clear_context

        sid = "e2e-trace-no-mutation"
        clear_context(sid)
        r1 = handle_user_query("when is the application deadline", session_id=sid)
        clear_context(sid)
        with patch("backend.entrypoint.emit"):
            r2 = handle_user_query("when is the application deadline", session_id=sid)
        clear_context(sid)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
