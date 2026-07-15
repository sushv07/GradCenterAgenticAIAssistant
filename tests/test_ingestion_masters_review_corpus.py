"""
tests/test_ingestion_masters_review_corpus.py
Offline tests for the reviewed-corpus builder (Phase P4). Uses the synthetic
card index fixture + StaticFetcher — no live HTML, no production writes.

Run: pytest tests/test_ingestion_masters_review_corpus.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.fetching import StaticFetcher
from ingestion.masters.review_corpus import (
    _overview_looks_boilerplate, build_review_corpus,
)
from ingestion.masters.snapshots import SnapshotStore
from ingestion.masters.sources_policy import GRADUATE_STUDIES_MASTERS_INDEX_URL

FIXTURES = Path(__file__).parent / "fixtures" / "masters_html"
NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)

_PAGES = {
    GRADUATE_STUDIES_MASTERS_INDEX_URL: (FIXTURES / "index.html").read_bytes(),
    "https://example.edu/cecs/ms-data-science": (FIXTURES / "program_ms_data_science.html").read_bytes(),
    "https://example.edu/math/ms-applied-statistics": (FIXTURES / "program_ms_applied_statistics.html").read_bytes(),
}


def _build(selection, tmp):
    return build_review_corpus(
        fetcher=StaticFetcher(_PAGES, clock=lambda: NOW),
        snapshot_store=SnapshotStore(Path(tmp) / "sources"),
        out_dir=Path(tmp) / "programs",
        selection=selection, now=NOW,
    )


class TestReviewCorpus(unittest.TestCase):
    def test_builds_selected_programs(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _build(("Data Science", "Applied Statistics"), tmp)
            self.assertEqual(len(report.reviews), 2)
            self.assertEqual(report.ambiguous, [])
            self.assertEqual(report.metrics["programs_processed"], 2)

    def test_no_validation_errors_and_zero_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _build(("Data Science", "Applied Statistics"), tmp)
            self.assertEqual(report.metrics["validation_errors"], 0)
            self.assertEqual(report.metrics["fabricated_values"], 0)

    def test_missing_or_ambiguous_name_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _build(("Data Science", "Nonexistent Program"), tmp)
            self.assertEqual(len(report.reviews), 1)
            self.assertTrue(any("Nonexistent Program" in a for a in report.ambiguous))

    def test_metrics_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _build(("Data Science",), tmp).metrics
            for key in ("pct_source_backed", "pct_unknown", "pct_source_missing",
                        "snapshot_coverage_pct", "fabricated_values", "facts_total"):
                self.assertIn(key, m)

    def test_writes_only_to_given_out_dir_not_production(self):
        prod = Path(__file__).parent.parent / "data" / "masters" / "programs"
        with tempfile.TemporaryDirectory() as tmp:
            _build(("Data Science",), tmp)
            self.assertTrue((Path(tmp) / "programs" / "data-science.json").exists())
            if prod.exists():
                self.assertEqual(list(prod.glob("data-science.json")), [])


class TestBoilerplateOverviewDetection(unittest.TestCase):
    def test_carousel_text_flagged(self):
        self.assertTrue(_overview_looks_boilerplate(
            "This is a carousel. Use next and previous buttons to navigate."))

    def test_real_overview_not_flagged(self):
        self.assertFalse(_overview_looks_boilerplate(
            "The Master of Science in Data Science prepares students for analytics careers."))

    def test_none_not_flagged(self):
        self.assertFalse(_overview_looks_boilerplate(None))


if __name__ == "__main__":
    unittest.main()
