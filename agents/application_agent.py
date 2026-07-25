"""
agents/application_agent.py
Thin adapter over the existing application-workflow.

Two responsibilities, both via existing seams:
  1. Propagate the applicant type (extracted once from the composite request)
     into the shared JourneyState BEFORE running the workflow — using the same
     canonical field and context API the production application route reads
     (js["applicant_type"] via state.context_manager). This is what lets the
     application step run without triggering the domestic/international
     clarification gate in Phase 1. We reuse the existing state interface rather
     than passing applicant type "out of band" through the plan.
  2. Run the application workflow through orchestrator.run() — the stable public
     seam that composes active-program augmentation + routing + the
     applicant-type-aware application response builder. (The builder itself,
     _build_application_response / _application_workflow_response, is private;
     going through run() reuses the whole composition without duplicating it.)
"""
from __future__ import annotations

from typing import Optional

import orchestrator
from agents.journey_agent import init_journey_state
from state.context_manager import get_context, save_context


def _propagate_applicant_type(session_id: str, applicant_type: Optional[str]) -> None:
    """Write the applicant type onto the canonical JourneyState field through the
    existing context API — the same field _build_application_response() reads."""
    if not applicant_type:
        return
    js = get_context(session_id, default_factory=init_journey_state).journey_state
    if js.get("applicant_type") != applicant_type:
        js["applicant_type"] = applicant_type
        save_context(session_id, js)


def run(prompt: str, session_id: str, applicant_type: Optional[str] = None) -> dict:
    """Ensure the applicant type is known in shared state, then run the existing
    application workflow for the session's active program."""
    _propagate_applicant_type(session_id, applicant_type)
    return orchestrator.run(prompt, session_id=session_id)
