"""
tests/test_retrieval_evals.py
Phase 8A — regression tests for the retrieval evaluation framework itself.

Covers:
  - Dataset validation: required keys, required per-case fields, unique
    case IDs.
  - Metric calculations: top-1/top-k accuracy, recall, forbidden-source
    rate, duplicate-chunk rate, no-result rate, unexpected-retrieval rate —
    computed from hand-built case-result fixtures, not the live store.
  - Runner execution: every real dataset case runs against the live
    rag.retriever.retrieve() without raising.
  - Report generation: _build_report() shape; _write_report() writes both
    latest and archive files.
  - Failure classification: each category assigned correctly for a
    constructed scenario.
  - Edge cases: empty query, whitespace-only query, deliberately mismatched
    filter.
  - Empty retrieval: an out-of-scope query correctly yields is_empty=True
    with no error.
  - Duplicate retrieval: a hand-built result list with a repeated chunk_id
    is correctly flagged.

Run from the project root:
    pytest tests/test_retrieval_evals.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from unittest.mock import patch

from evals.run_retrieval_evals import (
    _run_case,
    _matches_source,
    _build_report,
    _write_report,
    _load_dataset,
    _DEFAULT_DATASET,
)
from evals.metrics_retrieval import compute_retrieval_metrics
from evals.error_classification_retrieval import classify_retrieval, build_error_summary


class TestDatasetValidation(unittest.TestCase):
    def test_dataset_loads_and_has_required_keys(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        for key in ("_schema_version", "_scope", "_source", "cases"):
            self.assertIn(key, dataset)
        self.assertGreater(len(dataset["cases"]), 0)

    def test_every_case_has_required_fields(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        for case in dataset["cases"]:
            for field in ("case_id", "query", "expected_sources", "forbidden_sources"):
                self.assertIn(field, case, case.get("case_id"))

    def test_case_ids_are_unique(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        ids = [c["case_id"] for c in dataset["cases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_dataset_includes_positive_negative_and_edge_cases(self):
        """Sanity check on dataset composition, not a specific case_id."""
        dataset = _load_dataset(_DEFAULT_DATASET)
        cases = dataset["cases"]
        has_positive = any(c.get("expected_sources") for c in cases)
        has_empty_expectation = any(c.get("expect_empty") for c in cases)
        has_forbidden = any(c.get("forbidden_sources") for c in cases)
        self.assertTrue(has_positive)
        self.assertTrue(has_empty_expectation)
        self.assertTrue(has_forbidden)


class TestSourceMatching(unittest.TestCase):
    def test_matches_on_page_type(self):
        result = {"page_type": "eligibility", "url": "https://x"}
        self.assertTrue(_matches_source(result, {"page_type": "eligibility"}))
        self.assertFalse(_matches_source(result, {"page_type": "deadlines"}))

    def test_matches_on_url(self):
        result = {"page_type": "eligibility", "url": "https://x"}
        self.assertTrue(_matches_source(result, {"url": "https://x"}))
        self.assertFalse(_matches_source(result, {"url": "https://y"}))

    def test_matches_on_both(self):
        result = {"page_type": "eligibility", "url": "https://x"}
        self.assertTrue(_matches_source(result, {"page_type": "eligibility", "url": "https://x"}))
        self.assertFalse(_matches_source(result, {"page_type": "eligibility", "url": "https://y"}))

    def test_empty_spec_matches_anything(self):
        result = {"page_type": "eligibility", "url": "https://x"}
        self.assertTrue(_matches_source(result, {}))


class TestRunnerExecution(unittest.TestCase):
    def test_all_real_dataset_cases_run_without_exception(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        for case in dataset["cases"]:
            try:
                _run_case(case)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"{case['case_id']} raised: {exc}")

    def test_empty_query_case_yields_empty_result_no_error(self):
        case = {"case_id": "T-EMPTY", "query": "", "expected_sources": [],
                 "forbidden_sources": [], "expect_empty": True, "k": 3}
        result = _run_case(case)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["actual"]["is_empty"])

    def test_whitespace_query_case_yields_empty_result_no_error(self):
        case = {"case_id": "T-WS", "query": "   ", "expected_sources": [],
                 "forbidden_sources": [], "expect_empty": True, "k": 3}
        result = _run_case(case)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["actual"]["is_empty"])

    def test_mismatched_filter_excludes_forbidden_source(self):
        case = {
            "case_id": "T-MISMATCH",
            "query": "what gpa do i need for a doctoral program",
            "page_type_filter": "deadlines",
            "k": 3,
            "expected_sources": [],
            "forbidden_sources": [{"page_type": "eligibility"}],
            "expect_empty": False,
        }
        result = _run_case(case)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["forbidden_found"], [])


class TestDuplicateDetection(unittest.TestCase):
    def test_duplicate_chunk_ids_detected_via_hand_built_results(self):
        """Verify the duplicate-detection logic itself (not the live store)
        using a mocked retrieve() return value."""
        case = {
            "case_id": "T-DUP",
            "query": "anything",
            "expected_sources": [],
            "forbidden_sources": [],
            "expect_empty": False,
        }
        fake_results = [
            {"page_type": "deadlines", "url": "https://x", "score": 0.5, "chunk_id": "a_0000"},
            {"page_type": "deadlines", "url": "https://x", "score": 0.5, "chunk_id": "a_0000"},
        ]
        with patch("evals.run_retrieval_evals.retrieve", return_value=fake_results):
            result = _run_case(case)
        self.assertTrue(result["actual"]["has_duplicates"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error_category"], "duplicate_chunks")

    def test_allow_duplicate_chunks_flag_suppresses_failure(self):
        case = {
            "case_id": "T-DUP-ALLOWED",
            "query": "anything",
            "expected_sources": [],
            "forbidden_sources": [],
            "expect_empty": False,
            "allow_duplicate_chunks": True,
        }
        fake_results = [
            {"page_type": "deadlines", "url": "https://x", "score": 0.5, "chunk_id": "a_0000"},
            {"page_type": "deadlines", "url": "https://x", "score": 0.5, "chunk_id": "a_0000"},
        ]
        with patch("evals.run_retrieval_evals.retrieve", return_value=fake_results):
            result = _run_case(case)
        self.assertTrue(result["actual"]["has_duplicates"])  # still recorded
        self.assertEqual(result["status"], "PASS")  # but doesn't fail the case

    def test_no_duplicates_when_chunk_ids_distinct(self):
        case = {"case_id": "T-NODUP", "query": "x", "expected_sources": [], "forbidden_sources": [], "expect_empty": False}
        fake_results = [
            {"page_type": "deadlines", "url": "https://x", "score": 0.5, "chunk_id": "a_0000"},
            {"page_type": "deadlines", "url": "https://x", "score": 0.4, "chunk_id": "a_0001"},
        ]
        with patch("evals.run_retrieval_evals.retrieve", return_value=fake_results):
            result = _run_case(case)
        self.assertFalse(result["actual"]["has_duplicates"])


class TestMetrics(unittest.TestCase):
    def _fake_case(self, **overrides):
        base = {
            "status": "PASS",
            "actual": {"num_results": 2, "is_empty": False, "top_score": 0.5, "has_duplicates": False},
            "expected_sources": [{"page_type": "eligibility"}],
            "expected_source_results": [{"spec": {"page_type": "eligibility"}, "found": True}],
            "forbidden_found": [],
            "top1_match": True,
            "topk_match": True,
            "expect_empty": False,
        }
        base.update(overrides)
        return base

    def test_top1_and_topk_accuracy_all_pass(self):
        cases = [self._fake_case(), self._fake_case()]
        metrics = compute_retrieval_metrics(cases)
        self.assertEqual(metrics["top_1_accuracy"], 100.0)
        self.assertEqual(metrics["top_k_accuracy"], 100.0)

    def test_top1_accuracy_drops_on_ranking_error(self):
        cases = [
            self._fake_case(),
            self._fake_case(top1_match=False, topk_match=True,
                              expected_source_results=[{"spec": {}, "found": True}]),
        ]
        metrics = compute_retrieval_metrics(cases)
        self.assertEqual(metrics["top_1_accuracy"], 50.0)
        self.assertEqual(metrics["top_k_accuracy"], 100.0)

    def test_forbidden_source_rate(self):
        cases = [self._fake_case(), self._fake_case(forbidden_found=[{"page_type": "x"}])]
        metrics = compute_retrieval_metrics(cases)
        self.assertEqual(metrics["forbidden_source_rate"], 50.0)

    def test_no_result_rate(self):
        cases = [
            self._fake_case(),
            self._fake_case(actual={"num_results": 0, "is_empty": True, "top_score": 0.0, "has_duplicates": False}),
        ]
        metrics = compute_retrieval_metrics(cases)
        self.assertEqual(metrics["no_result_rate"], 50.0)

    def test_duplicate_chunk_rate(self):
        cases = [
            self._fake_case(),
            self._fake_case(actual={"num_results": 2, "is_empty": False, "top_score": 0.5, "has_duplicates": True}),
        ]
        metrics = compute_retrieval_metrics(cases)
        self.assertEqual(metrics["duplicate_chunk_rate"], 50.0)

    def test_unexpected_retrieval_rate(self):
        cases = [
            self._fake_case(expect_empty=True, expected_sources=[],
                              actual={"num_results": 1, "is_empty": False, "top_score": 0.4, "has_duplicates": False}),
            self._fake_case(expect_empty=True, expected_sources=[],
                              actual={"num_results": 0, "is_empty": True, "top_score": 0.0, "has_duplicates": False}),
        ]
        metrics = compute_retrieval_metrics(cases)
        self.assertEqual(metrics["unexpected_retrieval_rate"], 50.0)

    def test_empty_case_list_does_not_divide_by_zero(self):
        metrics = compute_retrieval_metrics([])
        self.assertEqual(metrics["overall_counts"]["total_cases"], 0)
        self.assertEqual(metrics["top_1_accuracy"], 0.0)


class TestFailureClassification(unittest.TestCase):
    def test_classify_none_on_clean_pass(self):
        case = {"expect_empty": False, "expected_sources": [{"page_type": "eligibility"}]}
        result = {
            "status": "PASS",
            "actual": {"is_empty": False, "has_duplicates": False, "num_results": 1},
            "expected_source_results": [{"found": True}],
            "forbidden_found": [],
            "top1_match": True, "topk_match": True,
        }
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "none")

    def test_classify_empty_context(self):
        case = {"expect_empty": True}
        result = {"status": "FAIL", "actual": {"is_empty": False, "num_results": 1, "has_duplicates": False},
                  "expected_source_results": [], "forbidden_found": []}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "empty_context")

    def test_classify_no_retrieval(self):
        case = {"expect_empty": False, "expected_min_chunks": 1}
        result = {"status": "FAIL", "actual": {"is_empty": True, "num_results": 0, "has_duplicates": False},
                  "expected_source_results": [], "forbidden_found": []}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "no_retrieval")

    def test_classify_unexpected_source(self):
        case = {"expect_empty": False, "expected_sources": []}
        result = {"status": "FAIL", "actual": {"is_empty": False, "num_results": 1, "has_duplicates": False},
                  "expected_source_results": [], "forbidden_found": [{"page_type": "x"}]}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "unexpected_source")

    def test_classify_missing_expected_source(self):
        case = {"expect_empty": False, "expected_sources": [{"page_type": "eligibility"}]}
        result = {"status": "FAIL", "actual": {"is_empty": False, "num_results": 1, "has_duplicates": False},
                  "expected_source_results": [{"found": False}], "forbidden_found": []}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "missing_expected_source")

    def test_classify_partial_match(self):
        case = {"expect_empty": False, "expected_sources": [{"page_type": "a"}, {"page_type": "b"}]}
        result = {"status": "FAIL", "actual": {"is_empty": False, "num_results": 2, "has_duplicates": False},
                  "expected_source_results": [{"found": True}, {"found": False}],
                  "forbidden_found": [], "top1_match": True, "topk_match": True}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "partial_match")

    def test_classify_ranking_error(self):
        case = {"expect_empty": False, "expected_sources": [{"page_type": "eligibility"}]}
        result = {"status": "FAIL", "actual": {"is_empty": False, "num_results": 3, "has_duplicates": False},
                  "expected_source_results": [{"found": True}],
                  "forbidden_found": [], "top1_match": False, "topk_match": True}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "ranking_error")

    def test_classify_duplicate_chunks(self):
        case = {"expect_empty": False, "expected_sources": [], "allow_duplicate_chunks": False}
        result = {"status": "FAIL", "actual": {"is_empty": False, "num_results": 2, "has_duplicates": True},
                  "expected_source_results": [], "forbidden_found": []}
        category, _ = classify_retrieval(case, result)
        self.assertEqual(category, "duplicate_chunks")

    def test_build_error_summary_counts_categories(self):
        results = [{"error_category": "none"}, {"error_category": "none"}, {"error_category": "duplicate_chunks"}]
        summary = build_error_summary(results)
        self.assertEqual(summary, {"none": 2, "duplicate_chunks": 1})


class TestReportGeneration(unittest.TestCase):
    def test_build_report_shape(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        results = [_run_case(c) for c in dataset["cases"][:3]]
        report = _build_report(results, _DEFAULT_DATASET, dataset, 1.0)
        self.assertIn("summary", report)
        self.assertIn("cases", report)
        self.assertIn("metrics", report)
        self.assertIn("error_summary", report)
        self.assertEqual(report["summary"]["total_cases"], 3)

    def test_write_report_creates_latest_and_archive(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        results = [_run_case(dataset["cases"][0])]
        report = _build_report(results, _DEFAULT_DATASET, dataset, 1.0)
        latest, archive = _write_report(report, no_archive=False)
        self.assertTrue(latest.exists())
        self.assertIsNotNone(archive)
        self.assertTrue(archive.exists())


if __name__ == "__main__":
    unittest.main()
