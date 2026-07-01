"""
test_healthcare_clarification.py
Goal-oriented healthcare clarification flow — 6 spec test cases.

Turn 1 of "I want a clinical doctoral degree in healthcare." must ask
a goal-oriented question (not a program menu).  Turn 2 answers should
resolve to the correct program: DPT, DNP, DrPH, or continue clarifying
when the answer remains ambiguous.

Run from the project root:
    pytest tests/test_healthcare_clarification.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.journey_agent import handle_discovery
from state.context_manager import clear_context


BROAD_HEALTHCARE_Q = "I want a clinical doctoral degree in healthcare."


def _fresh(sid: str):
    clear_context(sid)


# ---------------------------------------------------------------------------
# Test 1 — Broad healthcare query must produce goal-oriented clarification
# ---------------------------------------------------------------------------

class TestBroadHealthcareClarification:

    def test_behavior_is_clarify(self):
        _fresh("hc1")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1")
        assert r["behavior"] == "clarify", (
            f"Broad healthcare query must clarify first; got {r['behavior']!r}"
        )

    def test_confidence_is_none(self):
        _fresh("hc1a")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1a")
        assert r["confidence"] == "none"

    def test_no_recommended_programs(self):
        _fresh("hc1b")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1b")
        assert r["recommended_programs"] == []

    def test_no_program_matches(self):
        _fresh("hc1c")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1c")
        assert r.get("program_matches", []) == []

    def test_question_mentions_direct_patient_care(self):
        _fresh("hc1d")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1d")
        q = (r.get("clarification_question") or "").lower()
        assert "direct patient care" in q, (
            f"Question must mention 'direct patient care'; got: {q!r}"
        )

    def test_question_mentions_nursing_leadership(self):
        _fresh("hc1e")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1e")
        q = (r.get("clarification_question") or "").lower()
        assert "nursing" in q, (
            f"Question must mention nursing; got: {q!r}"
        )

    def test_question_mentions_public_health(self):
        _fresh("hc1f")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1f")
        q = (r.get("clarification_question") or "").lower()
        assert "public health" in q, (
            f"Question must mention 'public health'; got: {q!r}"
        )

    def test_question_mentions_rehabilitation(self):
        _fresh("hc1g")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1g")
        q = (r.get("clarification_question") or "").lower()
        assert "rehabilitation" in q, (
            f"Question must mention 'rehabilitation'; got: {q!r}"
        )

    def test_question_is_goal_oriented_not_program_menu(self):
        """Must ask about goals, not present a program menu."""
        _fresh("hc1h")
        r, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc1h")
        q = (r.get("clarification_question") or "").lower()
        # Goal-oriented language
        assert any(kw in q for kw in ("role", "impact", "hoping")), (
            f"Question should be goal-oriented; got: {q!r}"
        )
        # Must NOT jump straight to program names as choices
        for prog in ("dpt", "dnp", "drph", "doctor of nursing", "doctor of physical"):
            assert prog not in q, (
                f"Question must not present a program menu; found {prog!r} in: {q!r}"
            )


# ---------------------------------------------------------------------------
# Test 2 — Healthcare → DPT via rehabilitation signal
# ---------------------------------------------------------------------------

class TestHealthcareToDPT:

    def test_turn1_clarifies(self):
        _fresh("hc2a")
        r1, _ = handle_discovery(BROAD_HEALTHCARE_Q, "hc2a")
        assert r1["behavior"] == "clarify"

    def test_turn2_recommends_dpt(self):
        _fresh("hc2")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc2")
        r2, _ = handle_discovery("I want to help patients recover movement.", "hc2")
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        assert "dpt-physical-therapy" in ids, (
            f"DPT must be recommended after rehabilitation signal; got {ids}"
        )

    def test_turn2_dpt_has_advisor(self):
        _fresh("hc2b")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc2b")
        r2, _ = handle_discovery("I want to help patients recover movement.", "hc2b")
        top = r2.get("program_matches", [{}])[0]
        assert top.get("advisor_email"), "DPT program_match must include advisor_email"

    def test_turn2_dpt_has_deadline(self):
        _fresh("hc2c")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc2c")
        r2, _ = handle_discovery("I want to help patients recover movement.", "hc2c")
        top = r2.get("program_matches", [{}])[0]
        assert top.get("deadline_fall"), "DPT program_match must include deadline_fall"

    def test_turn2_dpt_behavior_is_recommend(self):
        _fresh("hc2d")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc2d")
        r2, _ = handle_discovery("I want to help patients recover movement.", "hc2d")
        assert r2["behavior"] in ("recommend", "multi_recommend"), (
            f"Turn 2 must produce a recommendation; got {r2['behavior']!r}"
        )

    def test_turn2_route_stays_discovery(self):
        _fresh("hc2e")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc2e")
        r2, _ = handle_discovery("I want to help patients recover movement.", "hc2e")
        assert r2["route"] == "discovery"


# ---------------------------------------------------------------------------
# Test 3 — Healthcare → DNP via nursing interest signal
# ---------------------------------------------------------------------------

class TestHealthcareToDNP:

    def test_turn2_recommends_dnp(self):
        _fresh("hc3")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc3")
        r2, _ = handle_discovery("I want advanced nursing practice.", "hc3")
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        assert "dnp-nursing" in ids, (
            f"DNP must be recommended after nursing signal; got {ids}"
        )

    def test_turn2_dnp_behavior_is_recommend(self):
        _fresh("hc3a")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc3a")
        r2, _ = handle_discovery("I want advanced nursing practice.", "hc3a")
        assert r2["behavior"] in ("recommend", "multi_recommend"), (
            f"Turn 2 must produce a recommendation; got {r2['behavior']!r}"
        )

    def test_turn2_dnp_confidence_is_valid(self):
        _fresh("hc3b")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc3b")
        r2, _ = handle_discovery("I want advanced nursing practice.", "hc3b")
        assert r2["confidence"] in ("high", "medium"), (
            f"DNP after nursing signal should have medium+ confidence; "
            f"got {r2['confidence']!r}"
        )


# ---------------------------------------------------------------------------
# Test 4 — Healthcare → DrPH via population health / policy signal
# ---------------------------------------------------------------------------

class TestHealthcareToDrPH:

    def test_turn2_recommends_drph(self):
        _fresh("hc4")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc4")
        r2, _ = handle_discovery("I want to work on population health policy.", "hc4")
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        assert "drph-public-health" in ids, (
            f"DrPH must be recommended after population health policy signal; got {ids}"
        )

    def test_turn2_drph_behavior_is_recommend(self):
        _fresh("hc4a")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc4a")
        r2, _ = handle_discovery("I want to work on population health policy.", "hc4a")
        assert r2["behavior"] in ("recommend", "multi_recommend"), (
            f"Turn 2 must produce a recommendation; got {r2['behavior']!r}"
        )

    def test_turn2_drph_confidence_is_valid(self):
        _fresh("hc4b")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc4b")
        r2, _ = handle_discovery("I want to work on population health policy.", "hc4b")
        assert r2["confidence"] in ("high", "medium"), (
            f"DrPH after health policy signal should have medium+ confidence; "
            f"got {r2['confidence']!r}"
        )


# ---------------------------------------------------------------------------
# Test 5 — Still ambiguous after Turn 2 — no forced recommendation
# ---------------------------------------------------------------------------

class TestHealthcareStillAmbiguous:

    def test_turn2_vague_continues_clarifying(self):
        _fresh("hc5")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc5")
        r2, _ = handle_discovery("I want to help people.", "hc5")
        # Must not force a recommendation on ambiguous input
        assert r2["behavior"] == "clarify", (
            f"'I want to help people' must not force a recommendation; "
            f"got {r2['behavior']!r}"
        )

    def test_turn2_vague_no_programs_surfaced(self):
        _fresh("hc5a")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc5a")
        r2, _ = handle_discovery("I want to help people.", "hc5a")
        assert r2.get("program_matches", []) == [], (
            f"No programs must be surfaced when still ambiguous; "
            f"got {r2.get('program_matches')}"
        )

    def test_turn2_vague_confidence_is_none(self):
        _fresh("hc5b")
        handle_discovery(BROAD_HEALTHCARE_Q, "hc5b")
        r2, _ = handle_discovery("I want to help people.", "hc5b")
        assert r2["confidence"] == "none"


# ---------------------------------------------------------------------------
# Test 6 — Regression: DNP deadlines query must stay on deadlines route
# ---------------------------------------------------------------------------

class TestDeadlinesRegressionNotDiscovery:

    def test_dnp_deadlines_goes_to_deadlines_route_not_discovery(self):
        """
        'What are the application deadlines for DNP?' must not enter the
        discovery journey — it belongs to the deadlines or advisor route.
        Tested via the orchestrator so the full router path is exercised.
        """
        import orchestrator as orch_module
        response = orch_module.run(
            "What are the application deadlines for DNP?",
            session_id="hc6-reg",
        )
        route = response.get("route", "")
        assert route != "discovery", (
            f"DNP deadlines query must not route to 'discovery'; got route={route!r}"
        )
