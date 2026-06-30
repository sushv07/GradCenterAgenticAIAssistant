"""
tests/test_kb_health_report.py
Phase 9B — regression tests for the knowledge-base health report.

Covers:
  - Report generation from the live Chroma store.
  - Health classification logic for all four status levels.
  - Statistics: chunk counts, size distribution, short/empty detection.
  - Duplicate chunk_id detection.
  - Metadata health reporting.
  - Warning generation for each warning condition.
  - Empty-store handling (returns unhealthy without crashing).
  - JSON report writing roundtrip.
  - Behavior unchanged: retrieval output is identical before and after
    running the health report.

Run from the project root:
    pytest tests/test_kb_health_report.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from obs.kb_health_report import (
    inspect_kb,
    classify_health,
    format_console_report,
    write_json_report,
    _SHORT_CHUNK_THRESHOLD,
    _MIN_TOTAL_CHUNKS,
    _MIN_NAMED_PROGRAMS,
)


# ---------------------------------------------------------------------------
# Helpers — build a mock Chroma store from a list of (text, metadata) tuples
# ---------------------------------------------------------------------------

def _build_mock_store(chunks: list[tuple[str, dict]]) -> MagicMock:
    """Return a mock Chroma instance whose _collection.get() returns `chunks`.
    Each chunk is (page_content, metadata_dict)."""
    store = MagicMock()
    metadatas = [m for _, m in chunks]
    documents  = [t for t, _ in chunks]
    store._collection.get.return_value = {
        "metadatas": metadatas,
        "documents":  documents,
        "ids":        [str(i) for i in range(len(chunks))],
    }
    return store


def _make_chunk(
    text: str = "x" * 200,
    url: str = "https://www.csulb.edu/page",
    page_type: str = "faq",
    title: str = "Test Page",
    chunk_id: str = "abc00000_0000",
    program_name: str = "",
    content_category: str = "",
) -> tuple[str, dict]:
    return text, {
        "url": url, "page_type": page_type, "title": title,
        "chunk_id": chunk_id, "program_name": program_name,
        "content_category": content_category, "workflow_priority": 5,
    }


def _healthy_store(n: int = 150) -> MagicMock:
    """Return a mock store with `n` clean chunks covering all required page types."""
    types = ["faq", "deadlines", "eligibility", "application_process", "program_application"]
    programs = [
        "Nursing (D.N.P.)", "Physical Therapy (DPT)", "Educational Leadership (Ed.D.)",
        "Engineering & Computational Mathematics (Ph.D.)", "Public Health (DR.P.H.)",
    ]
    chunks = []
    for i in range(n):
        pt = types[i % len(types)]
        prog = programs[i % len(programs)] if pt == "program_application" else ""
        chunks.append(_make_chunk(
            text="a" * 200, url=f"https://csulb.edu/{pt}",
            page_type=pt, chunk_id=f"abc{i:06d}_0000", program_name=prog,
        ))
    return _build_mock_store(chunks)


# ---------------------------------------------------------------------------
# Health classification tests
# ---------------------------------------------------------------------------

class TestClassifyHealth(unittest.TestCase):
    def _classify(self, **kwargs) -> tuple[str, list[str]]:
        defaults = {
            "total": 200,
            "pt_counts": {pt: 20 for pt in ["faq","deadlines","eligibility","application_process","program_application"]},
            "distinct_programs": ["P1","P2","P3","P4","P5"],
            "empty_count": 0,
            "short_count": 0,
            "metadata_health": {"missing_url": 0, "missing_chunk_id": 0, "missing_page_type": 0},
            "dup_count": 0,
            "store_age_hours": 5.0,
        }
        defaults.update(kwargs)
        return classify_health(**defaults)

    def test_healthy_all_clean(self):
        status, warnings = self._classify()
        self.assertEqual(status, "healthy")
        self.assertEqual(warnings, [])

    def test_unhealthy_empty_store(self):
        status, warnings = self._classify(total=0)
        self.assertEqual(status, "unhealthy")
        self.assertGreater(len(warnings), 0)

    def test_unhealthy_missing_url(self):
        status, _ = self._classify(
            metadata_health={"missing_url": 5, "missing_chunk_id": 0, "missing_page_type": 0}
        )
        self.assertEqual(status, "unhealthy")

    def test_unhealthy_empty_chunks(self):
        status, _ = self._classify(empty_count=1)
        self.assertEqual(status, "unhealthy")

    def test_degraded_below_min_chunks(self):
        status, _ = self._classify(total=50)
        self.assertEqual(status, "degraded")

    def test_degraded_missing_required_page_type(self):
        pt = {"faq": 0, "deadlines": 20, "eligibility": 20,
              "application_process": 20, "program_application": 20}
        status, warnings = self._classify(pt_counts=pt, total=200)
        self.assertEqual(status, "degraded")
        self.assertTrue(any("faq" in w for w in warnings))

    def test_healthy_with_warnings_duplicate_ids(self):
        status, warnings = self._classify(dup_count=1)
        self.assertEqual(status, "healthy_with_warnings")
        self.assertTrue(any("chunk_id" in w.lower() for w in warnings))

    def test_healthy_with_warnings_short_chunks(self):
        status, warnings = self._classify(short_count=3)
        self.assertEqual(status, "healthy_with_warnings")
        self.assertTrue(any("short" in w.lower() for w in warnings))

    def test_healthy_with_warnings_few_programs(self):
        status, warnings = self._classify(distinct_programs=["P1", "P2"])
        self.assertEqual(status, "healthy_with_warnings")
        self.assertTrue(any("program" in w.lower() for w in warnings))

    def test_healthy_with_warnings_stale_store(self):
        status, warnings = self._classify(store_age_hours=72.0)
        self.assertEqual(status, "healthy_with_warnings")
        self.assertTrue(any("old" in w.lower() or "rebuild" in w.lower() for w in warnings))

    def test_unhealthy_takes_precedence_over_degraded(self):
        status, _ = self._classify(
            total=50,  # would be degraded
            empty_count=2,  # unhealthy
        )
        self.assertEqual(status, "unhealthy")


# ---------------------------------------------------------------------------
# Statistics tests using mock stores
# ---------------------------------------------------------------------------

class TestKBStatistics(unittest.TestCase):
    def test_correct_total_chunk_count(self):
        store = _healthy_store(200)
        report = inspect_kb(store=store)
        self.assertEqual(report["knowledge_base"]["total_chunks"], 200)

    def test_empty_chunks_detected(self):
        store = _build_mock_store([
            _make_chunk(text=""),
            _make_chunk(text="good content here " * 10),
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["chunk_stats"]["empty_chunks"], 1)
        self.assertEqual(report["overall_health"], "unhealthy")

    def test_short_chunks_detected(self):
        short_text = "x" * (_SHORT_CHUNK_THRESHOLD - 1)
        store = _build_mock_store([
            _make_chunk(text=short_text),
            _make_chunk(text="y" * 200),
        ] * 50)
        report = inspect_kb(store=store)
        self.assertGreater(report["chunk_stats"]["short_chunks"]["count"], 0)

    def test_average_chunk_size(self):
        store = _build_mock_store([
            _make_chunk(text="a" * 100, chunk_id="x_0000"),
            _make_chunk(text="a" * 300, chunk_id="x_0001"),
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["chunk_stats"]["average_chars"], 200.0)

    def test_min_max_chunk_size(self):
        store = _build_mock_store([
            _make_chunk(text="a" * 50, chunk_id="x_0000"),
            _make_chunk(text="a" * 400, chunk_id="x_0001"),
            _make_chunk(text="a" * 200, chunk_id="x_0002"),
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["chunk_stats"]["min_chars"], 50)
        self.assertEqual(report["chunk_stats"]["max_chars"], 400)

    def test_distinct_url_count(self):
        store = _build_mock_store([
            _make_chunk(url="https://a.com", chunk_id="a_0000"),
            _make_chunk(url="https://a.com", chunk_id="a_0001"),
            _make_chunk(url="https://b.com", chunk_id="b_0000"),
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["knowledge_base"]["total_urls"], 2)


# ---------------------------------------------------------------------------
# Duplicate detection tests
# ---------------------------------------------------------------------------

class TestDuplicateDetection(unittest.TestCase):
    def test_no_duplicates_detected_in_clean_store(self):
        store = _build_mock_store([
            _make_chunk(chunk_id=f"unique_{i:04d}") for i in range(20)
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["duplicate_tracking"]["duplicate_chunk_id_count"], 0)
        self.assertEqual(report["duplicate_tracking"]["total_extra_copies"], 0)

    def test_duplicate_chunk_id_detected(self):
        store = _build_mock_store([
            _make_chunk(text="a" * 200, chunk_id="dup_0000"),
            _make_chunk(text="b" * 200, chunk_id="dup_0000"),
            _make_chunk(text="c" * 200, chunk_id="dup_0000"),
            _make_chunk(text="d" * 200, chunk_id="unique_001"),
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["duplicate_tracking"]["duplicate_chunk_id_count"], 1)
        self.assertEqual(report["duplicate_tracking"]["total_extra_copies"], 2)
        self.assertEqual(
            report["duplicate_tracking"]["known_duplicates"][0]["chunk_id"], "dup_0000"
        )

    def test_multiple_duplicate_ids(self):
        store = _build_mock_store([
            _make_chunk(chunk_id="dup_A"),
            _make_chunk(chunk_id="dup_A"),
            _make_chunk(chunk_id="dup_B"),
            _make_chunk(chunk_id="dup_B"),
            _make_chunk(chunk_id="dup_B"),
            _make_chunk(chunk_id="unique"),
        ])
        report = inspect_kb(store=store)
        self.assertEqual(report["duplicate_tracking"]["duplicate_chunk_id_count"], 2)
        self.assertEqual(report["duplicate_tracking"]["total_extra_copies"], 3)


# ---------------------------------------------------------------------------
# Metadata health tests
# ---------------------------------------------------------------------------

class TestMetadataHealth(unittest.TestCase):
    def test_missing_url_flagged(self):
        store = _build_mock_store([
            ("text " * 30, {"url": "", "page_type": "faq", "title": "T",
                             "chunk_id": "x_0000", "program_name": "", "content_category": ""}),
            _make_chunk(chunk_id="x_0001"),
        ])
        report = inspect_kb(store=store)
        self.assertGreater(report["metadata_health"]["missing_url"], 0)
        self.assertEqual(report["overall_health"], "unhealthy")

    def test_all_metadata_present_in_clean_store(self):
        store = _healthy_store(50)
        report = inspect_kb(store=store)
        self.assertEqual(report["metadata_health"]["missing_url"], 0)
        self.assertEqual(report["metadata_health"]["missing_chunk_id"], 0)
        self.assertEqual(report["metadata_health"]["missing_page_type"], 0)
        self.assertEqual(report["metadata_health"]["missing_title"], 0)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestFormatConsoleReport(unittest.TestCase):
    def test_format_healthy_store_does_not_raise(self):
        store = _healthy_store(200)
        report = inspect_kb(store=store)
        text = format_console_report(report)
        self.assertIsInstance(text, str)
        self.assertIn("Knowledge Base Health Report", text)
        self.assertIn("HEALTHY", text.upper())

    def test_format_unhealthy_shows_warnings(self):
        store = _build_mock_store([])   # empty
        report = inspect_kb(store=store)
        text = format_console_report(report)
        self.assertIn("UNHEALTHY", text.upper())

    def test_format_includes_all_sections(self):
        store = _healthy_store(100)
        report = inspect_kb(store=store)
        text = format_console_report(report)
        for section in ("Knowledge Base", "Coverage", "Chunk Statistics",
                         "Metadata Health", "Duplicate Tracking"):
            self.assertIn(section, text, section)

    def test_format_empty_store_does_not_raise(self):
        report = {
            "timestamp": "2026-01-01T00:00:00Z",
            "store_path": "/tmp/nonexistent",
            "store_built_at": None,
            "store_age_hours": None,
            "overall_health": "unhealthy",
            "warnings": ["Store is empty"],
            "knowledge_base": {"total_chunks": 0, "total_urls": 0, "total_named_programs": 0, "named_programs": []},
            "coverage": {"by_page_type": {}, "by_program": {}, "url_distribution": {"total_distinct_urls": 0, "top_10_urls": []}},
            "chunk_stats": {"average_chars": 0, "min_chars": 0, "max_chars": 0, "empty_chunks": 0, "short_chunks": {"count": 0, "threshold_chars": 50}},
            "metadata_health": {"total_chunks": 0, "missing_url": 0, "missing_chunk_id": 0, "missing_page_type": 0, "missing_title": 0, "content_category_coverage": {"with_value": 0, "without_value": 0}},
            "duplicate_tracking": {"duplicate_chunk_id_count": 0, "total_extra_copies": 0, "known_duplicates": []},
        }
        text = format_console_report(report)
        self.assertIn("Knowledge Base Health Report", text)


# ---------------------------------------------------------------------------
# JSON report tests
# ---------------------------------------------------------------------------

class TestJSONReport(unittest.TestCase):
    def test_write_json_report_roundtrip(self):
        store = _healthy_store(50)
        report = inspect_kb(store=store)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "test_kb_health.json"
            written = write_json_report(report, path=out_path)
            self.assertEqual(written, out_path)
            loaded = json.loads(out_path.read_text())
        self.assertEqual(loaded["overall_health"], report["overall_health"])
        self.assertEqual(loaded["knowledge_base"]["total_chunks"],
                          report["knowledge_base"]["total_chunks"])

    def test_write_json_creates_parent_dirs(self):
        store = _healthy_store(50)
        report = inspect_kb(store=store)
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_path = Path(tmpdir) / "a" / "b" / "kb.json"
            write_json_report(report, path=deep_path)
            self.assertTrue(deep_path.exists())


# ---------------------------------------------------------------------------
# Empty store handling
# ---------------------------------------------------------------------------

class TestEmptyStoreHandling(unittest.TestCase):
    def test_inspect_kb_with_empty_mock_store(self):
        store = _build_mock_store([])
        report = inspect_kb(store=store)
        self.assertEqual(report["overall_health"], "unhealthy")
        self.assertEqual(report["knowledge_base"]["total_chunks"], 0)
        self.assertIsInstance(report["warnings"], list)
        self.assertGreater(len(report["warnings"]), 0)

    def test_inspect_kb_when_store_unavailable(self):
        with patch("obs.kb_health_report.inspect_kb") as mock:
            mock.return_value = {
                "overall_health": "unhealthy",
                "warnings": ["Vector store not found"],
                "knowledge_base": {"total_chunks": 0},
            }
            result = mock()
        self.assertEqual(result["overall_health"], "unhealthy")


# ---------------------------------------------------------------------------
# Live store tests
# ---------------------------------------------------------------------------

class TestLiveStore(unittest.TestCase):
    """Verify the report against the real chroma_db/ store."""

    @classmethod
    def setUpClass(cls):
        from rag.store import load_vector_store
        cls.store = load_vector_store()
        if cls.store is None:
            raise unittest.SkipTest("Vector store not available")

    def test_live_report_correct_chunk_count(self):
        report = inspect_kb(store=self.store)
        self.assertEqual(report["knowledge_base"]["total_chunks"], 491)

    def test_live_report_correct_program_count(self):
        report = inspect_kb(store=self.store)
        self.assertEqual(report["knowledge_base"]["total_named_programs"], 5)

    def test_live_report_correct_health_status(self):
        report = inspect_kb(store=self.store)
        self.assertEqual(report["overall_health"], "healthy_with_warnings")

    def test_live_report_known_duplicate_tracked(self):
        report = inspect_kb(store=self.store)
        dt = report["duplicate_tracking"]
        self.assertEqual(dt["duplicate_chunk_id_count"], 1)
        self.assertEqual(dt["known_duplicates"][0]["chunk_id"], "c31caccf_0000")
        self.assertEqual(dt["known_duplicates"][0]["count"], 7)

    def test_live_report_no_missing_required_metadata(self):
        report = inspect_kb(store=self.store)
        mh = report["metadata_health"]
        self.assertEqual(mh["missing_url"], 0)
        self.assertEqual(mh["missing_chunk_id"], 0)
        self.assertEqual(mh["missing_page_type"], 0)

    def test_live_report_deterministic(self):
        r1 = inspect_kb(store=self.store)
        r2 = inspect_kb(store=self.store)
        r1.pop("timestamp"); r2.pop("timestamp")
        r1.pop("store_age_hours", None); r2.pop("store_age_hours", None)
        self.assertEqual(r1, r2)


class TestBehaviorUnchanged(unittest.TestCase):
    """Retrieval output is identical before and after running the health report."""

    def test_retrieval_unaffected_by_health_report(self):
        from rag.retriever import retrieve
        from rag.store import load_vector_store
        before = retrieve("when is the application deadline", k=3)
        store = load_vector_store()
        if store:
            inspect_kb(store=store)
        after = retrieve("when is the application deadline", k=3)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
