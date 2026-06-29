"""
test_discovery_dispatch.py
Tests for multi-turn discovery session continuity.

Covers:
  - _is_discovery_clarify() pure predicate (mirrors app.py logic)
  - Two-turn journeys that would fail if the second turn went through the
    generic router instead of handle_discovery() with the same session_id.

The predicate is duplicated here (not imported from app.py) so this test
file can run without triggering Streamlit's page-config initialisation.

Run from the project root:
    pytest tests/test_discovery_dispatch.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.journey_agent import handle_discovery
from state.context_manager import clear_context


# ---------------------------------------------------------------------------
# Pure predicate — mirrors app._is_discovery_clarify
# ---------------------------------------------------------------------------

def _is_discovery_clarify(response: dict) -> bool:
    return (
        bool(response)
        and response.get("route") == "discovery"
        and response.get("behavior") == "clarify"
    )


class TestIsDiscoveryClarify:
    def test_true_when_route_and_behavior_match(self):
        assert _is_discovery_clarify({"route": "discovery", "behavior": "clarify"})

    def test_false_when_behavior_is_recommend(self):
        assert not _is_discovery_clarify({"route": "discovery", "behavior": "recommend"})

    def test_false_when_route_is_advisor(self):
        assert not _is_discovery_clarify({"route": "advisor", "behavior": "clarify"})

    def test_false_when_behavior_is_multi_recommend(self):
        assert not _is_discovery_clarify({"route": "discovery", "behavior": "multi_recommend"})

    def test_false_on_empty_dict(self):
        assert not _is_discovery_clarify({})

    def test_false_on_redirect(self):
        assert not _is_discovery_clarify({"route": "discovery", "behavior": "redirect"})

    def test_false_on_partial_match(self):
        assert not _is_discovery_clarify(
            {"route": "discovery", "behavior": "partial_match_with_caveat"}
        )


# ---------------------------------------------------------------------------
# Two-turn multi-turn journeys
# ---------------------------------------------------------------------------

def _fresh(sid: str):
    """Ensure no stale session state for this test session id."""
    clear_context(sid)


class TestMultiTurnDiscovery:

    def test_educational_leadership_resolves_to_p12(self):
        """
        Turn 1: 'I am interested in educational leadership'
            → discovery clarify (CC vs P-12 disambiguation)
        Turn 2: 'looking to lead K-12 schools and districts'
            → EdD-P12 recommend, medium confidence
        Advisor: eddinfo@csulb.edu  Deadline: February 15
        """
        sid = "test-dispatch-p12"
        _fresh(sid)

        # Turn 1
        r1, _ = handle_discovery("I am interested in educational leadership", sid)
        assert r1["route"] == "discovery"
        assert _is_discovery_clarify(r1), (
            f"Turn 1 should be a discovery clarification; got behavior={r1['behavior']!r}"
        )
        assert "K-12" in (r1.get("clarification_question") or ""), (
            "Turn 1 clarification question should mention K-12"
        )

        # Turn 2 — simulate app.py dispatching to handle_discovery directly
        r2, _ = handle_discovery("looking to lead K-12 schools and districts", sid)
        assert r2["route"] == "discovery"
        assert r2["behavior"] in ("recommend", "multi_recommend", "partial_match_with_caveat"), (
            f"Turn 2 must produce a recommendation; got {r2['behavior']!r}"
        )
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        assert "edd-educational-leadership-p12" in ids, (
            f"EdD-P12 must be in program_matches after K-12 clarification; got {ids}"
        )
        top = r2["program_matches"][0]
        assert top["program_id"] == "edd-educational-leadership-p12"
        assert top["confidence"] == "medium"
        assert top["advisor_email"] == "eddinfo@csulb.edu"
        assert top["deadline_fall"] == "February 15"

        _fresh(sid)

    def test_educational_leadership_resolves_to_cc(self):
        """
        Turn 1: 'I want to pursue educational leadership'
            → discovery clarify
        Turn 2: 'I want to lead in community colleges and higher education'
            → EdD-CC recommend
        """
        sid = "test-dispatch-cc"
        _fresh(sid)

        r1, _ = handle_discovery("I want to pursue educational leadership", sid)
        assert _is_discovery_clarify(r1)

        r2, _ = handle_discovery(
            "I want to lead in community colleges and higher education", sid
        )
        assert r2["route"] == "discovery"
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        assert "edd-educational-leadership-cc" in ids, (
            f"EdD-CC must be surfaced after CC clarification; got {ids}"
        )

        _fresh(sid)

    def test_health_clarify_then_resolve(self):
        """
        Turn 1: 'I have a healthcare background and want a doctoral degree'
            → discovery clarify (health_undifferentiated)
        Turn 2: 'I want to become a nurse practitioner'
            → DNP recommend, high confidence
        """
        sid = "test-dispatch-health"
        _fresh(sid)

        r1, _ = handle_discovery(
            "I have a healthcare background and want a doctoral degree", sid
        )
        assert r1["route"] == "discovery"
        # May clarify due to health_undifferentiated or admission_gated
        assert r1["behavior"] == "clarify"

        r2, _ = handle_discovery("I want to become a nurse practitioner", sid)
        assert r2["route"] == "discovery"
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        assert "dnp-nursing" in ids, (
            f"DNP must be surfaced after nurse practitioner signal; got {ids}"
        )
        assert r2["program_matches"][0]["confidence"] == "high", (
            "nurse_practitioner is a unique career tag → high confidence"
        )

        _fresh(sid)

    def test_second_turn_does_not_route_to_advisor_fallback(self):
        """
        Without the dispatch fix the second turn would fall through to the
        orchestrator router which, for vague 'K-12' text, might pick advisor
        or another non-discovery route.  Verify that route stays 'discovery'.
        """
        sid = "test-dispatch-no-fallback"
        _fresh(sid)

        r1, _ = handle_discovery("I am interested in educational leadership", sid)
        assert _is_discovery_clarify(r1), "Precondition: turn 1 must be clarify"

        # Simulate what app.py now does: continue via handle_discovery
        r2, _ = handle_discovery("K-12 district leadership", sid)
        assert r2["route"] == "discovery", (
            f"Turn 2 must stay on discovery route; got route={r2['route']!r}"
        )
        assert r2["behavior"] != "clarify", (
            "Turn 2 with K-12 signal should resolve, not keep clarifying"
        )

        _fresh(sid)
