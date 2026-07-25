"""
tests/test_coordinator.py
Multi-Agent Coordinator (Version 2) — the optional, flag-gated composite
orchestration layer. These tests are ADDITIVE and isolated; the existing
regression suite proves the coordinator changes nothing on the default path.

What is asserted:
  * detector — deterministic composite vs single-intent classification
  * planner  — deterministic, dependency-ordered plan
  * bypass   — single-intent requests never reach the coordinator
  * flag off — a composite request behaves exactly as it does today
  * flag on  — a composite request activates the coordinator and returns a
               synthesized composite response
  * reuse    — advisor/application sections resolve to the DISCOVERED program
               (dependency propagated through shared JourneyState, not hardcoded)
  * safe clarification — a broad discovery input halts and returns the existing
               clarification response verbatim (no broken composite)
  * API      — the composite response validates against QueryResponse through
               FastAPI TestClient (guards the additive union member)

The composite request uses a specific healthcare discovery signal (registered
nurse → DNP) so discovery deterministically recommends a single program, which
is what a composite flow needs. A vaguer "healthcare" input is used to exercise
the safe-clarification path.

Run: pytest tests/test_coordinator.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from coordination import detector, planner
from coordination.contracts import Intent
from state.context_manager import clear_context

# A composite healthcare request that resolves to a single program (DNP nursing),
# names the advisor ask, and declares international applicant type — so the whole
# discovery→advisor→application chain runs without any clarification.
COMPOSITE = ("I am a registered nurse seeking a doctoral nursing practice degree. "
             "Recommend a program, tell me who the advisor is, and explain how an "
             "international student should apply.")


# ---------------------------------------------------------------------------
# Detector — pure, deterministic
# ---------------------------------------------------------------------------

class TestDetector(unittest.TestCase):
    def test_composite_detected(self):
        self.assertTrue(detector.is_composite(COMPOSITE))
        self.assertEqual(
            detector.detect_intents(COMPOSITE),
            {Intent.DISCOVERY, Intent.ADVISOR, Intent.APPLICATION},
        )

    def test_single_intent_not_composite(self):
        self.assertFalse(detector.is_composite("Who is the advisor for physical therapy?"))
        self.assertFalse(detector.is_composite("How do I apply for public health?"))
        self.assertFalse(detector.is_composite("what is the deadline for the DNP"))

    def test_dependent_without_discovery_not_composite(self):
        # advisor + application but no discovery → left to existing routes
        self.assertFalse(detector.is_composite("who is the advisor and how do I apply"))


# ---------------------------------------------------------------------------
# Planner — deterministic, dependency-ordered
# ---------------------------------------------------------------------------

class TestPlanner(unittest.TestCase):
    def test_plan_order_and_dependencies(self):
        intents = {Intent.APPLICATION, Intent.DISCOVERY, Intent.ADVISOR}
        plan = planner.build_plan(COMPOSITE, intents, applicant_type="international")
        # discovery first, then advisor, then application (INTENT_ORDER)
        self.assertEqual(plan.intents, (Intent.DISCOVERY, Intent.ADVISOR, Intent.APPLICATION))
        self.assertEqual(plan.applicant_type, "international")
        # discovery gets the original query; dependents depend on discovery
        disc = plan.steps[0]
        self.assertEqual(disc.prompt, COMPOSITE)
        self.assertEqual(disc.depends_on, ())
        for step in plan.steps[1:]:
            self.assertIn(Intent.DISCOVERY, step.depends_on)


# ---------------------------------------------------------------------------
# Integration through the real backend entry point
# ---------------------------------------------------------------------------

def _run(query, sid, enabled):
    """Call handle_user_query with the coordinator flag patched on/off."""
    with mock.patch("config.settings.ENABLE_MULTI_AGENT_COORDINATOR", enabled):
        from backend.entrypoint import handle_user_query
        return handle_user_query(query, sid)


class TestBypassAndFlag(unittest.TestCase):
    def setUp(self):
        for s in ("c1", "c2", "c3", "c4", "c5", "c6"):
            clear_context(s)

    def test_single_intent_bypasses_coordinator(self):
        # Even with the flag ON, a single-intent request must NOT be composite.
        with mock.patch("coordination.coordinator.run") as spy:
            r = _run("Who is the advisor for physical therapy?", "c1", enabled=True)
        spy.assert_not_called()
        self.assertEqual(r["route"], "advisor")

    def test_flag_off_composite_uses_existing_path(self):
        # Flag OFF: composite request behaves exactly as today (coordinator never
        # imported/run). The existing path routes it as a single request.
        with mock.patch("coordination.coordinator.run") as spy:
            r = _run(COMPOSITE, "c2", enabled=False)
        spy.assert_not_called()
        self.assertNotEqual(r.get("route"), "composite")

    def test_flag_on_composite_activates_coordinator(self):
        r = _run(COMPOSITE, "c3", enabled=True)
        self.assertEqual(r["route"], "composite")
        intents = [s["intent"] for s in r["sections"]]
        self.assertEqual(intents, ["discovery", "advisor", "application"])

    def test_sections_depend_on_discovered_program(self):
        r = _run(COMPOSITE, "c4", enabled=True)
        sections = {s["intent"]: s["response"] for s in r["sections"]}
        # discovery resolved DNP nursing …
        disc_matches = sections["discovery"].get("program_matches") or []
        self.assertTrue(any((m.get("program_id") == "dnp-nursing") for m in disc_matches))
        # … and the advisor section resolved to that same program (reuse, not
        # hardcoded): advisor matched a Nursing (D.N.P.) advisor.
        advisor_program = ((sections["advisor"].get("advisor_data") or {})
                           .get("match") or {}).get("program")
        self.assertEqual(advisor_program, "Nursing (D.N.P.)")
        # … and the application section ran the workflow (no gate) with the
        # international supplement, tailored by the propagated applicant type.
        app = sections["application"]
        self.assertFalse((app.get("tool_result") or {}).get("needs_applicant_type"))
        self.assertTrue((app.get("tool_result") or {}).get("workflow_steps"))
        self.assertIsNotNone(app.get("international_info"))

    def test_broad_discovery_safely_returns_clarification(self):
        # Broad "healthcare" → discovery can't resolve a single program; the
        # coordinator returns the existing clarification response verbatim
        # rather than a broken composite.
        broad = ("I'm interested in healthcare. Recommend a program, who is the "
                 "advisor, and how do I apply?")
        r = _run(broad, "c5", enabled=True)
        self.assertNotEqual(r.get("route"), "composite")
        self.assertEqual(r.get("route"), "discovery")
        self.assertEqual(r.get("behavior"), "clarify")


# ---------------------------------------------------------------------------
# API-level — the composite response must validate against QueryResponse
# ---------------------------------------------------------------------------

class TestApiComposite(unittest.TestCase):
    def test_composite_validates_through_testclient(self):
        from fastapi.testclient import TestClient
        clear_context("api-composite")
        with mock.patch("config.settings.ENABLE_MULTI_AGENT_COORDINATOR", True):
            from api.app import app
            client = TestClient(app)
            resp = client.post("/query", json={"query": COMPOSITE, "session_id": "api-composite"})
        self.assertEqual(resp.status_code, 200)   # no ResponseValidationError
        body = resp.json()
        self.assertEqual(body["route"], "composite")
        self.assertEqual([s["intent"] for s in body["sections"]],
                         ["discovery", "advisor", "application"])


if __name__ == "__main__":
    unittest.main()
