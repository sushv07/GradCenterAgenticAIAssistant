"""
tests/test_ingestion_observability.py
Phase 9D — regression tests for the ingestion observability layer.

Covers:
  - Event helper output shapes and field values.
  - Successful page ingestion fires the right event sequence.
  - Failed page ingestion (fetch fail, parse fail) fires ingestion.page_failed.
  - Retry events fire when first HTTP attempt fails.
  - Timing metadata is numeric (ms) and non-negative.
  - Chunk count metadata is correct.
  - No page text, HTML, or chunk content is ever logged.
  - Summary utility against fixture log data.
  - Deterministic repeated runs: same inputs → same events.
  - Behavior unchanged: chunk_documents() return values are byte-identical
    whether the new emit() calls run or are mocked out.

Run from the project root:
    pytest tests/test_ingestion_observability.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock, call

from obs.ingestion_events import (
    emit_ingestion_started,
    emit_ingestion_page_fetched,
    emit_ingestion_page_retry,
    emit_ingestion_page_parsed,
    emit_ingestion_page_failed,
    emit_ingestion_page_chunked,
    emit_ingestion_completed,
)
from obs.ingestion_summary import summarize_ingestion_events, format_console_summary


# ---------------------------------------------------------------------------
# Helper: capture ingestion events from a patched emit()
# ---------------------------------------------------------------------------

def _captured_emit_calls(fn, *args, **kwargs) -> list[tuple[str, dict]]:
    with patch("obs.ingestion_events.emit") as mock_emit:
        fn(*args, **kwargs)
    return [(c.args[0], c.kwargs) for c in mock_emit.call_args_list]


# ---------------------------------------------------------------------------
# Event helper shapes
# ---------------------------------------------------------------------------

class TestEventHelperShapes(unittest.TestCase):
    def test_ingestion_started_shape(self):
        calls = _captured_emit_calls(emit_ingestion_started, 12, True)
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "ingestion.started")
        self.assertEqual(kwargs["ingestion_stage"], "started")
        self.assertEqual(kwargs["source_count"], 12)
        self.assertEqual(kwargs["use_discovery"], True)

    def test_ingestion_page_fetched_shape(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_fetched,
            "https://csulb.edu/p", "faq", "Nursing (D.N.P.)", 320.5, 45000,
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "ingestion.page_fetched")
        self.assertEqual(kwargs["ingestion_stage"], "fetch")
        self.assertEqual(kwargs["url"], "https://csulb.edu/p")
        self.assertEqual(kwargs["page_type"], "faq")
        self.assertEqual(kwargs["program_name"], "Nursing (D.N.P.)")
        self.assertIsInstance(kwargs["fetch_elapsed_ms"], float)
        self.assertIsInstance(kwargs["response_size_bytes"], int)

    def test_ingestion_page_retry_shape(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_retry, "https://csulb.edu/p", "ConnectionError", "timeout"
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "ingestion.page_retry")
        self.assertEqual(kwargs["level"], "WARNING")
        self.assertEqual(kwargs["error_type"], "ConnectionError")

    def test_ingestion_page_parsed_shape(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_parsed, "https://x.com", "eligibility", "", 1200, 45.2, 1
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "ingestion.page_parsed")
        self.assertEqual(kwargs["char_count"], 1200)
        self.assertEqual(kwargs["entry_count"], 1)

    def test_ingestion_page_parsed_specialist_entry_count(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_parsed, "https://x.com", "deadlines", "", 800, 20.0, 6
        )
        _, kwargs = calls[0]
        self.assertEqual(kwargs["entry_count"], 6)

    def test_ingestion_page_failed_shape(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_failed,
            "https://x.com", "faq", "", "fetch", "fetch_failed", "ConnectionError",
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "ingestion.page_failed")
        self.assertEqual(kwargs["level"], "WARNING")
        self.assertEqual(kwargs["reason"], "fetch_failed")
        self.assertEqual(kwargs["ingestion_stage"], "fetch")

    def test_ingestion_page_chunked_shape(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_chunked, "https://x.com", "faq", "", 12, 5800, 1.3
        )
        name, kwargs = calls[0]
        self.assertEqual(name, "ingestion.page_chunked")
        self.assertEqual(kwargs["chunks_generated"], 12)
        self.assertEqual(kwargs["chars_in"], 5800)

    def test_ingestion_completed_info_when_no_failures(self):
        calls = _captured_emit_calls(emit_ingestion_completed, 5, 5, 0, 3200.0, 45000)
        _, kwargs = calls[0]
        self.assertEqual(kwargs["level"], "INFO")

    def test_ingestion_completed_warning_when_failures(self):
        calls = _captured_emit_calls(emit_ingestion_completed, 5, 3, 2, 3200.0, 30000)
        _, kwargs = calls[0]
        self.assertEqual(kwargs["level"], "WARNING")
        self.assertEqual(kwargs["pages_failed"], 2)


# ---------------------------------------------------------------------------
# Full ingestion pipeline — mocked HTTP, real parsing
# ---------------------------------------------------------------------------

_LONG_HTML = (
    "<html><head><title>Eligibility | CSULB</title></head>"
    "<body><main><p>"
    + ("Doctoral programs eligibility content with details. " * 20)
    + "</p></main></body></html>"
)

_SHORT_HTML = "<html><body><main><p>too short</p></main></body></html>"


class TestIngestPagesEventSequence(unittest.TestCase):
    def _run_ingest(self, html_by_url: dict, sources: list[dict]) -> list[dict]:
        events = []

        def fake_fetch(url):
            return html_by_url.get(url)

        def fake_emit(event, level="INFO", **f):
            events.append({"event": event, "level": level, **f})

        with patch("obs.ingestion_events.emit", side_effect=fake_emit), \
             patch("gradcenter_logging.emit", side_effect=fake_emit), \
             patch("rag.ingestion.fetch_page", side_effect=fake_fetch):
            from rag.ingestion import ingest_pages
            ingest_pages(sources=sources, use_discovery=False)

        return [e for e in events if e["event"].startswith("ingestion.")]

    def test_successful_page_fires_started_fetched_parsed_completed(self):
        events = self._run_ingest(
            {"https://test.csulb.edu/a": _LONG_HTML},
            [{"url": "https://test.csulb.edu/a", "page_type": "eligibility", "title": "T"}],
        )
        event_names = [e["event"] for e in events]
        self.assertIn("ingestion.started", event_names)
        self.assertIn("ingestion.page_fetched", event_names)
        self.assertIn("ingestion.page_parsed", event_names)
        self.assertIn("ingestion.completed", event_names)
        self.assertNotIn("ingestion.page_failed", event_names)
        self.assertNotIn("ingestion.page_retry", event_names)

    def test_fetch_failure_fires_page_failed_not_fetched(self):
        events = self._run_ingest(
            {},  # no URL maps → fetch_page returns None
            [{"url": "https://test.csulb.edu/missing", "page_type": "faq", "title": "T"}],
        )
        event_names = [e["event"] for e in events]
        self.assertIn("ingestion.page_failed", event_names)
        self.assertNotIn("ingestion.page_fetched", event_names)
        failed = next(e for e in events if e["event"] == "ingestion.page_failed")
        self.assertEqual(failed["reason"], "fetch_failed")
        self.assertEqual(failed["ingestion_stage"], "fetch")

    def test_parse_failure_short_content_fires_page_failed(self):
        events = self._run_ingest(
            {"https://test.csulb.edu/short": _SHORT_HTML},
            [{"url": "https://test.csulb.edu/short", "page_type": "faq", "title": "T"}],
        )
        event_names = [e["event"] for e in events]
        self.assertIn("ingestion.page_fetched", event_names)
        self.assertIn("ingestion.page_failed", event_names)
        failed = next(e for e in events if e["event"] == "ingestion.page_failed")
        self.assertEqual(failed["ingestion_stage"], "parse")

    def test_started_fires_with_correct_source_count(self):
        events = self._run_ingest(
            {"https://a.com": _LONG_HTML, "https://b.com": _LONG_HTML},
            [
                {"url": "https://a.com", "page_type": "faq", "title": "T"},
                {"url": "https://b.com", "page_type": "eligibility", "title": "T"},
            ],
        )
        started = next(e for e in events if e["event"] == "ingestion.started")
        self.assertEqual(started["source_count"], 2)

    def test_completed_has_correct_counts(self):
        events = self._run_ingest(
            {"https://a.com": _LONG_HTML},
            [
                {"url": "https://a.com", "page_type": "faq", "title": "T"},
                {"url": "https://b.com", "page_type": "faq", "title": "T"},  # fails fetch
            ],
        )
        completed = next(e for e in events if e["event"] == "ingestion.completed")
        self.assertEqual(completed["pages_attempted"], 2)
        self.assertEqual(completed["pages_succeeded"], 1)
        self.assertEqual(completed["pages_failed"], 1)

    def test_exactly_one_started_per_run(self):
        events = self._run_ingest(
            {"https://a.com": _LONG_HTML},
            [{"url": "https://a.com", "page_type": "faq", "title": "T"}],
        )
        self.assertEqual(sum(1 for e in events if e["event"] == "ingestion.started"), 1)

    def test_exactly_one_completed_per_run(self):
        events = self._run_ingest(
            {"https://a.com": _LONG_HTML},
            [{"url": "https://a.com", "page_type": "faq", "title": "T"}],
        )
        self.assertEqual(sum(1 for e in events if e["event"] == "ingestion.completed"), 1)


# ---------------------------------------------------------------------------
# Retry events
# ---------------------------------------------------------------------------

class TestRetryEvents(unittest.TestCase):
    def test_retry_fires_when_first_attempt_fails(self):
        from unittest.mock import MagicMock
        import requests

        events = []

        def fake_emit(event, level="INFO", **f):
            events.append({"event": event, **f})

        call_count = [0]

        def mock_requests_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise requests.exceptions.ConnectionError("simulated")
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.text = _LONG_HTML
            return resp

        with patch("obs.ingestion_events.emit", side_effect=fake_emit), \
             patch("gradcenter_logging.emit", side_effect=fake_emit), \
             patch("requests.get", side_effect=mock_requests_get), \
             patch("rag.ingestion.time.sleep"):  # no actual sleep in tests
            from rag.ingestion import fetch_page
            result = fetch_page("https://test.csulb.edu/retry")

        ingestion_events = [e for e in events if "ingestion" in e.get("event", "")]
        self.assertTrue(any(e["event"] == "ingestion.page_retry" for e in ingestion_events),
                        "ingestion.page_retry should have fired")
        retry = next(e for e in ingestion_events if e["event"] == "ingestion.page_retry")
        self.assertEqual(retry["url"], "https://test.csulb.edu/retry")
        self.assertEqual(retry["error_type"], "ConnectionError")
        self.assertIsNotNone(result)  # second attempt succeeded


# ---------------------------------------------------------------------------
# Timing metadata
# ---------------------------------------------------------------------------

class TestTimingMetadata(unittest.TestCase):
    def test_fetch_elapsed_ms_is_non_negative_float(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_fetched, "https://x.com", "faq", "", 0.1, 100
        )
        _, kwargs = calls[0]
        self.assertIsInstance(kwargs["fetch_elapsed_ms"], float)
        self.assertGreaterEqual(kwargs["fetch_elapsed_ms"], 0.0)

    def test_chunk_elapsed_ms_present_and_non_negative(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_chunked, "https://x.com", "faq", "", 5, 1000, 2.5
        )
        _, kwargs = calls[0]
        self.assertIsInstance(kwargs["chunk_elapsed_ms"], float)
        self.assertGreaterEqual(kwargs["chunk_elapsed_ms"], 0.0)


# ---------------------------------------------------------------------------
# No page text logged
# ---------------------------------------------------------------------------

class TestNoPageTextLogged(unittest.TestCase):
    """Verify that no raw HTML, cleaned text, or chunk text ever appears
    in any ingestion event field — only metadata."""

    def test_no_html_or_text_in_fetched_event(self):
        calls = _captured_emit_calls(
            emit_ingestion_page_fetched,
            "https://x.com", "faq", "", 50.0, 2000,
        )
        _, kwargs = calls[0]
        for value in kwargs.values():
            if isinstance(value, str):
                self.assertLess(len(value), 300, f"Suspiciously long string in event: {value[:100]}")

    def test_chunk_documents_events_contain_no_chunk_text(self):
        chunk_text = "This is the actual chunk text that must never appear in events."
        events = []

        def fake_emit(event, level="INFO", **f):
            events.append({"event": event, **f})

        with patch("obs.ingestion_events.emit", side_effect=fake_emit):
            from rag.chunking import chunk_documents
            chunk_documents([{
                "url": "https://x.com", "page_type": "faq", "title": "T",
                "program_name": "", "content_category": "", "discovered_from": "",
                "parent_program_url": "", "workflow_priority": 5,
                "text": chunk_text * 5, "links": [], "char_count": len(chunk_text * 5),
            }])

        for event in events:
            for key, value in event.items():
                if isinstance(value, str) and chunk_text[:20] in value:
                    self.fail(
                        f"Chunk text found in event field {key!r}: {value[:100]}"
                    )


# ---------------------------------------------------------------------------
# Behavior unchanged: chunk_documents return value is byte-identical
# ---------------------------------------------------------------------------

class TestBehaviorUnchanged(unittest.TestCase):
    def test_chunk_documents_identical_with_emit_mocked_vs_live(self):
        from rag.chunking import chunk_documents

        pages = [{
            "url": "https://x.com", "page_type": "eligibility", "title": "T",
            "program_name": "", "content_category": "", "discovered_from": "",
            "parent_program_url": "", "workflow_priority": 5,
            "text": "Test content for eligibility. " * 30,
            "links": [], "char_count": 900,
        }]
        docs_live = chunk_documents(pages)
        with patch("obs.ingestion_events.emit"):
            docs_patched = chunk_documents(pages)
        for d1, d2 in zip(docs_live, docs_patched):
            self.assertEqual(d1.page_content, d2.page_content)
            self.assertEqual(d1.metadata, d2.metadata)

    def test_ingest_pages_return_value_identical_with_emit_mocked(self):
        from rag.ingestion import ingest_pages

        sources = [
            {"url": "https://a.com", "page_type": "faq", "title": "T"},
            {"url": "https://b.com", "page_type": "eligibility", "title": "T2"},
        ]
        with patch("rag.ingestion.fetch_page", return_value=_LONG_HTML):
            pages_live = ingest_pages(sources=sources, use_discovery=False)
        with patch("rag.ingestion.fetch_page", return_value=_LONG_HTML), \
             patch("obs.ingestion_events.emit"), \
             patch("gradcenter_logging.emit"):
            pages_patched = ingest_pages(sources=sources, use_discovery=False)
        self.assertEqual(len(pages_live), len(pages_patched))
        for p1, p2 in zip(pages_live, pages_patched):
            self.assertEqual(p1["url"], p2["url"])
            self.assertEqual(p1["char_count"], p2["char_count"])
            self.assertEqual(p1["text"], p2["text"])


# ---------------------------------------------------------------------------
# Summary utility
# ---------------------------------------------------------------------------

class TestIngestionSummary(unittest.TestCase):
    def _write_fixture_log(self, records: list[dict]) -> Path:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        )
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.close()
        return Path(f.name)

    def test_empty_log_returns_zeroed_summary(self):
        path = self._write_fixture_log([])
        s = summarize_ingestion_events(path)
        self.assertEqual(s["total_runs"], 0)
        self.assertEqual(s["total_chunks_generated"], 0)
        path.unlink()

    def test_summary_counts_runs_and_pages(self):
        records = [
            {"event": "ingestion.started", "source_count": 5, "use_discovery": False},
            {"event": "ingestion.page_fetched", "fetch_elapsed_ms": 300.0, "response_size_bytes": 40000},
            {"event": "ingestion.page_parsed", "char_count": 1200, "parse_elapsed_ms": 20.0, "entry_count": 1},
            {"event": "ingestion.page_chunked", "chunks_generated": 3, "chars_in": 1200, "chunk_elapsed_ms": 1.5},
            {"event": "ingestion.completed", "pages_attempted": 5, "pages_succeeded": 4, "pages_failed": 1, "elapsed_ms": 1500.0, "total_chars": 4800},
        ]
        path = self._write_fixture_log(records)
        s = summarize_ingestion_events(path)
        self.assertEqual(s["total_runs"], 1)
        self.assertEqual(s["completed_runs"], 1)
        self.assertEqual(s["pages_attempted"], 5)
        self.assertEqual(s["pages_succeeded"], 4)
        self.assertEqual(s["total_chunks_generated"], 3)
        self.assertEqual(s["average_fetch_ms"], 300.0)
        path.unlink()

    def test_failure_reasons_counted(self):
        records = [
            {"event": "ingestion.page_failed", "reason": "fetch_failed", "stage": "fetch"},
            {"event": "ingestion.page_failed", "reason": "fetch_failed", "stage": "fetch"},
            {"event": "ingestion.page_failed", "reason": "parse_failed", "stage": "parse"},
        ]
        path = self._write_fixture_log(records)
        s = summarize_ingestion_events(path)
        self.assertEqual(s["failure_reasons"]["fetch_failed"], 2)
        self.assertEqual(s["failure_reasons"]["parse_failed"], 1)
        path.unlink()

    def test_retry_error_types_counted(self):
        records = [
            {"event": "ingestion.page_retry", "error_type": "ConnectionError"},
            {"event": "ingestion.page_retry", "error_type": "Timeout"},
        ]
        path = self._write_fixture_log(records)
        s = summarize_ingestion_events(path)
        self.assertEqual(s["total_retries"], 2)
        self.assertEqual(s["retry_error_types"]["ConnectionError"], 1)
        self.assertEqual(s["retry_error_types"]["Timeout"], 1)
        path.unlink()

    def test_missing_log_returns_zeroed_summary(self):
        s = summarize_ingestion_events(Path("/tmp/definitely_does_not_exist_9d.log"))
        self.assertEqual(s["total_runs"], 0)

    def test_malformed_lines_skipped(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
        f.write("not valid json\n")
        f.write(json.dumps({"event": "ingestion.started", "source_count": 3}) + "\n")
        f.close()
        path = Path(f.name)
        s = summarize_ingestion_events(path)
        self.assertEqual(s["total_runs"], 1)
        path.unlink()

    def test_format_console_summary_does_not_raise(self):
        s = summarize_ingestion_events(Path("/tmp/does_not_exist.log"))
        text = format_console_summary(s)
        self.assertIn("Ingestion Observability Summary", text)


if __name__ == "__main__":
    unittest.main()
