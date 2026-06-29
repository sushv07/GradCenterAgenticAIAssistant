"""
tests/test_backend_entrypoint.py
Phase 4F — regression tests for the unified backend entry point.

Covers:
  - A standard (non-discovery) request routes exactly as orchestrator.run()
    would have routed it directly.
  - A discovery request starts a journey and returns a discovery response.
  - Discovery continuation: a second call with the same session_id
    continues the same JourneyState, without the caller deciding so.
  - Multiple sessions / session isolation: two different session_ids never
    see each other's JourneyState.
  - _is_discovery_active() reflects JourneyState.phase exactly.

Run from the project root:
    pytest tests/test_backend_entrypoint.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

from backend.entrypoint import handle_user_query, _is_discovery_active
from state.context_manager import clear_context
import orchestrator


def _fresh(sid: str) -> None:
    clear_context(sid)


class TestStandardRequest(unittest.TestCase):
    """A non-discovery query should route identically to orchestrator.run()."""

    def test_deadlines_query_matches_orchestrator_directly(self):
        sid = "be-standard-1"
        _fresh(sid)
        via_entrypoint = handle_user_query("when is the application deadline", session_id=sid)
        _fresh(sid)
        via_orchestrator = orchestrator.run("when is the application deadline", session_id=sid)
        _fresh(sid)
        self.assertEqual(via_entrypoint, via_orchestrator)

    def test_advisor_query_matches_orchestrator_directly(self):
        sid = "be-standard-2"
        _fresh(sid)
        via_entrypoint = handle_user_query("who is my advisor for nursing", session_id=sid)
        _fresh(sid)
        via_orchestrator = orchestrator.run("who is my advisor for nursing", session_id=sid)
        _fresh(sid)
        self.assertEqual(via_entrypoint, via_orchestrator)


class TestDiscoveryStart(unittest.TestCase):
    def test_vague_query_starts_discovery(self):
        sid = "be-discovery-start"
        _fresh(sid)
        response = handle_user_query("I don't know what graduate program fits me", session_id=sid)
        self.assertEqual(response["route"], "discovery")
        _fresh(sid)


class TestDiscoveryContinuation(unittest.TestCase):
    """The defining Phase 4F behavior: the caller never decides continuation."""

    def test_second_call_continues_same_journey_without_caller_deciding(self):
        sid = "be-discovery-continue"
        _fresh(sid)

        r1 = handle_user_query("I am interested in educational leadership", session_id=sid)
        self.assertEqual(r1["route"], "discovery")
        self.assertEqual(r1["behavior"], "clarify")

        # Caller passes the same plain query + session_id, with zero
        # knowledge of discovery state — handle_user_query must route this
        # to the journey agent, not the generic router.
        r2 = handle_user_query("looking to lead K-12 schools and districts", session_id=sid)
        self.assertEqual(r2["route"], "discovery")
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        self.assertIn("edd-educational-leadership-p12", ids)

        _fresh(sid)

    def test_is_discovery_active_tracks_phase_exactly(self):
        sid = "be-phase-tracking"
        _fresh(sid)

        self.assertFalse(_is_discovery_active(sid))  # no state yet

        r1 = handle_user_query("I am interested in educational leadership", session_id=sid)
        self.assertEqual(r1["behavior"], "clarify")
        self.assertTrue(_is_discovery_active(sid))

        r2 = handle_user_query("looking to lead K-12 schools and districts", session_id=sid)
        self.assertNotEqual(r2["behavior"], "clarify")
        self.assertFalse(_is_discovery_active(sid))

        _fresh(sid)


class TestSessionIsolation(unittest.TestCase):
    def test_two_sessions_do_not_share_state(self):
        sid_a = "be-isolation-a"
        sid_b = "be-isolation-b"
        _fresh(sid_a)
        _fresh(sid_b)

        handle_user_query("I am interested in educational leadership", session_id=sid_a)
        self.assertTrue(_is_discovery_active(sid_a))
        self.assertFalse(_is_discovery_active(sid_b))

        # A fresh query under sid_b must not be treated as a continuation
        # of sid_a's pending clarification.
        response_b = handle_user_query("when is the application deadline", session_id=sid_b)
        self.assertNotEqual(response_b["route"], "discovery")

        _fresh(sid_a)
        _fresh(sid_b)


if __name__ == "__main__":
    unittest.main()
