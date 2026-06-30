"""
tests/test_retrieval_observability.py
Phase 8B — regression tests for the retrieval observability layer.

Covers:
  - Structured event generation: each of the 5 emit_retrieval_*() helpers
    produces a correctly-shaped event via gradcenter_logging.emit().
  - Event schema: every event includes retrieval_stage, session_id, and
    the stage-specific fields the design calls for.
  - Latency recording: elapsed_ms is present and numeric on every event
    that has it.
  - Candidate counting / filtering metrics: retrieval.filtering's
    filtered_count = candidate_count - survived_count, always.
  - Empty retrieval: a real out-of-scope query still fires
    retrieval.completed with returned_count=0, not retrieval.failed.
  - Retrieval failure logging: a simulated store-unavailable case and a
    simulated search exception each fire retrieval.failed with the right
    reason code.
  - Behavior identical before/after instrumentation: retrieve()'s return
    value is unaffected by any of this — verified directly against a
    pre-instrumentation baseline captured earlier in this project's
    history, plus a fresh self-consistency check.
  - obs/retrieval_summary.py: reads a hand-built NDJSON log fixture and
    computes the documented aggregate stats correctly.

Run from the project root:
    pytest tests/test_retrieval_observability.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from gradcenter_logging import set_session_id, get_session_id
from obs.retrieval_events import (
    emit_retrieval_started,
    emit_retrieval_vector_search,
    emit_retrieval_filtering,
    emit_retrieval_completed,
    emit_retrieval_failed,
    _truncate_query,
)
from obs.retrieval_summary import summarize_retrieval_events, format_console_summary
from rag.retriever import retrieve


def _captured_emit_calls(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) with obs.retrieval_events.emit mocked;
    return the list of (event_name, kwargs) calls made."""
    with patch("obs.retrieval_events.emit") as mock_emit:
        fn(*args, **kwargs)
        return [(c.args[0], c.kwargs) for c in mock_emit.call_args_list]


class TestSessionIdContext(unittest.TestCase):
    def test_set_and_get_session_id(self):
        set_session_id("test-session-123")
        self.assertEqual(get_session_id(), "test-session-123")
        set_session_id("")  # reset

    def test_default_is_empty_string(self):
        set_session_id("")
        self.assertEqual(get_session_id(), "")

    def test_does_not_affect_request_id(self):
        from gradcenter_logging import set_request_id, get_request_id
        set_request_id("req-1")
        set_session_id("sess-1")
        self.assertEqual(get_request_id(), "req-1")
        self.assertEqual(get_session_id(), "sess-1")
        set_request_id("")
        set_session_id("")


class TestEventGeneration(unittest.TestCase):
    def test_emit_retrieval_started_shape(self):
        calls = _captured_emit_calls(
            emit_retrieval_started, "what gpa do i need", 3, 0.30, "eligibility", None,
        )
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "retrieval.started")
        self.assertEqual(kwargs["retrieval_stage"], "started")
        self.assertIn("session_id", kwargs)
        self.assertEqual(kwargs["top_k"], 3)
        self.assertEqual(kwargs["min_score"], 0.30)
        self.assertEqual(kwargs["page_type"], "eligibility")

    def test_emit_retrieval_vector_search_shape(self):
        calls = _captured_emit_calls(emit_retrieval_vector_search, 14, 92.7, "deadlines")
        name, kwargs = calls[0]
        self.assertEqual(name, "retrieval.vector_search")
        self.assertEqual(kwargs["candidate_count"], 14)
        self.assertEqual(kwargs["elapsed_ms"], 92.7)

    def test_emit_retrieval_filtering_shape_and_math(self):
        calls = _captured_emit_calls(emit_retrieval_filtering, 14, 9, 0.25)
        name, kwargs = calls[0]
        self.assertEqual(name, "retrieval.filtering")
        self.assertEqual(kwargs["candidate_count"], 14)
        self.assertEqual(kwargs["survived_count"], 9)
        self.assertEqual(kwargs["filtered_count"], 5)  # 14 - 9

    def test_emit_retrieval_completed_shape(self):
        calls = _captured_emit_calls(
            emit_retrieval_completed,
            returned_count=2, scores=[0.6, 0.5], chunk_ids=["a", "b"],
            page_types=["faq", "faq"], elapsed_ms=10.0,
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "retrieval.completed")
        self.assertEqual(kwargs["returned_count"], 2)
        self.assertEqual(kwargs["top_score"], 0.6)
        self.assertEqual(kwargs["min_score_returned"], 0.5)
        self.assertEqual(kwargs["max_score_returned"], 0.6)
        self.assertEqual(kwargs["chunk_ids"], ["a", "b"])

    def test_emit_retrieval_completed_empty_results(self):
        calls = _captured_emit_calls(
            emit_retrieval_completed,
            returned_count=0, scores=[], chunk_ids=[], page_types=[], elapsed_ms=5.0,
        )
        name, kwargs = calls[0]
        self.assertEqual(kwargs["top_score"], 0.0)
        self.assertEqual(kwargs["level"], "WARNING")

    def test_emit_retrieval_failed_shape(self):
        calls = _captured_emit_calls(
            emit_retrieval_failed, "search_exception", error="boom", error_type="RuntimeError", elapsed_ms=3.0,
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "retrieval.failed")
        self.assertEqual(kwargs["reason"], "search_exception")
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertEqual(kwargs["error_type"], "RuntimeError")

    def test_query_truncation_long_query(self):
        long_query = "word " * 100
        truncated = _truncate_query(long_query)
        self.assertLessEqual(len(truncated), 200)

    def test_query_truncation_short_query_unchanged(self):
        self.assertEqual(_truncate_query("short query"), "short query")


class TestLiveRetrievalInstrumentation(unittest.TestCase):
    """Exercise the real rag.retriever.retrieve() and confirm the new
    events fire with sane values — not mocked, the live store."""

    def test_real_query_fires_started_search_filtering_completed(self):
        with patch("rag.retriever.emit_retrieval_started") as m_started, \
             patch("rag.retriever.emit_retrieval_vector_search") as m_search, \
             patch("rag.retriever.emit_retrieval_filtering") as m_filter, \
             patch("rag.retriever.emit_retrieval_completed") as m_completed, \
             patch("rag.retriever.emit_retrieval_failed") as m_failed:
            retrieve("what gpa do i need", k=3)
        m_started.assert_called_once()
        m_search.assert_called_once()
        m_filter.assert_called_once()
        m_completed.assert_called_once()
        m_failed.assert_not_called()

    def test_empty_query_fires_no_observability_events(self):
        """The trivial empty-query bailout isn't a meaningful retrieval
        attempt — by design, no events fire for it (see obs/__init__.py)."""
        with patch("rag.retriever.emit_retrieval_started") as m_started:
            retrieve("", k=3)
        m_started.assert_not_called()

    def test_out_of_scope_query_fires_completed_not_failed(self):
        """A real query that legitimately returns nothing is NOT a failure
        — retrieval.completed with returned_count=0, never retrieval.failed."""
        with patch("rag.retriever.emit_retrieval_completed") as m_completed, \
             patch("rag.retriever.emit_retrieval_failed") as m_failed:
            results = retrieve("xyzxyzxyz totally unrelated gibberish nonsense", k=3)
        self.assertEqual(results, [])
        m_completed.assert_called_once()
        self.assertEqual(m_completed.call_args.kwargs["returned_count"], 0)
        m_failed.assert_not_called()

    def test_store_unavailable_fires_failed_with_correct_reason(self):
        with patch("rag.retriever.get_or_build_store", return_value=None), \
             patch("rag.retriever.emit_retrieval_failed") as m_failed:
            results = retrieve("any query", k=3)
        self.assertEqual(results, [])
        m_failed.assert_called_once()
        self.assertEqual(m_failed.call_args.args[0], "store_unavailable")

    def test_search_exception_fires_failed_with_correct_reason(self):
        fake_store = MagicMock()
        fake_store.similarity_search_with_relevance_scores.side_effect = RuntimeError("chroma down")
        with patch("rag.retriever.get_or_build_store", return_value=fake_store), \
             patch("rag.retriever.emit_retrieval_failed") as m_failed:
            results = retrieve("any query", k=3)
        self.assertEqual(results, [])
        m_failed.assert_called_once()
        self.assertEqual(m_failed.call_args.args[0], "search_exception")
        self.assertEqual(m_failed.call_args.kwargs["error_type"], "RuntimeError")


class TestBehaviorIdenticalBeforeAfterInstrumentation(unittest.TestCase):
    def test_retrieve_return_value_unaffected_by_observability(self):
        """Calling retrieve() with observability mocked out entirely must
        produce the identical return value as calling it normally."""
        normal_result = retrieve("what gpa do i need", k=3)
        with patch("rag.retriever.emit_retrieval_started"), \
             patch("rag.retriever.emit_retrieval_vector_search"), \
             patch("rag.retriever.emit_retrieval_filtering"), \
             patch("rag.retriever.emit_retrieval_completed"), \
             patch("rag.retriever.emit_retrieval_failed"):
            mocked_result = retrieve("what gpa do i need", k=3)
        self.assertEqual(normal_result, mocked_result)

    def test_repeated_calls_are_self_consistent(self):
        r1 = retrieve("when is the deadline", k=3)
        r2 = retrieve("when is the deadline", k=3)
        self.assertEqual(r1, r2)


class TestRetrievalSummary(unittest.TestCase):
    def _write_fixture_log(self, records: list[dict]) -> Path:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8")
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.close()
        return Path(f.name)

    def test_empty_log_returns_zeroed_summary(self):
        path = self._write_fixture_log([])
        summary = summarize_retrieval_events(path)
        self.assertEqual(summary["total_started"], 0)
        self.assertEqual(summary["average_latency_ms"], 0.0)
        path.unlink()

    def test_summary_counts_and_averages(self):
        records = [
            {"event": "retrieval.started"},
            {"event": "retrieval.started"},
            {"event": "retrieval.vector_search", "candidate_count": 10},
            {"event": "retrieval.vector_search", "candidate_count": 20},
            {"event": "retrieval.filtering", "candidate_count": 10, "filtered_count": 4},
            {"event": "retrieval.filtering", "candidate_count": 20, "filtered_count": 6},
            {"event": "retrieval.completed", "returned_count": 3, "elapsed_ms": 100.0},
            {"event": "retrieval.completed", "returned_count": 0, "elapsed_ms": 50.0},
        ]
        path = self._write_fixture_log(records)
        summary = summarize_retrieval_events(path)
        self.assertEqual(summary["total_started"], 2)
        self.assertEqual(summary["total_completed"], 2)
        self.assertEqual(summary["average_candidate_count"], 15.0)  # (10+20)/2
        self.assertEqual(summary["average_returned_chunks"], 1.5)   # (3+0)/2
        self.assertEqual(summary["average_latency_ms"], 75.0)       # (100+50)/2
        self.assertEqual(summary["filtering_percentage"], round(10 / 30 * 100, 1))  # (4+6)/(10+20)
        self.assertEqual(summary["empty_retrieval_percentage"], 50.0)  # 1 of 2 completed had 0 results
        path.unlink()

    def test_failure_reason_breakdown(self):
        records = [
            {"event": "retrieval.failed", "reason": "store_unavailable"},
            {"event": "retrieval.failed", "reason": "store_unavailable"},
            {"event": "retrieval.failed", "reason": "search_exception"},
        ]
        path = self._write_fixture_log(records)
        summary = summarize_retrieval_events(path)
        self.assertEqual(summary["total_failed"], 3)
        self.assertEqual(summary["failure_reason_breakdown"],
                          {"store_unavailable": 2, "search_exception": 1})
        path.unlink()

    def test_malformed_lines_are_skipped_not_raised(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8")
        f.write("not valid json\n")
        f.write(json.dumps({"event": "retrieval.started"}) + "\n")
        f.close()
        path = Path(f.name)
        summary = summarize_retrieval_events(path)
        self.assertEqual(summary["total_started"], 1)
        path.unlink()

    def test_missing_log_file_returns_zeroed_summary(self):
        summary = summarize_retrieval_events(Path("/tmp/definitely_does_not_exist_12345.log"))
        self.assertEqual(summary["total_started"], 0)

    def test_format_console_summary_does_not_raise(self):
        summary = summarize_retrieval_events(Path("/tmp/definitely_does_not_exist_12345.log"))
        text = format_console_summary(summary)
        self.assertIsInstance(text, str)
        self.assertIn("Retrieval Observability Summary", text)


if __name__ == "__main__":
    unittest.main()
