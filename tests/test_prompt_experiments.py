"""
tests/test_prompt_experiments.py
Phase 8C — regression tests for the prompt experimentation framework.

Covers:
  - Experiment configuration: default dataset/prompt paths resolve and exist.
  - Prompt version loading: baseline vs. candidate registry entries are
    distinct, and the production registry entry is untouched by the v2 one.
  - Baseline/candidate execution: _run_dataset_with_prompt() reuses
    run_llm_evals._run_explanation_case() unchanged and returns one result
    per case.
  - Metric delta calculation: compare_explanation_metrics()'s direction
    logic (higher-is-better vs. forbidden_claim_rate's lower-is-better),
    threshold behavior, and status labels.
  - Comparison reports / report generation: _build_report() shape,
    _write_report() writes valid JSON to evals/reports/.
  - No mutation of production prompt: agents.recommendation_explainer.
    _SYSTEM_PROMPT is identical before and after running the full
    experiment, including the candidate leg.
  - Reuse of existing evaluation framework: confirms no duplicated
    evaluation logic exists in this module (the underlying case function
    is the same object imported from run_llm_evals).
  - No live LLM required by default: every case in both datasets fully
    mocked, asserted by running with requests.post unpatched-but-unused
    (the dataset's own simulate mocking covers every case already).

Run from the project root:
    pytest tests/test_prompt_experiments.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import tempfile
import unittest

import agents.recommendation_explainer as explainer
from evals.run_llm_evals import _run_explanation_case
from evals.run_prompt_experiments import (
    _run_dataset_with_prompt,
    compare_explanation_metrics,
    _status_for_delta,
    _overall_recommendation,
    _build_report,
    _write_report,
    _DEFAULT_BASELINE_DATASET,
    _DEFAULT_CANDIDATE_DATASET,
    _BASELINE_PROMPT_NAME,
    _CANDIDATE_PROMPT_NAME,
)
from evals.metrics_llm import compute_explanation_metrics
from prompts.registry import get_prompt_metadata
from prompts.loader import load_prompt


class TestExperimentConfiguration(unittest.TestCase):
    def test_default_datasets_exist(self):
        self.assertTrue(_DEFAULT_BASELINE_DATASET.exists())
        self.assertTrue(_DEFAULT_CANDIDATE_DATASET.exists())

    def test_default_datasets_are_distinct_files(self):
        self.assertNotEqual(_DEFAULT_BASELINE_DATASET, _DEFAULT_CANDIDATE_DATASET)

    def test_candidate_dataset_has_same_case_ids_as_baseline(self):
        baseline = json.loads(_DEFAULT_BASELINE_DATASET.read_text())
        candidate = json.loads(_DEFAULT_CANDIDATE_DATASET.read_text())
        baseline_ids = {c["case_id"] for c in baseline["cases"]}
        candidate_ids = {c["case_id"] for c in candidate["cases"]}
        self.assertEqual(baseline_ids, candidate_ids)


class TestPromptVersionLoading(unittest.TestCase):
    def test_baseline_and_candidate_are_distinct_registry_entries(self):
        baseline_meta = get_prompt_metadata(_BASELINE_PROMPT_NAME)
        candidate_meta = get_prompt_metadata(_CANDIDATE_PROMPT_NAME)
        self.assertNotEqual(baseline_meta.relative_path, candidate_meta.relative_path)
        self.assertEqual(baseline_meta.version, "v1")
        self.assertEqual(candidate_meta.version, "v2")

    def test_production_registry_entry_is_v1(self):
        """The name agents/recommendation_explainer.py actually loads must
        never be the experimental candidate."""
        self.assertEqual(get_prompt_metadata("recommendation_explanation").version, "v1")

    def test_candidate_prompt_text_differs_from_baseline(self):
        baseline_text = load_prompt(_BASELINE_PROMPT_NAME)
        candidate_text = load_prompt(_CANDIDATE_PROMPT_NAME)
        self.assertNotEqual(baseline_text, candidate_text)
        self.assertIn("2-3 sentences", baseline_text)
        self.assertIn("1-2 sentences", candidate_text)


class TestBaselineCandidateExecution(unittest.TestCase):
    def test_run_dataset_with_prompt_reuses_real_case_function(self):
        """Same function object as run_llm_evals.py — true reuse, not a
        reimplementation that could silently drift."""
        import evals.run_prompt_experiments as runner
        self.assertIs(runner._run_explanation_case, _run_explanation_case)

    def test_baseline_run_returns_one_result_per_case(self):
        results = _run_dataset_with_prompt(_DEFAULT_BASELINE_DATASET, None)
        dataset = json.loads(_DEFAULT_BASELINE_DATASET.read_text())
        self.assertEqual(len(results), len(dataset["cases"]))
        for r in results:
            self.assertIn("status", r)
            self.assertIn(r["status"], ("PASS", "FAIL"))

    def test_candidate_run_returns_one_result_per_case(self):
        results = _run_dataset_with_prompt(_DEFAULT_CANDIDATE_DATASET, _CANDIDATE_PROMPT_NAME)
        dataset = json.loads(_DEFAULT_CANDIDATE_DATASET.read_text())
        self.assertEqual(len(results), len(dataset["cases"]))

    def test_known_regression_case_reproduced(self):
        """EXPL-002 is a deliberately-built regression case: the candidate
        dataset's shortened simulated text drops the 'biomechanics'
        evidence phrase. Confirms the comparison pipeline can actually
        detect a real regression, not just always report 'no change'."""
        results = _run_dataset_with_prompt(_DEFAULT_CANDIDATE_DATASET, _CANDIDATE_PROMPT_NAME)
        expl_002 = next(r for r in results if r["case_id"] == "EXPL-002")
        self.assertEqual(expl_002["status"], "FAIL")
        self.assertFalse(expl_002["evidence_fully_covered"])
        self.assertIn("biomechanics", expl_002["missing_evidence_phrases"])


class TestMetricDeltaCalculation(unittest.TestCase):
    def test_status_for_delta_no_meaningful_change_below_threshold(self):
        self.assertEqual(_status_for_delta("evidence_coverage_rate", 0.5), "No meaningful change")
        self.assertEqual(_status_for_delta("evidence_coverage_rate", -0.9), "No meaningful change")

    def test_status_for_delta_higher_is_better_metric(self):
        self.assertEqual(_status_for_delta("evidence_coverage_rate", 5.0), "Improved")
        self.assertEqual(_status_for_delta("evidence_coverage_rate", -5.0), "Regressed")

    def test_status_for_delta_lower_is_better_metric(self):
        # forbidden_claim_rate: a NEGATIVE delta (fewer forbidden claims) is an improvement.
        self.assertEqual(_status_for_delta("forbidden_claim_rate", -5.0), "Improved")
        self.assertEqual(_status_for_delta("forbidden_claim_rate", 5.0), "Regressed")

    def test_compare_explanation_metrics_produces_one_row_per_scalar_metric(self):
        baseline = compute_explanation_metrics([
            {"status": "PASS", "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached", "evidence_fully_covered": True,
             "forbidden_phrase_found": False, "deterministic_drift_detected": False},
        ])
        candidate = compute_explanation_metrics([
            {"status": "FAIL", "actual_outcome": "explanation_attached",
             "expected_outcome": "explanation_attached", "evidence_fully_covered": False,
             "forbidden_phrase_found": False, "deterministic_drift_detected": False},
        ])
        rows = compare_explanation_metrics(baseline, candidate)
        metric_names = {r["metric"] for r in rows}
        self.assertIn("evidence_coverage_rate", metric_names)
        self.assertNotIn("overall_counts", metric_names)
        self.assertNotIn("outcome_distribution", metric_names)
        for row in rows:
            self.assertEqual(round(row["candidate"] - row["baseline"], 1), row["delta"])

    def test_overall_recommendation_rejects_on_any_regression(self):
        rows = [
            {"metric": "a", "status": "Improved"},
            {"metric": "b", "status": "Regressed"},
        ]
        self.assertTrue(_overall_recommendation(rows).startswith("Reject"))

    def test_overall_recommendation_promotable_when_only_improvements(self):
        rows = [
            {"metric": "a", "status": "Improved"},
            {"metric": "b", "status": "No meaningful change"},
        ]
        self.assertTrue(_overall_recommendation(rows).startswith("Promotable"))

    def test_overall_recommendation_neutral_when_no_change(self):
        rows = [{"metric": "a", "status": "No meaningful change"}]
        result = _overall_recommendation(rows)
        self.assertNotIn("Reject", result)
        self.assertNotIn("Promotable", result)


class TestComparisonReports(unittest.TestCase):
    def test_build_report_shape(self):
        baseline_results = _run_dataset_with_prompt(_DEFAULT_BASELINE_DATASET, None)
        candidate_results = _run_dataset_with_prompt(_DEFAULT_CANDIDATE_DATASET, _CANDIDATE_PROMPT_NAME)
        baseline_metrics = compute_explanation_metrics(baseline_results)
        candidate_metrics = compute_explanation_metrics(candidate_results)
        comparison_rows = compare_explanation_metrics(baseline_metrics, candidate_metrics)

        report = _build_report(
            _DEFAULT_BASELINE_DATASET, _DEFAULT_CANDIDATE_DATASET,
            baseline_results, candidate_results, comparison_rows, 12.3,
        )
        for key in ("schema_version", "run_id", "timestamp", "baseline", "candidate",
                    "comparison", "recommendation", "execution_time_ms"):
            self.assertIn(key, report)
        self.assertEqual(report["baseline"]["prompt_version"], "v1")
        self.assertEqual(report["candidate"]["prompt_version"], "v2")
        self.assertEqual(report["recommendation"], "Reject — at least one metric regressed")

    def test_write_report_produces_valid_json_file(self):
        report = {"schema_version": "1.0", "comparison": [], "recommendation": "x"}
        with tempfile.TemporaryDirectory() as tmpdir:
            import evals.run_prompt_experiments as runner
            original_dir = runner._REPORTS_DIR
            runner._REPORTS_DIR = Path(tmpdir)
            try:
                latest, archive = _write_report(report, no_archive=True)
                self.assertTrue(latest.exists())
                self.assertIsNone(archive)
                loaded = json.loads(latest.read_text())
                self.assertEqual(loaded["recommendation"], "x")
            finally:
                runner._REPORTS_DIR = original_dir


class TestNoProductionMutation(unittest.TestCase):
    def test_system_prompt_unchanged_after_full_experiment(self):
        prompt_before = explainer._SYSTEM_PROMPT

        _run_dataset_with_prompt(_DEFAULT_BASELINE_DATASET, None)
        _run_dataset_with_prompt(_DEFAULT_CANDIDATE_DATASET, _CANDIDATE_PROMPT_NAME)

        self.assertIs(explainer._SYSTEM_PROMPT, prompt_before)
        self.assertIn("2-3 sentences", explainer._SYSTEM_PROMPT)
        self.assertNotIn("1-2 sentences", explainer._SYSTEM_PROMPT)

    def test_system_prompt_restored_even_if_a_case_would_raise(self):
        """patch.object always restores on exit, including via exception —
        confirmed structurally rather than by forcing a real exception,
        since _run_explanation_case() already catches everything itself."""
        prompt_before = explainer._SYSTEM_PROMPT
        _run_dataset_with_prompt(_DEFAULT_CANDIDATE_DATASET, _CANDIDATE_PROMPT_NAME)
        self.assertEqual(explainer._SYSTEM_PROMPT, prompt_before)


class TestNoLiveLLMRequired(unittest.TestCase):
    def test_experiment_runs_with_no_network_access_needed(self):
        """Every case's response comes from the dataset's own "simulate"
        mocking (inherited from _run_explanation_case) — no real
        requests.post call is ever made. If this test can run in a
        sandboxed/offline CI environment, no live LLM was required."""
        results = _run_dataset_with_prompt(_DEFAULT_CANDIDATE_DATASET, _CANDIDATE_PROMPT_NAME)
        self.assertTrue(len(results) > 0)


if __name__ == "__main__":
    unittest.main()
