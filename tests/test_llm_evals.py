"""
tests/test_llm_evals.py
Phase 7D — regression tests for the LLM evaluation framework itself.

Covers:
  - Dataset schema (both datasets load, required keys present, every case
    has the fields the runner depends on).
  - Evaluation runner: per-case execution for both recommendation
    explanation and grounded answer cases, including the 3 intentionally-
    crafted "bad explanation" cases that prove evidence_omission/
    unsupported_claim detection actually works (not just that good cases
    pass).
  - Metrics: compute_explanation_metrics() / compute_answer_metrics()
    produce correct rates from hand-built case-result fixtures.
  - Report generation: _build_report() produces the expected shape;
    _write_report() writes both latest and archive files.
  - Failure classification: classify_explanation() / classify_answer()
    assign the correct category for each known scenario.
  - Mocked LLM outputs: _patch_requests_post() produces the right
    behavior for every simulate mode.
  - Feature flag disabled: explicitly NOT covered by the runner itself
    (the runner always force-enables the flag via patch.object, exactly
    like tests/test_recommendation_explainer.py and
    tests/test_grounded_answer_generation.py already do) — this file adds
    one direct check that disabling the flag is still respected by the
    underlying functions the runner calls.
  - Deterministic fallback: a connection-error case never raises.

Run from the project root:
    pytest tests/test_llm_evals.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import unittest
import tempfile

import requests

from evals.run_llm_evals import (
    _run_explanation_case,
    _run_answer_case,
    _derive_explanation_outcome,
    _derive_answer_outcome,
    _patch_requests_post,
    _build_report,
    _write_report,
    _load_dataset,
    _EXPLANATION_DATASET,
    _ANSWER_DATASET,
)
from evals.metrics_llm import compute_explanation_metrics, compute_answer_metrics
from evals.error_classification_llm import (
    classify_explanation, classify_answer, build_error_summary,
)


class TestDatasetSchema(unittest.TestCase):
    def test_explanation_dataset_loads_and_has_required_keys(self):
        dataset = _load_dataset(_EXPLANATION_DATASET)
        for key in ("_schema_version", "_scope", "_source", "cases"):
            self.assertIn(key, dataset)
        self.assertGreater(len(dataset["cases"]), 0)

    def test_answer_dataset_loads_and_has_required_keys(self):
        dataset = _load_dataset(_ANSWER_DATASET)
        for key in ("_schema_version", "_scope", "_source", "cases"):
            self.assertIn(key, dataset)
        self.assertGreater(len(dataset["cases"]), 0)

    def test_every_explanation_case_has_required_fields(self):
        dataset = _load_dataset(_EXPLANATION_DATASET)
        for case in dataset["cases"]:
            for field in ("case_id", "program_match", "simulate", "expected_outcome"):
                self.assertIn(field, case, case.get("case_id"))
            self.assertIn("program_id", case["program_match"])
            self.assertIn("score_basis", case["program_match"])
            self.assertIn("mode", case["simulate"])

    def test_every_answer_case_has_required_fields(self):
        dataset = _load_dataset(_ANSWER_DATASET)
        for case in dataset["cases"]:
            for field in ("case_id", "query", "retrieved_evidence", "simulate", "expected_outcome"):
                self.assertIn(field, case, case.get("case_id"))
            self.assertIn("mode", case["simulate"])

    def test_explanation_case_ids_are_unique(self):
        dataset = _load_dataset(_EXPLANATION_DATASET)
        ids = [c["case_id"] for c in dataset["cases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_answer_case_ids_are_unique(self):
        dataset = _load_dataset(_ANSWER_DATASET)
        ids = [c["case_id"] for c in dataset["cases"]]
        self.assertEqual(len(ids), len(set(ids)))


class TestPatchRequestsPost(unittest.TestCase):
    def test_success_mode_returns_scripted_content(self):
        with _patch_requests_post({"mode": "success", "explanation": "x"}):
            resp = requests.post("http://fake", json={}, timeout=1)
        content = json.loads(resp.json()["message"]["content"])
        self.assertEqual(content["explanation"], "x")

    def test_connection_error_mode_raises(self):
        with _patch_requests_post({"mode": "connection_error"}):
            with self.assertRaises(requests.exceptions.ConnectionError):
                requests.post("http://fake", json={}, timeout=1)

    def test_timeout_mode_raises(self):
        with _patch_requests_post({"mode": "timeout"}):
            with self.assertRaises(requests.exceptions.Timeout):
                requests.post("http://fake", json={}, timeout=1)

    def test_malformed_json_mode_returns_unparseable_content(self):
        with _patch_requests_post({"mode": "malformed_json"}):
            resp = requests.post("http://fake", json={}, timeout=1)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(resp.json()["message"]["content"])

    def test_unknown_mode_raises_value_error(self):
        with self.assertRaises(ValueError):
            _patch_requests_post({"mode": "not_a_real_mode"})


class TestExplanationCaseExecution(unittest.TestCase):
    def test_good_case_passes(self):
        case = {
            "case_id": "T-GOOD",
            "program_match": {"program_id": "x", "confidence": "high", "score_basis": ["interest_1:nursing"]},
            "simulate": {"mode": "success", "explanation": "Matches your interest in nursing."},
            "expected_evidence_phrases": ["nursing"],
            "forbidden_phrases": ["accepted"],
            "expected_outcome": "explanation_attached",
        }
        result = _run_explanation_case(case)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["error_category"], "none")

    def test_evidence_omission_is_detected_as_fail(self):
        case = {
            "case_id": "T-OMIT",
            "program_match": {"program_id": "x", "confidence": "medium", "score_basis": ["interest_1:nursing"]},
            "simulate": {"mode": "success", "explanation": "This program is a good fit."},
            "expected_evidence_phrases": ["nursing"],
            "forbidden_phrases": [],
            "expected_outcome": "explanation_attached",
        }
        result = _run_explanation_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error_category"], "evidence_omission")

    def test_unsupported_claim_is_detected_as_fail(self):
        case = {
            "case_id": "T-CLAIM",
            "program_match": {"program_id": "x", "confidence": "high", "score_basis": ["interest_1:nursing"]},
            "simulate": {"mode": "success", "explanation": "You will be accepted given your nursing interest."},
            "expected_evidence_phrases": ["nursing"],
            "forbidden_phrases": ["accepted"],
            "expected_outcome": "explanation_attached",
        }
        result = _run_explanation_case(case)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error_category"], "unsupported_claim")

    def test_no_evidence_case_passes_with_no_explanation(self):
        case = {
            "case_id": "T-NOEV",
            "program_match": {"program_id": "x", "confidence": "none", "score_basis": []},
            "simulate": {"mode": "success", "explanation": "should not be used"},
            "expected_evidence_phrases": [],
            "forbidden_phrases": [],
            "expected_outcome": "no_explanation_no_evidence",
        }
        result = _run_explanation_case(case)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["actual_outcome"], "no_explanation_no_evidence")

    def test_connection_error_case_passes_with_graceful_fallback(self):
        case = {
            "case_id": "T-CONN",
            "program_match": {"program_id": "x", "confidence": "high", "score_basis": ["interest_1:nursing"]},
            "simulate": {"mode": "connection_error"},
            "expected_evidence_phrases": [],
            "forbidden_phrases": [],
            "expected_outcome": "no_explanation_graceful_fallback",
        }
        result = _run_explanation_case(case)
        self.assertEqual(result["status"], "PASS")

    def test_deterministic_fields_never_change(self):
        case = {
            "case_id": "T-DET",
            "program_match": {
                "program_id": "dnp-nursing", "confidence": "high",
                "score_basis": ["interest_1:nursing"],
                "advisor_email": "a@csulb.edu", "deadline_fall": "Jan 15",
            },
            "simulate": {"mode": "success", "explanation": "Matches nursing."},
            "expected_evidence_phrases": ["nursing"],
            "forbidden_phrases": [],
            "expected_outcome": "explanation_attached",
        }
        result = _run_explanation_case(case)
        self.assertFalse(result["deterministic_drift_detected"])

    def test_all_real_dataset_cases_run_without_exception(self):
        dataset = _load_dataset(_EXPLANATION_DATASET)
        for case in dataset["cases"]:
            try:
                _run_explanation_case(case)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"{case['case_id']} raised: {exc}")


class TestAnswerCaseExecution(unittest.TestCase):
    def test_legitimate_citation_accepted(self):
        case = {
            "case_id": "T-CITE",
            "query": "q",
            "retrieved_evidence": {"source": "https://www.csulb.edu/x"},
            "source_url": None,
            "simulate": {"mode": "success", "answer": "See https://www.csulb.edu/x.", "confidence": "high"},
            "expected_outcome": "accepted",
        }
        result = _run_answer_case(case)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["error_category"], "none")

    def test_fabricated_citation_rejected(self):
        case = {
            "case_id": "T-FAB",
            "query": "q",
            "retrieved_evidence": {"text": "no urls"},
            "source_url": None,
            "simulate": {"mode": "success", "answer": "See https://invented.example.com.", "confidence": "high"},
            "expected_outcome": "rejected_fabricated_citation",
        }
        result = _run_answer_case(case)
        self.assertEqual(result["status"], "PASS")  # correctly predicted rejection
        self.assertIsNone(result["llm_result"])

    def test_network_failure_falls_back_cleanly(self):
        case = {
            "case_id": "T-NET",
            "query": "q",
            "retrieved_evidence": {"text": "x"},
            "source_url": None,
            "simulate": {"mode": "connection_error"},
            "expected_outcome": "rejected_network_failure",
        }
        try:
            result = _run_answer_case(case)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"raised unexpectedly: {exc}")
        self.assertEqual(result["status"], "PASS")

    def test_all_real_dataset_cases_run_without_exception(self):
        dataset = _load_dataset(_ANSWER_DATASET)
        for case in dataset["cases"]:
            try:
                _run_answer_case(case)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"{case['case_id']} raised: {exc}")


class TestMetrics(unittest.TestCase):
    def test_explanation_metrics_deterministic_consistency_rate(self):
        cases = [
            {"status": "PASS", "deterministic_drift_detected": False, "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached", "evidence_fully_covered": True, "forbidden_phrase_found": False},
            {"status": "PASS", "deterministic_drift_detected": False, "actual_outcome": "no_explanation_no_evidence",
             "expected_outcome": "no_explanation_no_evidence"},
        ]
        metrics = compute_explanation_metrics(cases)
        self.assertEqual(metrics["deterministic_consistency_rate"], 100.0)

    def test_explanation_metrics_drift_lowers_consistency_rate(self):
        cases = [
            {"status": "FAIL", "deterministic_drift_detected": True, "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached"},
            {"status": "PASS", "deterministic_drift_detected": False, "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached", "evidence_fully_covered": True, "forbidden_phrase_found": False},
        ]
        metrics = compute_explanation_metrics(cases)
        self.assertEqual(metrics["deterministic_consistency_rate"], 50.0)

    def test_explanation_metrics_evidence_coverage_rate(self):
        cases = [
            {"status": "PASS", "deterministic_drift_detected": False, "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached", "evidence_fully_covered": True, "forbidden_phrase_found": False},
            {"status": "FAIL", "deterministic_drift_detected": False, "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached", "evidence_fully_covered": False, "forbidden_phrase_found": False},
        ]
        metrics = compute_explanation_metrics(cases)
        self.assertEqual(metrics["evidence_coverage_rate"], 50.0)

    def test_answer_metrics_citation_fidelity_rate(self):
        cases = [
            {"status": "PASS", "expected_outcome": "accepted", "actual_outcome": "accepted", "simulated_confidence": "high"},
            {"status": "FAIL", "expected_outcome": "accepted", "actual_outcome": "rejected_fabricated_citation", "simulated_confidence": "high"},
        ]
        metrics = compute_answer_metrics(cases)
        self.assertEqual(metrics["citation_fidelity_rate"], 50.0)

    def test_answer_metrics_unsupported_url_rejection_rate(self):
        cases = [
            {"status": "PASS", "expected_outcome": "rejected_fabricated_citation",
             "actual_outcome": "rejected_fabricated_citation", "simulated_confidence": "high"},
        ]
        metrics = compute_answer_metrics(cases)
        self.assertEqual(metrics["unsupported_url_rejection_rate"], 100.0)

    def test_empty_case_list_does_not_divide_by_zero(self):
        metrics = compute_explanation_metrics([])
        self.assertEqual(metrics["overall_counts"]["total_cases"], 0)
        metrics2 = compute_answer_metrics([])
        self.assertEqual(metrics2["overall_counts"]["total_cases"], 0)


class TestFailureClassification(unittest.TestCase):
    def test_classify_explanation_none_on_clean_pass(self):
        case = {"expected_outcome": "explanation_attached"}
        result = {"actual_outcome": "explanation_attached", "deterministic_drift_detected": False,
                  "forbidden_phrase_found": False, "evidence_fully_covered": True}
        category, _ = classify_explanation(case, result)
        self.assertEqual(category, "none")

    def test_classify_explanation_deterministic_drift_takes_priority(self):
        case = {"expected_outcome": "explanation_attached"}
        result = {"actual_outcome": "explanation_attached", "deterministic_drift_detected": True,
                  "forbidden_phrase_found": True}  # even with another issue present
        category, _ = classify_explanation(case, result)
        self.assertEqual(category, "deterministic_drift")

    def test_classify_explanation_missing_explanation(self):
        case = {"expected_outcome": "explanation_attached"}
        result = {"actual_outcome": "no_explanation_validation_failure", "deterministic_drift_detected": False}
        category, _ = classify_explanation(case, result)
        self.assertEqual(category, "missing_explanation")

    def test_classify_answer_none_on_clean_pass(self):
        case = {"expected_outcome": "accepted"}
        result = {"actual_outcome": "accepted"}
        category, _ = classify_answer(case, result)
        self.assertEqual(category, "none")

    def test_classify_answer_fabricated_citation(self):
        case = {"expected_outcome": "accepted"}
        result = {"actual_outcome": "rejected_fabricated_citation"}
        category, _ = classify_answer(case, result)
        self.assertEqual(category, "fabricated_citation")

    def test_build_error_summary_counts_categories(self):
        results = [{"error_category": "none"}, {"error_category": "none"}, {"error_category": "unsupported_claim"}]
        summary = build_error_summary(results)
        self.assertEqual(summary, {"none": 2, "unsupported_claim": 1})


class TestReportGeneration(unittest.TestCase):
    def test_build_report_shape(self):
        explanation_dataset = _load_dataset(_EXPLANATION_DATASET)
        answer_dataset       = _load_dataset(_ANSWER_DATASET)
        explanation_results  = [_run_explanation_case(c) for c in explanation_dataset["cases"][:2]]
        answer_results        = [_run_answer_case(c) for c in answer_dataset["cases"][:2]]

        report = _build_report(explanation_results, answer_results, explanation_dataset, answer_dataset, 1.0)

        self.assertIn("summary", report)
        self.assertIn("recommendation_explanation", report)
        self.assertIn("grounded_answer", report)
        self.assertEqual(report["summary"]["total_cases"], 4)

    def test_write_report_creates_latest_and_archive(self):
        explanation_dataset = _load_dataset(_EXPLANATION_DATASET)
        answer_dataset       = _load_dataset(_ANSWER_DATASET)
        explanation_results  = [_run_explanation_case(explanation_dataset["cases"][0])]
        answer_results        = [_run_answer_case(answer_dataset["cases"][0])]
        report = _build_report(explanation_results, answer_results, explanation_dataset, answer_dataset, 1.0)

        latest, archive = _write_report(report, no_archive=False)
        self.assertTrue(latest.exists())
        self.assertIsNotNone(archive)
        self.assertTrue(archive.exists())
        loaded = json.loads(latest.read_text())
        self.assertEqual(loaded["summary"]["total_cases"], 2)


class TestFeatureFlagAndFallback(unittest.TestCase):
    def test_disabled_flag_means_no_explanation_attached(self):
        """Direct check on the underlying function (not the runner, which
        always force-enables the flag) — confirms the disabled-by-default
        behavior the runner's mocking deliberately bypasses still works."""
        from unittest.mock import patch
        import agents.recommendation_explainer as explainer
        matches = [{"program_id": "x", "confidence": "high", "score_basis": ["interest_1:nursing"]}]
        with patch.object(explainer, "_ENABLED", False):
            explainer.attach_explanations(matches)
        self.assertNotIn("explanation", matches[0])

    def test_connection_error_never_raises_through_full_eval_case(self):
        case = {
            "case_id": "T-NORAISE",
            "program_match": {"program_id": "x", "confidence": "high", "score_basis": ["interest_1:nursing"]},
            "simulate": {"mode": "connection_error"},
            "expected_evidence_phrases": [],
            "forbidden_phrases": [],
            "expected_outcome": "no_explanation_graceful_fallback",
        }
        try:
            _run_explanation_case(case)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
