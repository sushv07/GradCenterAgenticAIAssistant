"""
tests/test_recommendation_explainer.py
Phase 7B — regression tests for LLM-generated recommendation explanations.

Covers:
  - score_basis parsing into evidence categories (including the
    orientation_mismatch exclusion).
  - attach_explanations(): disabled (default) is a true no-op; enabled +
    success attaches "explanation" without touching any other field;
    enabled + failure/retry-exhaustion degrades to the exact same response
    as disabled.
  - Recommendation ranking, scores, and every ProgramMatch field other than
    "explanation" are identical regardless of whether the LLM is enabled,
    disabled, or fails.
  - No evidence -> no explanation generated (nothing to explain).
  - Full handle_discovery() integration: disabled-by-default, enabled
    end-to-end, and failure end-to-end.

Run from the project root:
    pytest tests/test_recommendation_explainer.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import unittest
from unittest.mock import patch, MagicMock

import requests

import agents.recommendation_explainer as explainer
from agents.recommendation_explainer import (
    attach_explanations,
    _parse_score_basis,
    _has_any_evidence,
)
from agents.journey_agent import handle_discovery
from state.context_manager import clear_context


def _fresh(sid: str) -> None:
    clear_context(sid)


def _fake_ollama_response(explanation: str):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message": {"content": json.dumps({"explanation": explanation})}}
    return resp


class TestScoreBasisParsing(unittest.TestCase):
    def test_degree_type(self):
        evidence = _parse_score_basis(["degree_type"])
        self.assertTrue(evidence["matched_degree"])

    def test_unique_and_shared_career(self):
        evidence = _parse_score_basis(["unique_career:nurse_practitioner", "shared_career:clinician"])
        self.assertEqual(set(evidence["matched_career_goals"]), {"nurse_practitioner", "clinician"})

    def test_interest_1(self):
        evidence = _parse_score_basis(["interest_1:nursing"])
        self.assertEqual(evidence["matched_interests"], ["nursing"])

    def test_interests_2_and_3plus_comma_split(self):
        evidence = _parse_score_basis(["interests_2:nursing,pediatric_care"])
        self.assertEqual(evidence["matched_interests"], ["nursing", "pediatric_care"])

    def test_background_1_and_2plus(self):
        evidence = _parse_score_basis(["background_2plus:nursing,clinical_rn_experience"])
        self.assertEqual(evidence["matched_background"], ["nursing", "clinical_rn_experience"])

    def test_orientation_match_true(self):
        evidence = _parse_score_basis(["orientation_match:research"])
        self.assertTrue(evidence["orientation_match"])

    def test_orientation_mismatch_excluded_entirely(self):
        """A mismatch is a penalty, not supporting evidence for 'why this fits'."""
        evidence = _parse_score_basis(["orientation_mismatch:research!=applied"])
        self.assertFalse(evidence["orientation_match"])
        self.assertFalse(_has_any_evidence(evidence))

    def test_empty_score_basis_has_no_evidence(self):
        evidence = _parse_score_basis([])
        self.assertFalse(_has_any_evidence(evidence))

    def test_combined_real_example(self):
        evidence = _parse_score_basis(["unique_career:nurse_practitioner", "interest_1:nursing"])
        self.assertTrue(_has_any_evidence(evidence))
        self.assertEqual(evidence["matched_career_goals"], ["nurse_practitioner"])
        self.assertEqual(evidence["matched_interests"], ["nursing"])
        self.assertFalse(evidence["matched_degree"])


class TestAttachExplanationsDisabledByDefault(unittest.TestCase):
    def test_disabled_is_a_true_noop(self):
        matches = [{"program_id": "dnp-nursing", "confidence": "high",
                    "score_basis": ["unique_career:nurse_practitioner"]}]
        original = [dict(m) for m in matches]
        with patch.object(explainer, "_ENABLED", False):
            attach_explanations(matches)
        self.assertEqual(matches, original)
        self.assertNotIn("explanation", matches[0])

    def test_empty_list_is_safe(self):
        with patch.object(explainer, "_ENABLED", True):
            attach_explanations([])  # must not raise


class TestAttachExplanationsEnabled(unittest.TestCase):
    def test_success_adds_explanation_only(self):
        matches = [{"program_id": "dnp-nursing", "confidence": "high",
                    "score_basis": ["unique_career:nurse_practitioner"],
                    "advisor_email": "a@csulb.edu", "deadline_fall": "Jan 15"}]
        original_other_fields = {k: v for k, v in matches[0].items()}

        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", return_value=_fake_ollama_response("Great fit.")):
            attach_explanations(matches)

        self.assertEqual(matches[0]["explanation"], "Great fit.")
        for k, v in original_other_fields.items():
            self.assertEqual(matches[0][k], v)

    def test_no_evidence_skips_generation_entirely(self):
        matches = [{"program_id": "x", "confidence": "none", "score_basis": []}]
        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post") as mock_post:
            attach_explanations(matches)
        mock_post.assert_not_called()
        self.assertNotIn("explanation", matches[0])

    def test_failure_leaves_match_unchanged(self):
        matches = [{"program_id": "dnp-nursing", "confidence": "high",
                     "score_basis": ["unique_career:nurse_practitioner"]}]
        original = [dict(m) for m in matches]
        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", side_effect=requests.exceptions.ConnectionError("down")), \
             patch("utils.retry.time.sleep"):
            attach_explanations(matches)
        self.assertEqual(matches, original)
        self.assertNotIn("explanation", matches[0])

    def test_retry_exhaustion_does_not_raise(self):
        matches = [{"program_id": "dnp-nursing", "confidence": "high",
                     "score_basis": ["interest_1:nursing"]}]
        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", side_effect=requests.exceptions.Timeout("slow")), \
             patch("utils.retry.time.sleep"):
            attach_explanations(matches)  # must not raise
        self.assertNotIn("explanation", matches[0])

    def test_invalid_json_response_leaves_match_unchanged(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"content": "not json"}}
        matches = [{"program_id": "dnp-nursing", "confidence": "high",
                     "score_basis": ["interest_1:nursing"]}]
        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", return_value=resp):
            attach_explanations(matches)
        self.assertNotIn("explanation", matches[0])


class TestEndToEndIntegration(unittest.TestCase):
    """Full handle_discovery() pipeline — the level Phase 7B cares about."""

    def test_disabled_by_default_matches_pre_phase_7b_shape(self):
        sid = "e2e-explain-disabled"
        _fresh(sid)
        r, _ = handle_discovery("I want to become a nurse practitioner", sid)
        pm = r["program_matches"][0]
        self.assertNotIn("explanation", pm)
        _fresh(sid)

    def test_enabled_attaches_explanation_end_to_end(self):
        sid = "e2e-explain-enabled"
        _fresh(sid)
        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", return_value=_fake_ollama_response("Matches your nursing goals.")):
            r, _ = handle_discovery("I want to become a nurse practitioner", sid)
        pm = r["program_matches"][0]
        self.assertEqual(pm["explanation"], "Matches your nursing goals.")
        _fresh(sid)

    def test_recommendation_identical_whether_llm_enabled_disabled_or_failing(self):
        """The core Phase 7B guarantee: ranking/scores/ProgramMatch fields
        never change based on LLM availability."""
        sid_disabled = "e2e-compare-disabled"
        sid_enabled  = "e2e-compare-enabled"
        sid_failing  = "e2e-compare-failing"
        for sid in (sid_disabled, sid_enabled, sid_failing):
            _fresh(sid)

        r_disabled, _ = handle_discovery("I want to become a nurse practitioner", sid_disabled)

        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", return_value=_fake_ollama_response("x")):
            r_enabled, _ = handle_discovery("I want to become a nurse practitioner", sid_enabled)

        with patch.object(explainer, "_ENABLED", True), \
             patch("requests.post", side_effect=requests.exceptions.ConnectionError("down")), \
             patch("utils.retry.time.sleep"):
            r_failing, _ = handle_discovery("I want to become a nurse practitioner", sid_failing)

        for key in ("route", "behavior", "confidence", "recommended_programs"):
            self.assertEqual(r_disabled[key], r_enabled[key], key)
            self.assertEqual(r_disabled[key], r_failing[key], key)

        for field in ("program_id", "confidence", "score_basis", "advisor_email", "deadline_fall"):
            self.assertEqual(
                r_disabled["program_matches"][0][field],
                r_enabled["program_matches"][0][field],
                field,
            )
            self.assertEqual(
                r_disabled["program_matches"][0][field],
                r_failing["program_matches"][0][field],
                field,
            )

        self.assertNotIn("explanation", r_disabled["program_matches"][0])
        self.assertIn("explanation", r_enabled["program_matches"][0])
        self.assertNotIn("explanation", r_failing["program_matches"][0])

        for sid in (sid_disabled, sid_enabled, sid_failing):
            _fresh(sid)


if __name__ == "__main__":
    unittest.main()
