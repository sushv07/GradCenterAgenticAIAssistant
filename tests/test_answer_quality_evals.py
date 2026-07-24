"""
tests/test_answer_quality_evals.py
Phase 10 — answer-quality metrics + eval runner (offline, deterministic).

Covers the metric primitives (grounding, citation correctness, verbosity,
repetition, abstention, clarification), the case evaluator's expectation gates,
and the golden-set runner. Pure functions over strings — no LLM, no network.

Run: pytest tests/test_answer_quality_evals.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.metrics_answer_quality import (
    abstains, abstains_cleanly, asks_clarification, citation_correctness,
    evaluate_case, grounding_rate, repetition_rate, score_answer, verbosity,
)
from evals.run_answer_quality_evals import load_cases, run

EV = ("Applicants must submit a completed Cal State Apply application, official "
      "transcripts, a statement of purpose, and two letters of recommendation. "
      "A minimum cumulative GPA of 3.0 is required. "
      "See https://www.csulb.edu/admissions for details.")


class TestGrounding(unittest.TestCase):
    def test_grounded_answer_scores_high(self):
        ans = ("Submit a Cal State Apply application, official transcripts, a "
               "statement of purpose, and two letters of recommendation.")
        self.assertGreaterEqual(grounding_rate(ans, EV), 0.9)

    def test_fabricated_fact_scores_low(self):
        # a sentence with facts absent from the evidence is ungrounded
        ans = "The average starting salary is 65000 dollars per year nationwide."
        self.assertEqual(grounding_rate(ans, EV), 0.0)

    def test_empty_answer_is_vacuously_grounded(self):
        self.assertEqual(grounding_rate("", EV), 1.0)


class TestCitation(unittest.TestCase):
    def test_real_url_ok(self):
        c = citation_correctness("See https://www.csulb.edu/admissions here.", EV)
        self.assertTrue(c["fidelity_ok"])
        self.assertTrue(c["attribution_ok"])
        self.assertEqual(c["hallucinated_url_count"], 0)

    def test_fabricated_url_flagged(self):
        c = citation_correctness("See https://www.csulb.edu/made-up-page.", EV)
        self.assertFalse(c["fidelity_ok"])
        self.assertEqual(c["hallucinated_urls"],
                         ["https://www.csulb.edu/made-up-page"])

    def test_trailing_punctuation_not_fabrication(self):
        # a correctly-copied URL ending a sentence must not read as fabricated
        c = citation_correctness("Details: https://www.csulb.edu/admissions.", EV)
        self.assertTrue(c["fidelity_ok"])

    def test_attribution_missing_when_no_url_cited(self):
        c = citation_correctness("The GPA minimum is 3.0.", EV)
        self.assertTrue(c["fidelity_ok"])          # cited nothing false
        self.assertFalse(c["attribution_ok"])       # but evidence had a URL


class TestVerbosityRepetitionSignals(unittest.TestCase):
    def test_verbosity_counts(self):
        v = verbosity("One fact. Two facts.")
        self.assertEqual(v["sentences"], 2)
        self.assertGreater(v["chars"], 0)

    def test_repetition_detects_restated_sentence(self):
        dup = "The deadline is March 1. The deadline is March 1."
        self.assertGreater(repetition_rate(dup), 0.0)
        self.assertEqual(repetition_rate("The deadline is March 1."), 0.0)

    def test_abstention_and_clean_abstention(self):
        self.assertTrue(abstains("That information is not available in the pages."))
        self.assertTrue(abstains_cleanly(
            "That information is not available in the provided pages."))
        # abstains but also asserts a fabricated specific -> not clean
        self.assertFalse(abstains_cleanly(
            "Not available, but it's probably around $65,000."))

    def test_clarification_detected(self):
        self.assertTrue(asks_clarification("Which program — the MA or the MFA?"))
        self.assertFalse(asks_clarification("The deadline is March 1."))


class TestEvaluateCase(unittest.TestCase):
    def _case(self, answer, expect):
        return {"case_id": "T", "category": "c", "query": "q",
                "retrieved_evidence": EV,
                "baseline_answer": answer, "candidate_answer": answer,
                "expect": expect}

    def test_must_contain_gate(self):
        c = self._case("The minimum GPA is 3.0.", {"must_contain": ["3.0"]})
        self.assertTrue(evaluate_case(c, "candidate")["passed"])
        c2 = self._case("No number here.", {"must_contain": ["3.0"]})
        r = evaluate_case(c2, "candidate")
        self.assertFalse(r["passed"])
        self.assertIn("missing required text", r["failures"][0])

    def test_grounding_and_verbosity_gates(self):
        c = self._case("The average salary is 65000 dollars.",
                       {"min_grounding": 0.8, "max_chars": 10})
        r = evaluate_case(c, "candidate")
        self.assertFalse(r["passed"])
        self.assertEqual(len(r["failures"]), 2)     # grounding AND chars


class TestGoldenRunner(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases()
        self.outcome = run(self.cases)

    def test_seven_categories_present(self):
        cats = {c["category"] for c in self.cases}
        for required in ("admissions", "eligibility", "deadlines",
                         "program_specific", "advisor", "unknown", "ambiguous"):
            self.assertIn(required, cats)

    def test_candidate_passes_all_expectations(self):
        self.assertEqual(self.outcome["candidate_summary"]["passed"],
                         len(self.cases))

    def test_candidate_beats_baseline_on_quality(self):
        b = self.outcome["baseline_summary"]
        c = self.outcome["candidate_summary"]
        self.assertGreater(c["mean_grounding"], b["mean_grounding"])
        self.assertLess(c["mean_chars"], b["mean_chars"])
        self.assertLessEqual(c["mean_repetition"], b["mean_repetition"])

    def test_no_hallucinated_urls_either_variant(self):
        # fixtures never fabricate URLs (fabrication is caught by the metric,
        # tested above); guards against a typo introducing one
        self.assertEqual(self.outcome["baseline_summary"]["hallucinated_url_total"], 0)
        self.assertEqual(self.outcome["candidate_summary"]["hallucinated_url_total"], 0)

    def test_deterministic(self):
        again = run(self.cases)
        self.assertEqual(again["candidate_summary"], self.outcome["candidate_summary"])


if __name__ == "__main__":
    unittest.main()
