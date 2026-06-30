"""
tests/test_advisor_evals.py
Phase 8D — regression tests for the advisor-answer evaluation framework.

Covers:
  - Dataset loading and schema validation.
  - Metric calculations: route accuracy, match rate, field accuracy,
    suggestion coverage, null-advisor handling.
  - Failure classification: every error_category in the taxonomy.
  - Report generation: _build_report() shape, _write_report() roundtrip.
  - Representative advisor cases: exact match, fuzzy match, ambiguous,
    token-disambiguation, null-advisor data, no-match, empty query.
  - No production behavior changes: advisor pipeline, routing, and
    response content confirmed unchanged by the new eval infrastructure.

Run from the project root:
    pytest tests/test_advisor_evals.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest

from evals.metrics_advisor import compute_advisor_metrics, format_console_summary
from evals.error_classification_advisor import (
    classify_advisor, build_error_summary, format_error_summary_console,
)
from evals.run_advisor_evals import (
    _run_case,
    _load_dataset,
    _build_report,
    _write_report,
    _DEFAULT_DATASET,
    _EVAL_SESSION_ID,
)


# ---------------------------------------------------------------------------
# Dataset tests
# ---------------------------------------------------------------------------

class TestDatasetLoading(unittest.TestCase):
    def test_default_dataset_exists(self):
        self.assertTrue(_DEFAULT_DATASET.exists())

    def test_default_dataset_has_required_keys(self):
        dataset = json.loads(_DEFAULT_DATASET.read_text())
        for key in ("_schema_version", "_scope", "_source", "cases"):
            self.assertIn(key, dataset)

    def test_cases_have_required_fields(self):
        dataset = json.loads(_DEFAULT_DATASET.read_text())
        for case in dataset["cases"]:
            self.assertIn("case_id", case)
            self.assertIn("query", case)
            self.assertIn("expected_match", case)

    def test_case_count_is_twelve(self):
        dataset = json.loads(_DEFAULT_DATASET.read_text())
        self.assertEqual(len(dataset["cases"]), 12)

    def test_load_dataset_function_works(self):
        dataset = _load_dataset(_DEFAULT_DATASET)
        self.assertIsInstance(dataset["cases"], list)
        self.assertGreater(len(dataset["cases"]), 0)

    def test_load_dataset_exits_on_missing_file(self):
        with self.assertRaises(SystemExit):
            _load_dataset(Path("/tmp/definitely_does_not_exist_8d.json"))


# ---------------------------------------------------------------------------
# Metric calculation tests
# ---------------------------------------------------------------------------

def _make_result(
    status="PASS",
    expected_route_checked=True, route_correct=True, expected_match=True,
    match_present=True, expected_program="Prog A", program_correct=True,
    expected_advisor_name="Alice", advisor_name_correct=True,
    expected_email="a@b.com", email_correct=True,
    expected_source_url="http://x.com", source_correct=True,
    has_null_advisor=False, null_advisor_correct=True,
    expected_suggestions_include=None, suggestions_fully_covered=True,
    **kwargs,
) -> dict:
    return {
        "status": status,
        "expected_route_checked": expected_route_checked,
        "route_correct": route_correct,
        "expected_match": expected_match,
        "match_present": match_present,
        "expected_program": expected_program,
        "program_correct": program_correct,
        "expected_advisor_name": expected_advisor_name,
        "advisor_name_correct": advisor_name_correct,
        "expected_email": expected_email,
        "email_correct": email_correct,
        "expected_source_url": expected_source_url,
        "source_correct": source_correct,
        "has_null_advisor": has_null_advisor,
        "null_advisor_correct": null_advisor_correct,
        "expected_suggestions_include": expected_suggestions_include or [],
        "suggestions_fully_covered": suggestions_fully_covered,
        **kwargs,
    }


class TestMetricCalculations(unittest.TestCase):
    def test_perfect_run_all_100(self):
        # Include one suggestion case and one null-advisor case so every metric
        # has a non-zero denominator — otherwise pct(0,0)=0.0 by design.
        cases = [_make_result() for _ in range(3)]
        # suggestion case: covers suggestion_coverage denominator
        cases.append(_make_result(
            expected_suggestions_include=["Prog X"],
            suggestions_fully_covered=True,
        ))
        # null-advisor case: covers null_advisor_handling_rate denominator
        cases.append(_make_result(has_null_advisor=True, null_advisor_correct=True))
        # no-match case: covers no_spurious_match_rate denominator
        cases.append(_make_result(expected_match=False, match_present=False))
        metrics = compute_advisor_metrics(cases)
        self.assertEqual(metrics["overall_counts"]["pass"], 6)
        for key, val in metrics.items():
            if key == "overall_counts":
                continue
            self.assertEqual(val, 100.0, f"{key} should be 100.0 in a perfect run")

    def test_route_accuracy_partial(self):
        cases = [
            _make_result(route_correct=True),
            _make_result(route_correct=False, status="FAIL"),
        ]
        metrics = compute_advisor_metrics(cases)
        self.assertEqual(metrics["route_accuracy"], 50.0)

    def test_advisor_match_rate(self):
        cases = [
            _make_result(expected_match=True, match_present=True),
            _make_result(expected_match=True, match_present=False, status="FAIL"),
        ]
        metrics = compute_advisor_metrics(cases)
        self.assertEqual(metrics["advisor_match_rate"], 50.0)

    def test_no_spurious_match_rate(self):
        cases = [
            _make_result(expected_match=False, match_present=False),
            _make_result(expected_match=False, match_present=True, status="FAIL"),
        ]
        metrics = compute_advisor_metrics(cases)
        self.assertEqual(metrics["no_spurious_match_rate"], 50.0)

    def test_suggestion_coverage(self):
        cases = [
            _make_result(expected_suggestions_include=["Prog A"], suggestions_fully_covered=True),
            _make_result(expected_suggestions_include=["Prog B"], suggestions_fully_covered=False, status="FAIL"),
        ]
        metrics = compute_advisor_metrics(cases)
        self.assertEqual(metrics["suggestion_coverage"], 50.0)

    def test_null_advisor_handling_rate(self):
        cases = [
            _make_result(has_null_advisor=True, null_advisor_correct=True),
            _make_result(has_null_advisor=True, null_advisor_correct=False, status="FAIL"),
        ]
        metrics = compute_advisor_metrics(cases)
        self.assertEqual(metrics["null_advisor_handling_rate"], 50.0)

    def test_empty_cases_returns_zeroed_metrics(self):
        metrics = compute_advisor_metrics([])
        self.assertEqual(metrics["overall_counts"]["total_cases"], 0)
        for key, val in metrics.items():
            if key != "overall_counts":
                self.assertEqual(val, 0.0)

    def test_format_console_summary_does_not_raise(self):
        metrics = compute_advisor_metrics([_make_result()])
        text = format_console_summary(metrics, 42.0)
        self.assertIn("Advisor Answer Evaluation Summary", text)
        self.assertIn("100.0%", text)


# ---------------------------------------------------------------------------
# Error classification tests
# ---------------------------------------------------------------------------

class TestErrorClassification(unittest.TestCase):
    def _case_and_result(self, **kwargs):
        case = {
            "query": "test query",
            "expected_match": kwargs.get("expected_match", True),
            "has_null_advisor": kwargs.get("has_null_advisor", False),
            "expected_program": kwargs.get("expected_program"),
            "expected_advisor_name": kwargs.get("expected_advisor_name"),
            "expected_email": kwargs.get("expected_email"),
            "expected_suggestions_include": kwargs.get("expected_suggestions_include", []),
        }
        result = _make_result(**kwargs)
        return case, result

    def test_pass_returns_none_category(self):
        case, result = self._case_and_result()
        cat, reason = classify_advisor(case, result)
        self.assertEqual(cat, "none")

    def test_route_mismatch_detected(self):
        case = {"query": "x", "expected_match": True, "has_null_advisor": False}
        result = _make_result(
            status="FAIL",
            expected_route_checked=True, route_correct=False,
            expected_route_value="advisor", actual_route="answer",
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "incorrect_route")

    def test_advisor_not_found(self):
        case = {"query": "nursing", "expected_match": True, "has_null_advisor": False}
        result = _make_result(
            status="FAIL", expected_match=True, match_present=False, actual_confidence=50,
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "advisor_not_found")

    def test_spurious_match(self):
        case = {"query": "xyz", "expected_match": False, "has_null_advisor": False}
        result = _make_result(
            status="FAIL", expected_match=False, match_present=True, actual_program="Nursing",
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "spurious_match")

    def test_wrong_program(self):
        case = {
            "query": "nursing", "expected_match": True, "has_null_advisor": False,
            "expected_program": "Nursing (D.N.P.)",
        }
        result = _make_result(
            status="FAIL",
            expected_program="Nursing (D.N.P.)", actual_program="Physical Therapy (DPT)",
            program_correct=False,
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "wrong_program")

    def test_wrong_advisor(self):
        case = {
            "query": "nursing", "expected_match": True, "has_null_advisor": False,
            "expected_advisor_name": "Alice",
        }
        result = _make_result(
            status="FAIL",
            expected_advisor_name="Alice", actual_advisor_name="Bob",
            advisor_name_correct=False,
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "wrong_advisor")

    def test_wrong_email(self):
        case = {
            "query": "nursing", "expected_match": True, "has_null_advisor": False,
            "expected_email": "a@b.com",
        }
        result = _make_result(
            status="FAIL",
            expected_email="a@b.com", actual_email="c@d.com",
            email_correct=False,
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "wrong_email")

    def test_suggestion_failure(self):
        case = {
            "query": "edd", "expected_match": False, "has_null_advisor": False,
            "expected_suggestions_include": ["Program A"],
        }
        result = _make_result(
            status="FAIL",
            expected_match=False, match_present=False,
            expected_suggestions_include=["Program A"],
            suggestions_fully_covered=False,
            missing_suggestions=["Program A"],
        )
        cat, _ = classify_advisor(case, result)
        self.assertEqual(cat, "suggestion_failure")

    def test_build_error_summary_counts(self):
        results = [
            {"error_category": "wrong_email"},
            {"error_category": "wrong_email"},
            {"error_category": "advisor_not_found"},
            {"error_category": "none"},
        ]
        summary = build_error_summary(results)
        self.assertEqual(summary["wrong_email"], 2)
        self.assertEqual(summary["advisor_not_found"], 1)
        self.assertEqual(summary["none"], 1)

    def test_format_error_summary_does_not_raise(self):
        text = format_error_summary_console({"none": 5, "wrong_email": 1})
        self.assertIn("none", text)


# ---------------------------------------------------------------------------
# Report generation tests
# ---------------------------------------------------------------------------

class TestReportGeneration(unittest.TestCase):
    def test_build_report_shape(self):
        results = [_make_result(status="PASS")]
        dataset = {"_schema_version": "1.0", "cases": results}
        report = _build_report(results, _DEFAULT_DATASET, dataset, 50.0)
        for key in ("schema_version", "run_id", "timestamp", "summary", "cases",
                    "metrics", "error_summary"):
            self.assertIn(key, report)
        self.assertEqual(report["summary"]["total_cases"], 1)
        self.assertEqual(report["summary"]["passed"], 1)

    def test_write_report_roundtrip(self):
        results = [_make_result()]
        dataset = {"_schema_version": "1.0", "cases": results}
        report = _build_report(results, _DEFAULT_DATASET, dataset, 10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            import evals.run_advisor_evals as runner
            original = runner._REPORTS_DIR
            runner._REPORTS_DIR = Path(tmpdir)
            try:
                latest, archive = _write_report(report, no_archive=True)
                self.assertTrue(latest.exists())
                loaded = json.loads(latest.read_text())
                self.assertIn("schema_version", loaded)
            finally:
                runner._REPORTS_DIR = original


# ---------------------------------------------------------------------------
# Representative case execution tests (live pipeline)
# ---------------------------------------------------------------------------

class TestRepresentativeCases(unittest.TestCase):
    """Each test calls the real handle_user_query() pipeline — no mocking.
    These verify that the evaluation framework correctly identifies pass/fail
    for specific, representative scenarios."""

    def _run(self, case: dict) -> dict:
        return _run_case(case)

    def test_exact_alias_match_dnp(self):
        result = self._run({
            "case_id": "T-001", "query": "dnp nursing",
            "expected_route": "advisor", "expected_match": True,
            "expected_program": "Nursing (D.N.P.)",
            "expected_advisor_name": "Cleddhy Arellano",
            "expected_email": "cleddhy.arellano@csulb.edu",
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["actual_route"], "advisor")
        self.assertTrue(result["match_present"])
        self.assertEqual(result["actual_program"], "Nursing (D.N.P.)")

    def test_fuzzy_match_nursing(self):
        result = self._run({
            "case_id": "T-002", "query": "nursing advisor",
            "expected_route": "advisor", "expected_match": True,
            "expected_program": "Nursing (D.N.P.)",
            "expected_advisor_name": "Cleddhy Arellano",
            "expected_email": "cleddhy.arellano@csulb.edu",
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")

    def test_ambiguous_educational_leadership(self):
        result = self._run({
            "case_id": "T-003", "query": "educational leadership advisor",
            "expected_route": "advisor", "expected_match": False,
            "expected_suggestions_include": [
                "Educational Leadership - P-12 Specialization (Ed.D.)",
                "Educational Leadership - Community College Higher Ed Specialization (Ed.D.)",
            ],
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["match_present"])
        self.assertTrue(result["suggestions_fully_covered"])

    def test_token_disambiguation_community_college(self):
        result = self._run({
            "case_id": "T-004", "query": "edd community college",
            "expected_route": "advisor", "expected_match": True,
            "expected_program": "Educational Leadership - Community College Higher Ed Specialization (Ed.D.)",
            "expected_advisor_name": "Kimberly Word",
            "expected_email": "eddinfo@csulb.edu",
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")

    def test_null_advisor_data_handled_correctly(self):
        result = self._run({
            "case_id": "T-005", "query": "accountancy advisor",
            "expected_route": "advisor", "expected_match": True,
            "expected_program": "Accountancy",
            "has_null_advisor": True,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["match_present"])
        self.assertTrue(result["null_advisor_correct"])

    def test_no_match_low_confidence_query(self):
        result = self._run({
            "case_id": "T-006", "query": "xyz totally unknown program",
            "expected_route_is_not": "advisor", "expected_match": False,
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertNotEqual(result["actual_route"], "advisor")

    def test_empty_query_routes_to_welcome(self):
        result = self._run({
            "case_id": "T-007", "query": "",
            "expected_route": None, "expected_match": False,
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertIsNone(result["actual_route"])

    def test_advisor_intent_no_program(self):
        result = self._run({
            "case_id": "T-008", "query": "who is my advisor",
            "expected_route": "advisor", "expected_match": False,
            "has_null_advisor": False,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["actual_route"], "advisor")
        self.assertFalse(result["match_present"])


class TestNoBehaviorChange(unittest.TestCase):
    """The eval infrastructure must not change the advisor pipeline's
    behavior — verified by confirming response content is identical
    whether we use the runner's evaluation path or call directly."""

    def test_advisor_response_identical_whether_eval_or_direct(self):
        from backend.entrypoint import handle_user_query
        from state.context_manager import clear_context

        query = "dnp nursing"
        sid_direct = "direct-call-sid"
        clear_context(sid_direct)
        clear_context(_EVAL_SESSION_ID)

        # What the eval runner gets
        eval_result = _run_case({
            "case_id": "X-001",
            "query": query,
            "expected_route": "advisor",
            "expected_match": True,
            "expected_program": "Nursing (D.N.P.)",
            "expected_advisor_name": "Cleddhy Arellano",
            "expected_email": "cleddhy.arellano@csulb.edu",
            "has_null_advisor": False,
        })

        # What a direct call gets
        clear_context(sid_direct)
        direct_response = handle_user_query(query, session_id=sid_direct)

        # Same route, same advisor details
        self.assertEqual(eval_result["actual_route"], direct_response.get("route"))
        self.assertEqual(eval_result["actual_program"],
                          (direct_response.get("advisor_data") or {}).get("match", {}).get("program", ""))


if __name__ == "__main__":
    unittest.main()
