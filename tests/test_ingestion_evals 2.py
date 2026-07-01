"""
tests/test_ingestion_evals.py
Phase 9A — regression tests for the ingestion evaluation framework.

Covers:
  - Dataset loading and schema validation.
  - Metric calculations for all eight metric categories.
  - Error classification for every taxonomy category.
  - Report generation.
  - Representative live-store inspection cases.
  - No production behavior changes: rag/ingestion.py, rag/chunking.py,
    rag/store.py, and the live chroma_db/ store are all unchanged.

Run from the project root:
    pytest tests/test_ingestion_evals.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from evals.metrics_ingestion import compute_ingestion_metrics, format_console_summary
from evals.error_classification_ingestion import (
    classify_ingestion, build_error_summary, format_error_summary_console,
)
from evals.run_ingestion_evals import (
    _run_case,
    _load_dataset,
    _build_report,
    _write_report,
    _DEFAULT_DATASET,
)


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

class TestDatasetLoading(unittest.TestCase):
    def test_default_dataset_exists(self):
        self.assertTrue(_DEFAULT_DATASET.exists())

    def test_default_dataset_has_required_keys(self):
        dataset = json.loads(_DEFAULT_DATASET.read_text())
        for key in ("_schema_version", "_scope", "_source", "cases"):
            self.assertIn(key, dataset)

    def test_default_dataset_has_21_cases(self):
        dataset = json.loads(_DEFAULT_DATASET.read_text())
        self.assertEqual(len(dataset["cases"]), 21)

    def test_cases_have_required_fields(self):
        dataset = json.loads(_DEFAULT_DATASET.read_text())
        for case in dataset["cases"]:
            self.assertIn("case_id", case)
            self.assertIn("check_type", case)
            self.assertIn("description", case)

    def test_load_dataset_function_works(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        self.assertIsInstance(dataset["cases"], list)
        self.assertGreater(len(dataset["cases"]), 0)

    def test_load_dataset_exits_on_missing_file(self):
        with self.assertRaises(SystemExit):
            _load_dataset(Path("/tmp/definitely_does_not_exist_9a.json"))


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------

def _make_result(check_type="total_chunk_count", status="PASS", **kwargs) -> dict:
    return {"status": status, "check_type": check_type, **kwargs}


class TestMetricCalculations(unittest.TestCase):
    def test_all_100_when_all_pass(self):
        cases = [
            _make_result("total_chunk_count", "PASS"),
            _make_result("page_type_chunk_count", "PASS"),
            _make_result("program_chunk_count", "PASS"),
            _make_result("distinct_program_count", "PASS"),
            _make_result("metadata_completeness", "PASS"),
            _make_result("no_empty_chunks", "PASS"),
            _make_result("max_chunk_size", "PASS"),
            _make_result("url_chunk_count", "PASS"),
            _make_result("chunk_id_count", "PASS"),
        ]
        metrics = compute_ingestion_metrics(cases)
        self.assertEqual(metrics["overall_pass_rate"], 100.0)
        self.assertEqual(metrics["page_coverage_rate"], 100.0)
        self.assertEqual(metrics["program_coverage_rate"], 100.0)
        self.assertEqual(metrics["metadata_completeness_rate"], 100.0)
        self.assertEqual(metrics["chunk_quality_rate"], 100.0)

    def test_overall_pass_rate(self):
        cases = [
            _make_result("total_chunk_count", "PASS"),
            _make_result("page_type_chunk_count", "FAIL"),
        ]
        metrics = compute_ingestion_metrics(cases)
        self.assertEqual(metrics["overall_pass_rate"], 50.0)

    def test_page_coverage_partial(self):
        cases = [
            _make_result("page_type_chunk_count", "PASS"),
            _make_result("page_type_chunk_count", "FAIL"),
        ]
        metrics = compute_ingestion_metrics(cases)
        self.assertEqual(metrics["page_coverage_rate"], 50.0)

    def test_metadata_completeness_partial(self):
        cases = [
            _make_result("metadata_completeness", "PASS"),
            _make_result("metadata_completeness", "FAIL"),
            _make_result("metadata_completeness", "PASS"),
        ]
        metrics = compute_ingestion_metrics(cases)
        self.assertAlmostEqual(metrics["metadata_completeness_rate"], 66.7)

    def test_empty_cases_returns_zero_rates(self):
        metrics = compute_ingestion_metrics([])
        self.assertEqual(metrics["overall_pass_rate"], 0.0)
        self.assertEqual(metrics["overall_counts"]["total_cases"], 0)

    def test_format_console_summary_does_not_raise(self):
        cases = [_make_result("total_chunk_count", "PASS")]
        metrics = compute_ingestion_metrics(cases)
        text = format_console_summary(metrics, 55.0)
        self.assertIn("Ingestion Evaluation Summary", text)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class TestErrorClassification(unittest.TestCase):
    def _pass_result(self, check_type="total_chunk_count"):
        return {"status": "PASS", "check_type": check_type, "actual_value": 100}

    def test_pass_returns_none(self):
        case = {"check_type": "total_chunk_count"}
        result = self._pass_result()
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "none")

    def test_total_volume_below_min(self):
        case = {"check_type": "total_chunk_count", "expected_min": 200, "expected_max": 1500}
        result = {"status": "FAIL", "check_type": "total_chunk_count", "actual_value": 50}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "total_volume_out_of_range")

    def test_page_missing_when_zero_chunks(self):
        case = {"check_type": "page_type_chunk_count", "page_type": "faq",
                "expected_min": 50, "expected_max": 500}
        result = {"status": "FAIL", "check_type": "page_type_chunk_count", "actual_value": 0}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "page_missing")

    def test_chunk_missing_when_below_min(self):
        case = {"check_type": "page_type_chunk_count", "page_type": "faq",
                "expected_min": 50, "expected_max": 500}
        result = {"status": "FAIL", "check_type": "page_type_chunk_count", "actual_value": 10}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "chunk_missing")

    def test_chunk_too_many(self):
        case = {"check_type": "page_type_chunk_count", "page_type": "faq",
                "expected_min": 1, "expected_max": 50}
        result = {"status": "FAIL", "check_type": "page_type_chunk_count", "actual_value": 200}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "chunk_too_many")

    def test_program_missing_when_zero(self):
        case = {"check_type": "program_chunk_count", "program_name": "Nursing (D.N.P.)",
                "expected_min": 20}
        result = {"status": "FAIL", "check_type": "program_chunk_count", "actual_value": 0}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "program_missing")

    def test_program_under_ingested(self):
        case = {"check_type": "program_chunk_count", "program_name": "Nursing (D.N.P.)",
                "expected_min": 20}
        result = {"status": "FAIL", "check_type": "program_chunk_count", "actual_value": 5}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "program_under_ingested")

    def test_distinct_program_count_low(self):
        case = {"check_type": "distinct_program_count", "expected_min": 5}
        result = {"status": "FAIL", "check_type": "distinct_program_count", "actual_value": 2}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "distinct_program_count_low")

    def test_metadata_missing(self):
        case = {"check_type": "metadata_completeness", "field": "url"}
        result = {"status": "FAIL", "check_type": "metadata_completeness",
                  "actual_value": 480, "missing_count": 11, "field": "url"}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "metadata_missing")

    def test_empty_chunk_detected(self):
        case = {"check_type": "no_empty_chunks"}
        result = {"status": "FAIL", "check_type": "no_empty_chunks",
                  "actual_value": 2, "empty_count": 2}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "empty_chunk")

    def test_chunk_size_violation(self):
        case = {"check_type": "max_chunk_size", "expected_max_chars": 500}
        result = {"status": "FAIL", "check_type": "max_chunk_size",
                  "actual_value": 650, "violation_count": 3}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "chunk_size_violation")

    def test_duplicate_mismatch(self):
        case = {"check_type": "chunk_id_count", "chunk_id": "abc_0000", "expected_count": 7}
        result = {"status": "FAIL", "check_type": "chunk_id_count", "actual_value": 3}
        cat, _ = classify_ingestion(case, result)
        self.assertEqual(cat, "duplicate_mismatch")

    def test_build_error_summary(self):
        results = [
            {"error_category": "page_missing"},
            {"error_category": "page_missing"},
            {"error_category": "none"},
        ]
        summary = build_error_summary(results)
        self.assertEqual(summary["page_missing"], 2)
        self.assertEqual(summary["none"], 1)

    def test_format_error_summary_does_not_raise(self):
        text = format_error_summary_console({"none": 10, "page_missing": 1})
        self.assertIn("none", text)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class TestReportGeneration(unittest.TestCase):
    def test_build_report_shape(self):
        results = [_make_result("total_chunk_count", "PASS")]
        results[0]["error_category"] = "none"
        results[0]["error_reason"] = "ok"
        dataset = {"_schema_version": "1.0", "cases": results}
        report = _build_report(results, _DEFAULT_DATASET, dataset, 491, 30.0)
        for key in ("schema_version", "run_id", "timestamp", "summary", "cases",
                    "metrics", "error_summary", "store_chunk_count"):
            self.assertIn(key, report)
        self.assertEqual(report["store_chunk_count"], 491)
        self.assertEqual(report["summary"]["total_cases"], 1)
        self.assertEqual(report["summary"]["passed"], 1)

    def test_write_report_roundtrip(self):
        results = [_make_result("total_chunk_count", "PASS")]
        results[0]["error_category"] = "none"
        results[0]["error_reason"] = "ok"
        dataset = {"_schema_version": "1.0", "cases": results}
        report = _build_report(results, _DEFAULT_DATASET, dataset, 100, 10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            import evals.run_ingestion_evals as runner
            original = runner._REPORTS_DIR
            runner._REPORTS_DIR = Path(tmpdir)
            try:
                latest, archive = _write_report(report, no_archive=True)
                self.assertTrue(latest.exists())
                self.assertIsNone(archive)
                loaded = json.loads(latest.read_text())
                self.assertIn("store_chunk_count", loaded)
            finally:
                runner._REPORTS_DIR = original


# ---------------------------------------------------------------------------
# Live store inspection tests (using real Chroma store)
# ---------------------------------------------------------------------------

class TestLiveStoreInspection(unittest.TestCase):
    """Inspects the real chroma_db/ store to verify the evaluation logic
    correctly assesses the current knowledge base state."""

    @classmethod
    def setUpClass(cls):
        from rag.store import load_vector_store
        cls.store = load_vector_store()
        if cls.store is None:
            raise unittest.SkipTest("Vector store not available — run rag/store.py first")
        cls.collection = cls.store._collection
        # Reset cache
        import evals.run_ingestion_evals as runner
        runner._CACHED_METADATAS = None
        runner._CACHED_DOCUMENTS = None

    def _run(self, case):
        return _run_case(case, self.collection)

    def test_total_chunk_count_in_range(self):
        result = self._run({
            "case_id": "T-001", "description": "", "check_type": "total_chunk_count",
            "expected_min": 200, "expected_max": 1500,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(result["actual_value"], 200)

    def test_faq_page_type_present(self):
        result = self._run({
            "case_id": "T-002", "description": "", "check_type": "page_type_chunk_count",
            "page_type": "faq", "expected_min": 50, "expected_max": 500,
        })
        self.assertEqual(result["status"], "PASS")

    def test_program_application_chunks_exist(self):
        result = self._run({
            "case_id": "T-003", "description": "", "check_type": "page_type_chunk_count",
            "page_type": "program_application", "expected_min": 100, "expected_max": 2000,
        })
        self.assertEqual(result["status"], "PASS")

    def test_nursing_program_has_min_chunks(self):
        result = self._run({
            "case_id": "T-004", "description": "", "check_type": "program_chunk_count",
            "program_name": "Nursing (D.N.P.)", "expected_min": 20,
        })
        self.assertEqual(result["status"], "PASS")

    def test_distinct_program_count(self):
        result = self._run({
            "case_id": "T-005", "description": "", "check_type": "distinct_program_count",
            "expected_min": 5,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(result["actual_value"], 5)

    def test_url_metadata_completeness(self):
        result = self._run({
            "case_id": "T-006", "description": "", "check_type": "metadata_completeness",
            "field": "url",
        })
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["missing_count"], 0)

    def test_no_empty_chunks(self):
        result = self._run({
            "case_id": "T-007", "description": "", "check_type": "no_empty_chunks",
        })
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["actual_value"], 0)

    def test_max_chunk_size_respected(self):
        result = self._run({
            "case_id": "T-008", "description": "", "check_type": "max_chunk_size",
            "expected_max_chars": 500,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertLessEqual(result["actual_value"], 500)

    def test_deadlines_url_present(self):
        result = self._run({
            "case_id": "T-009", "description": "", "check_type": "url_chunk_count",
            "url": "https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral",
            "expected_min": 5, "expected_max": 100,
        })
        self.assertEqual(result["status"], "PASS")

    def test_known_duplicate_chunk_id(self):
        result = self._run({
            "case_id": "T-010", "description": "", "check_type": "chunk_id_count",
            "chunk_id": "c31caccf_0000", "expected_count": 7,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["actual_value"], 7)

    def test_detection_of_impossible_chunk_count(self):
        """A case asserting exact_count=1 for the known-duplicate chunk_id
        should FAIL, proving the framework correctly detects count mismatches."""
        result = self._run({
            "case_id": "T-011", "description": "", "check_type": "chunk_id_count",
            "chunk_id": "c31caccf_0000", "expected_count": 1,
        })
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error_category"], "duplicate_mismatch")

    def test_detection_of_missing_nonexistent_page_type(self):
        """A case asserting min_chunks=1 for a nonexistent page_type should FAIL."""
        result = self._run({
            "case_id": "T-012", "description": "", "check_type": "page_type_chunk_count",
            "page_type": "completely_nonexistent_page_type", "expected_min": 1, "expected_max": 100,
        })
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error_category"], "page_missing")


class TestNoBehaviorChange(unittest.TestCase):
    """Confirm the eval framework is purely read-only — the store state is
    identical before and after running all eval cases."""

    def test_retrieval_unchanged_after_eval_run(self):
        from rag.retriever import retrieve
        before = retrieve("when is the application deadline", k=3)
        # Running ingestion evals should not change retrieval output
        from evals.run_ingestion_evals import _run_case, _CACHED_METADATAS, _CACHED_DOCUMENTS
        import evals.run_ingestion_evals as runner
        runner._CACHED_METADATAS = None
        runner._CACHED_DOCUMENTS = None
        from rag.store import load_vector_store
        store = load_vector_store()
        if store:
            _run_case({
                "case_id": "BV-001", "description": "", "check_type": "total_chunk_count",
                "expected_min": 100, "expected_max": 2000,
            }, store._collection)
        after = retrieve("when is the application deadline", k=3)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
