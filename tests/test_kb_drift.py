"""
tests/test_kb_drift.py
Phase 9C — regression tests for the Knowledge Base Drift Detection framework.

Covers:
  - Identical snapshots produce "no_drift".
  - Chunk additions (minor) and removals (minor/moderate/major).
  - URL additions and removals (minor).
  - Program additions (minor) and removals (major).
  - Page-type drops to zero (major) and significant drops (moderate).
  - Duplicate chunk_id count increases (moderate) and decreases (minor).
  - Metadata regressions (major) and improvements (minor).
  - Missing baseline → "no_baseline" overall status.
  - Malformed baseline gracefully returns None from load_baseline().
  - Classification logic: priority order, severity escalation.
  - Report generation (console + JSON roundtrip).
  - Deterministic behavior: repeated compare() calls on same inputs return same result.
  - No production behavior changes: retrieval output unchanged after drift detection.

Run from the project root:
    pytest tests/test_kb_drift.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest

from obs.kb_drift import (
    extract_baseline,
    save_baseline,
    load_baseline,
    compare,
    detect_drift,
    format_console_drift,
    write_drift_report,
    _severity_order,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _baseline(
    total_chunks=491, total_urls=28, total_named_programs=5,
    named_programs=None,
    chunks_by_page_type=None, chunks_by_program=None,
    empty_chunks=0, short_chunks=2,
    missing_url=0, missing_chunk_id=0, missing_page_type=0, missing_title=0,
    duplicate_chunk_id_count=1, total_extra_copies=6,
) -> dict:
    named_programs = named_programs or [
        "Nursing (D.N.P.)", "Physical Therapy (DPT)",
        "Educational Leadership (Ed.D.)",
        "Engineering & Computational Mathematics (Ph.D.)",
        "Public Health (DR.P.H.)",
    ]
    chunks_by_page_type = chunks_by_page_type or {
        "faq": 98, "deadlines": 14, "eligibility": 11,
        "application_process": 19, "program_application": 349,
    }
    chunks_by_program = chunks_by_program or {
        "Nursing (D.N.P.)": 44,
        "Physical Therapy (DPT)": 94,
        "Educational Leadership (Ed.D.)": 108,
        "Engineering & Computational Mathematics (Ph.D.)": 75,
        "Public Health (DR.P.H.)": 28,
    }
    return {
        "schema_version": "1.0",
        "captured_at": "2026-01-01T00:00:00Z",
        "total_chunks": total_chunks,
        "total_urls": total_urls,
        "total_named_programs": total_named_programs,
        "named_programs": sorted(named_programs),
        "chunks_by_page_type": chunks_by_page_type,
        "chunks_by_program": chunks_by_program,
        "empty_chunks": empty_chunks,
        "short_chunks": short_chunks,
        "missing_url": missing_url,
        "missing_chunk_id": missing_chunk_id,
        "missing_page_type": missing_page_type,
        "missing_title": missing_title,
        "duplicate_chunk_id_count": duplicate_chunk_id_count,
        "total_extra_copies": total_extra_copies,
    }


# ---------------------------------------------------------------------------
# Identical snapshots → no_drift
# ---------------------------------------------------------------------------

class TestNoDrift(unittest.TestCase):
    def test_identical_snapshots_produce_no_drift(self):
        b = _baseline()
        current = dict(b)
        status, changes = compare(current, b)
        self.assertEqual(status, "no_drift")
        self.assertEqual(changes, [])

    def test_no_drift_is_deterministic(self):
        b = _baseline()
        r1 = compare(dict(b), b)
        r2 = compare(dict(b), b)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Chunk changes
# ---------------------------------------------------------------------------

class TestChunkChanges(unittest.TestCase):
    def test_tiny_chunk_addition_is_minor(self):
        b = _baseline(total_chunks=491)
        cur = _baseline(total_chunks=496)  # +5, < 25
        status, changes = compare(cur, b)
        self.assertEqual(status, "minor_drift")
        chunk_change = next(c for c in changes if c["field"] == "total_chunks")
        self.assertEqual(chunk_change["severity"], "minor")
        self.assertEqual(chunk_change["delta"], 5)

    def test_moderate_chunk_drop_is_moderate(self):
        b = _baseline(total_chunks=491)
        cur = _baseline(total_chunks=456)  # -35, 25 < 35 < 75
        status, changes = compare(cur, b)
        self.assertEqual(status, "moderate_drift")

    def test_large_chunk_drop_is_major(self):
        b = _baseline(total_chunks=491)
        cur = _baseline(total_chunks=400)  # -91 > 75
        status, changes = compare(cur, b)
        self.assertEqual(status, "major_drift")
        chunk_change = next(c for c in changes if c["field"] == "total_chunks")
        self.assertEqual(chunk_change["severity"], "major")

    def test_chunk_growth_is_minor_for_small_increase(self):
        b = _baseline(total_chunks=491)
        cur = _baseline(total_chunks=495)
        status, _ = compare(cur, b)
        self.assertEqual(status, "minor_drift")

    def test_chunk_exact_boundary_moderate_to_major(self):
        # delta == 75 is moderate (not strictly > 75)
        b = _baseline(total_chunks=491)
        cur = _baseline(total_chunks=416)  # -75 exactly
        status, _ = compare(cur, b)
        self.assertEqual(status, "moderate_drift")

    def test_chunk_delta_76_is_major(self):
        b = _baseline(total_chunks=491)
        cur = _baseline(total_chunks=415)  # -76 > 75
        status, _ = compare(cur, b)
        self.assertEqual(status, "major_drift")


# ---------------------------------------------------------------------------
# URL changes
# ---------------------------------------------------------------------------

class TestURLChanges(unittest.TestCase):
    def test_url_addition_is_minor(self):
        b = _baseline(total_urls=28)
        cur = _baseline(total_urls=30)
        status, changes = compare(cur, b)
        self.assertEqual(status, "minor_drift")
        url_change = next(c for c in changes if c["field"] == "total_urls")
        self.assertEqual(url_change["severity"], "minor")

    def test_url_removal_is_minor(self):
        b = _baseline(total_urls=28)
        cur = _baseline(total_urls=25)
        status, changes = compare(cur, b)
        self.assertEqual(status, "minor_drift")
        url_change = next(c for c in changes if c["field"] == "total_urls")
        self.assertEqual(url_change["delta"], -3)


# ---------------------------------------------------------------------------
# Program changes
# ---------------------------------------------------------------------------

class TestProgramChanges(unittest.TestCase):
    def test_program_removal_is_major(self):
        b = _baseline(named_programs=["A", "B", "C", "D", "E"])
        cur = _baseline(
            named_programs=["A", "B", "C", "D"],  # E removed
            total_named_programs=4,
        )
        status, changes = compare(cur, b)
        self.assertEqual(status, "major_drift")
        prog_change = next(c for c in changes if "E" in c.get("field", ""))
        self.assertEqual(prog_change["severity"], "major")

    def test_new_program_addition_is_minor(self):
        b = _baseline(named_programs=["A", "B", "C", "D"])
        cur = _baseline(
            named_programs=["A", "B", "C", "D", "E"],
            total_named_programs=5,
        )
        status, changes = compare(cur, b)
        self.assertEqual(status, "minor_drift")
        prog_change = next(c for c in changes if "E" in c.get("field", ""))
        self.assertEqual(prog_change["severity"], "minor")


# ---------------------------------------------------------------------------
# Page-type changes
# ---------------------------------------------------------------------------

class TestPageTypeChanges(unittest.TestCase):
    def test_required_page_type_drops_to_zero_is_major(self):
        b_pt = {"faq": 98, "deadlines": 14, "eligibility": 11,
                "application_process": 19, "program_application": 349}
        cur_pt = dict(b_pt)
        cur_pt["faq"] = 0
        b = _baseline(chunks_by_page_type=b_pt)
        cur = _baseline(chunks_by_page_type=cur_pt)
        status, changes = compare(cur, b)
        self.assertEqual(status, "major_drift")
        pt_change = next(c for c in changes if "faq" in c["field"])
        self.assertEqual(pt_change["severity"], "major")

    def test_page_type_drops_more_than_50pct_is_moderate(self):
        b_pt = {"faq": 98, "deadlines": 14, "eligibility": 11,
                "application_process": 19, "program_application": 349}
        cur_pt = dict(b_pt)
        cur_pt["faq"] = 40  # dropped from 98 to 40, which is > 50% drop
        b = _baseline(chunks_by_page_type=b_pt)
        cur = _baseline(chunks_by_page_type=cur_pt)
        status, changes = compare(cur, b)
        self.assertEqual(status, "moderate_drift")

    def test_page_type_minor_change_is_minor(self):
        b_pt = {"faq": 98, "deadlines": 14, "eligibility": 11,
                "application_process": 19, "program_application": 349}
        cur_pt = dict(b_pt)
        cur_pt["faq"] = 100  # +2 chunks
        b = _baseline(chunks_by_page_type=b_pt)
        cur = _baseline(chunks_by_page_type=cur_pt)
        status, changes = compare(cur, b)
        self.assertEqual(status, "minor_drift")


# ---------------------------------------------------------------------------
# Duplicate changes
# ---------------------------------------------------------------------------

class TestDuplicateChanges(unittest.TestCase):
    def test_new_duplicates_introduced_is_moderate(self):
        b = _baseline(duplicate_chunk_id_count=1, total_extra_copies=6)
        cur = _baseline(duplicate_chunk_id_count=3, total_extra_copies=8)
        status, changes = compare(cur, b)
        self.assertEqual(status, "moderate_drift")
        dup_change = next(c for c in changes if c["field"] == "duplicate_chunk_id_count")
        self.assertEqual(dup_change["severity"], "moderate")

    def test_duplicates_resolved_is_minor(self):
        b = _baseline(duplicate_chunk_id_count=3, total_extra_copies=8)
        cur = _baseline(duplicate_chunk_id_count=0, total_extra_copies=0)
        status, changes = compare(cur, b)
        self.assertIn(status, ("minor_drift", "no_drift"))
        dup_change = next(c for c in changes if c["field"] == "duplicate_chunk_id_count")
        self.assertEqual(dup_change["severity"], "minor")


# ---------------------------------------------------------------------------
# Metadata drift
# ---------------------------------------------------------------------------

class TestMetadataDrift(unittest.TestCase):
    def test_missing_url_regression_is_major(self):
        b = _baseline(missing_url=0)
        cur = _baseline(missing_url=5)
        status, changes = compare(cur, b)
        self.assertEqual(status, "major_drift")
        url_change = next(c for c in changes if c["field"] == "missing_url")
        self.assertEqual(url_change["severity"], "major")

    def test_missing_chunk_id_regression_is_major(self):
        b = _baseline(missing_chunk_id=0)
        cur = _baseline(missing_chunk_id=1)
        status, changes = compare(cur, b)
        self.assertEqual(status, "major_drift")

    def test_metadata_issues_resolved_is_minor(self):
        b = _baseline(missing_url=3)
        cur = _baseline(missing_url=0)
        status, changes = compare(cur, b)
        self.assertIn(status, ("minor_drift", "no_drift"))

    def test_empty_chunk_introduced_is_major(self):
        b = _baseline(empty_chunks=0)
        cur = _baseline(empty_chunks=2)
        status, changes = compare(cur, b)
        self.assertEqual(status, "major_drift")


# ---------------------------------------------------------------------------
# Missing / malformed baseline
# ---------------------------------------------------------------------------

class TestMissingBaseline(unittest.TestCase):
    def test_missing_baseline_returns_no_baseline_status(self):
        report = detect_drift(baseline_path=Path("/tmp/does_not_exist_9c.json"))
        self.assertEqual(report["overall_drift"], "no_baseline")
        self.assertIsNone(report["baseline"])
        self.assertGreater(len(report["warnings"]), 0)

    def test_malformed_baseline_load_returns_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            bad_path = Path(f.name)
        result = load_baseline(bad_path)
        bad_path.unlink()
        self.assertIsNone(result)

    def test_missing_baseline_file_load_returns_none(self):
        result = load_baseline(Path("/tmp/definitely_nonexistent_9c.json"))
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Baseline persistence
# ---------------------------------------------------------------------------

class TestBaselinePersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        b = _baseline()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_baseline.json"
            saved = save_baseline(b, path=path)
            loaded = load_baseline(path=path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["total_chunks"], b["total_chunks"])
        self.assertEqual(loaded["named_programs"], b["named_programs"])

    def test_save_creates_parent_dirs(self):
        b = _baseline()
        with tempfile.TemporaryDirectory() as tmpdir:
            deep = Path(tmpdir) / "a" / "b" / "baseline.json"
            save_baseline(b, path=deep)
            self.assertTrue(deep.exists())


# ---------------------------------------------------------------------------
# Classification priority
# ---------------------------------------------------------------------------

class TestClassificationPriority(unittest.TestCase):
    def test_major_beats_minor_in_same_report(self):
        # URL changed (+1 minor) AND missing_url now > 0 (major)
        b = _baseline(total_urls=28, missing_url=0)
        cur = _baseline(total_urls=29, missing_url=3)
        status, _ = compare(cur, b)
        self.assertEqual(status, "major_drift")

    def test_severity_order_is_increasing(self):
        for lower, higher in [("no_drift", "minor"), ("minor", "moderate"),
                               ("moderate", "major")]:
            self.assertLess(_severity_order(lower), _severity_order(higher))

    def test_multiple_minor_changes_still_minor(self):
        b = _baseline(total_chunks=491, total_urls=28, short_chunks=2)
        cur = _baseline(total_chunks=493, total_urls=29, short_chunks=3)
        status, _ = compare(cur, b)
        self.assertEqual(status, "minor_drift")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class TestReportGeneration(unittest.TestCase):
    def test_format_no_drift(self):
        report = {
            "timestamp": "2026-01-01T00:00:00Z",
            "overall_drift": "no_drift",
            "baseline_captured_at": "2025-12-31T00:00:00Z",
            "current": _baseline(),
            "baseline": _baseline(),
            "changes": [],
            "warnings": [],
        }
        text = format_console_drift(report)
        self.assertIn("NO DRIFT", text)
        self.assertIn("Knowledge Base Drift", text)

    def test_format_major_drift(self):
        b = _baseline()
        cur = _baseline(total_chunks=400)
        _, changes = compare(cur, b)
        report = {
            "timestamp": "2026-01-01T00:00:00Z",
            "overall_drift": "major_drift",
            "baseline_captured_at": "2025-12-31T00:00:00Z",
            "current": cur, "baseline": b,
            "changes": changes, "warnings": [],
        }
        text = format_console_drift(report)
        self.assertIn("MAJOR DRIFT", text)

    def test_format_no_baseline(self):
        report = {
            "timestamp": "2026-01-01T00:00:00Z",
            "overall_drift": "no_baseline",
            "baseline_captured_at": None,
            "current": _baseline(), "baseline": None,
            "changes": [], "warnings": ["No baseline found"],
        }
        text = format_console_drift(report)
        self.assertIn("NO BASELINE", text)

    def test_write_drift_report_roundtrip(self):
        b = _baseline()
        cur = _baseline(total_chunks=495)
        _, changes = compare(cur, b)
        report = {
            "timestamp": "2026-01-01T00:00:00Z",
            "overall_drift": "minor_drift",
            "baseline_captured_at": "2025-12-31T00:00:00Z",
            "current": cur, "baseline": b,
            "changes": changes, "warnings": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "drift.json"
            written = write_drift_report(report, path=out_path)
            loaded = json.loads(out_path.read_text())
        self.assertEqual(loaded["overall_drift"], "minor_drift")

    def test_format_includes_summary_table(self):
        b = _baseline()
        report = {
            "timestamp": "2026-01-01T00:00:00Z",
            "overall_drift": "no_drift",
            "baseline_captured_at": "2025-12-31T00:00:00Z",
            "current": b, "baseline": b,
            "changes": [], "warnings": [],
        }
        text = format_console_drift(report)
        self.assertIn("Total Chunks", text)
        self.assertIn("Total URLs", text)
        self.assertIn("Named Programs", text)


# ---------------------------------------------------------------------------
# Live store tests
# ---------------------------------------------------------------------------

class TestLiveStore(unittest.TestCase):
    """Compare the live store against the saved baseline."""

    @classmethod
    def setUpClass(cls):
        from rag.store import load_vector_store
        cls.store = load_vector_store()
        if cls.store is None:
            raise unittest.SkipTest("Vector store not available")
        from obs.kb_drift import _DEFAULT_BASELINE_PATH
        cls.baseline_path = _DEFAULT_BASELINE_PATH
        if not cls.baseline_path.exists():
            raise unittest.SkipTest("No baseline saved — run --save-baseline first")

    def test_live_store_no_drift_against_itself(self):
        """Current store vs. the baseline captured from the same store → no_drift."""
        from obs.kb_health_report import inspect_kb
        health = inspect_kb(store=self.store)
        current = extract_baseline(health)
        baseline = load_baseline(self.baseline_path)
        status, changes = compare(current, baseline)
        self.assertEqual(status, "no_drift")
        self.assertEqual(changes, [])

    def test_detect_drift_returns_structured_report(self):
        report = detect_drift(store=self.store, baseline_path=self.baseline_path)
        self.assertIn("overall_drift", report)
        self.assertIn("current", report)
        self.assertIn("baseline", report)
        self.assertIn("changes", report)

    def test_detect_drift_is_deterministic(self):
        r1 = detect_drift(store=self.store, baseline_path=self.baseline_path)
        r2 = detect_drift(store=self.store, baseline_path=self.baseline_path)
        r1.pop("timestamp"); r2.pop("timestamp")
        self.assertEqual(r1, r2)


class TestNoBehaviorChange(unittest.TestCase):
    def test_retrieval_unchanged_after_drift_detection(self):
        from rag.retriever import retrieve
        before = retrieve("when is the application deadline", k=3)
        from obs.kb_drift import _DEFAULT_BASELINE_PATH
        if _DEFAULT_BASELINE_PATH.exists():
            detect_drift(baseline_path=_DEFAULT_BASELINE_PATH)
        after = retrieve("when is the application deadline", k=3)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
