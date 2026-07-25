"""
tests/test_program_continuity.py
Multi-turn program-context continuity through the REAL application path
(orchestrator.run + handle_discovery). Route tools are spied so the tests are
deterministic and offline: each spy records the query it received, proving the
orchestrator augments the internal tool query with the active program while the
user-facing query stays original.

Uses two different programs (DrPH and DPT) to prove the behavior is generic and
not hard-coded. Covers spec tests A–H.

Run: pytest tests/test_program_continuity.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from agents.journey_agent import handle_discovery
from state.context_manager import clear_context, get_context, save_context
from agents.journey_agent import init_journey_state

# Deterministic single-recommend discovery inputs (verified by existing
# test_student_interest a06/a07).
DRPH_DISCOVERY = "I want to address health disparities in underserved communities."
EDD_DISCOVERY = "I'm passionate about improving student outcomes in urban public schools."

_TOPIC_RESULT = {"sources": [], "results": [], "disclaimer": ""}
_ADVISOR_MATCH = {
    "match": {"advisor_name": "Dr. Test", "email": "t@csulb.edu",
              "program": "P", "source": "https://www.csulb.edu/x",
              "advisor_email": "t@csulb.edu"},
    "confidence": 95, "suggestions": [],
}


def _active(session_id):
    js = get_context(session_id, init_journey_state).journey_state
    return js.get("active_program")


def _spy_deadlines():
    return mock.patch("tools.deadlines_tool.get_deadlines",
                      mock.Mock(return_value=dict(_TOPIC_RESULT)))


def _spy_eligibility():
    return mock.patch("tools.eligibility_tool.get_eligibility",
                      mock.Mock(return_value=dict(_TOPIC_RESULT)))


def _spy_application():
    return mock.patch("tools.application_steps_tool.get_application_steps",
                      mock.Mock(return_value=dict(_TOPIC_RESULT)))


def _query_of(spy):
    """The query string the spied tool was called with."""
    return spy.call_args.args[0] if spy.call_args.args else spy.call_args.kwargs.get("query", "")


class TestContinuity(unittest.TestCase):
    def setUp(self):
        for s in ("A", "B", "C", "D", "E", "F", "G", "H"):
            clear_context(s)

    # ── A. recommendation → contextual deadline ──────────────────────────────
    def test_A_recommendation_to_contextual_deadline(self):
        handle_discovery(DRPH_DISCOVERY, "A")
        self.assertEqual(_active("A")["program_id"], "drph-public-health")
        with _spy_deadlines() as spy:
            orchestrator.run("what is the deadline for this program", session_id="A")
        self.assertIn("Public Health", _query_of(spy))

    # ── B. recommendation → contextual application ───────────────────────────
    def test_B_recommendation_to_contextual_application(self):
        handle_discovery(DRPH_DISCOVERY, "B")
        # The application route now asks applicant type before running the
        # workflow; set it so this test still exercises the program-context
        # augmentation reaching the tool.
        js = get_context("B", init_journey_state).journey_state
        js["applicant_type"] = "domestic"
        save_context("B", js)
        with _spy_application() as spy:
            orchestrator.run("how do I apply to it", session_id="B")
        self.assertIn("Public Health", _query_of(spy))

    # ── C. explicit switch A → B, then pronoun uses B ────────────────────────
    def test_C_context_switch(self):
        handle_discovery(DRPH_DISCOVERY, "C")               # active = DrPH
        with _spy_deadlines():
            orchestrator.run("what are the deadlines for physical therapy?", session_id="C")
        self.assertEqual(_active("C")["program_id"], "dpt-physical-therapy")  # switched
        with _spy_deadlines() as spy:
            orchestrator.run("what is its deadline?", session_id="C")
        self.assertIn("Physical Therapy", _query_of(spy))

    # ── D. direct explicit query sets active; pronoun advisor uses it ────────
    def test_D_direct_explicit_then_advisor_pronoun(self):
        with _spy_deadlines():
            orchestrator.run("what are the deadlines for physical therapy?", session_id="D")
        self.assertEqual(_active("D")["program_id"], "dpt-physical-therapy")
        # routing-level augmentation → the router's find_advisor sees the
        # active-program-augmented query
        with mock.patch("routing.router.find_advisor",
                        mock.Mock(return_value=_ADVISOR_MATCH)) as spy:
            orchestrator.run("who is the advisor for it", session_id="D")
        self.assertTrue(spy.called)
        calls = [(c.args[0] if c.args else c.kwargs.get("query", ""))
                 for c in spy.call_args_list]
        self.assertTrue(any("Physical Therapy" in q for q in calls), calls)

    # ── E. no context still clarifies (query NOT augmented) ──────────────────
    def test_E_no_context_preserves_clarification(self):
        with _spy_deadlines() as spy:
            orchestrator.run("what is the deadline", session_id="E")
        self.assertEqual(_query_of(spy), "what is the deadline")  # unchanged
        self.assertIsNone(_active("E"))

    # ── F. broad category does not set an active program ─────────────────────
    def test_F_broad_category_no_active(self):
        orchestrator.run("I'm interested in healthcare", session_id="F")
        self.assertIsNone(_active("F"))

    # ── G. eligibility contextual follow-up (specific context not overwritten) ─
    def test_G_eligibility_contextual_followup(self):
        handle_discovery(DRPH_DISCOVERY, "G")
        with _spy_eligibility() as spy:
            orchestrator.run("what are the eligibility requirements for the program",
                             session_id="G")
        self.assertIn("Public Health", _query_of(spy))
        self.assertEqual(_active("G")["program_id"], "drph-public-health")  # unchanged

    # ── second program proves genericity: EdD via discovery → contextual ─────
    def test_generic_second_program_edd(self):
        handle_discovery(EDD_DISCOVERY, "A")
        self.assertEqual(_active("A")["program_id"], "edd-educational-leadership-p12")
        with _spy_deadlines() as spy:
            orchestrator.run("what is the deadline for this program", session_id="A")
        self.assertIn("Educational Leadership", _query_of(spy))


class TestAdvisorContinuity(unittest.TestCase):
    """Advisor-route continuity through the REAL advisor lookup (find_advisor),
    proving the active program is consumed by the advisor matcher too. Uses DNP
    and DPT to prove genericity. No mocking of the advisor matcher — the whole
    point is that the augmented query resolves against real advisor data."""

    # deterministic single-recommend DNP discovery input
    DNP_DISCOVERY = ("I am a registered nurse with clinical experience seeking a "
                     "doctoral nursing practice degree")

    def setUp(self):
        for s in ("adv1", "adv2", "adv3", "adv4", "adv5"):
            clear_context(s)

    def _advisor_program(self, resp):
        return ((resp.get("advisor_data") or {}).get("match") or {}).get("program")

    # Test 1 — recommendation → bare advisor question
    def test_1_recommendation_to_advisor(self):
        r_disc, _ = handle_discovery(self.DNP_DISCOVERY, "adv1")
        self.assertEqual(_active("adv1")["program_id"], "dnp-nursing")
        r = orchestrator.run("Who is the advisor?", session_id="adv1")
        self.assertEqual(r["route"], "advisor")
        self.assertEqual(self._advisor_program(r), "Nursing (D.N.P.)")
        self.assertEqual(_active("adv1")["program_id"], "dnp-nursing")  # not discarded

    # Test 2 — explicit advisor query, then bare follow-up reuses it
    def test_2_explicit_then_bare_advisor(self):
        r1 = orchestrator.run("Who is the advisor for Physical Therapy?", session_id="adv2")
        self.assertEqual(self._advisor_program(r1), "Physical Therapy (DPT)")
        self.assertEqual(_active("adv2")["program_id"], "dpt-physical-therapy")
        r2 = orchestrator.run("Who is the advisor?", session_id="adv2")
        self.assertEqual(self._advisor_program(r2), "Physical Therapy (DPT)")

    # Test 3 — context switch (DNP active → explicit DPT → bare advisor)
    def test_3_context_switch_advisor(self):
        handle_discovery(self.DNP_DISCOVERY, "adv3")
        self.assertEqual(_active("adv3")["program_id"], "dnp-nursing")
        orchestrator.run("what are the deadlines for physical therapy?", session_id="adv3")
        self.assertEqual(_active("adv3")["program_id"], "dpt-physical-therapy")  # switched
        r = orchestrator.run("Who is the advisor?", session_id="adv3")
        self.assertEqual(self._advisor_program(r), "Physical Therapy (DPT)")

    # Test 4 — no active context → legitimate clarification preserved
    def test_4_no_context_clarifies(self):
        r = orchestrator.run("Who is the advisor?", session_id="adv4")
        self.assertEqual(r["route"], "advisor")
        self.assertIsNone(self._advisor_program(r))   # no match → asks for program
        self.assertIsNone(_active("adv4"))

    # Test 5 — original query preserved; internal advisor lookup gets augmented query
    def test_5_query_preserved_tool_query_augmented(self):
        handle_discovery(self.DNP_DISCOVERY, "adv5")
        with mock.patch("routing.router.find_advisor",
                        mock.Mock(return_value=_ADVISOR_MATCH)) as spy:
            r = orchestrator.run("Who is the advisor?", session_id="adv5")
        self.assertEqual(r["query"], "Who is the advisor?")            # user-facing original
        calls = [(c.args[0] if c.args else c.kwargs.get("query", ""))
                 for c in spy.call_args_list]
        self.assertTrue(any("Nursing" in q for q in calls), calls)     # internal augmented


class TestRationaleUI(unittest.TestCase):
    # ── H. "Why this program matched" not rendered; backend rationale remains ─
    def test_H_expander_removed_from_frontend(self):
        app_src = (Path(__file__).parent.parent / "app.py").read_text("utf-8")
        self.assertNotIn("Why this program matched", app_src)

    def test_H_backend_rationale_preserved(self):
        clear_context("H")
        r, _ = handle_discovery(DRPH_DISCOVERY, "H")
        matches = r.get("program_matches") or []
        self.assertTrue(matches)
        # score_basis rationale still present in the backend response object
        self.assertIn("score_basis", matches[0])


if __name__ == "__main__":
    unittest.main()
