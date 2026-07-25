"""
coordination/coordinator.py
The Multi-Agent Coordinator entry point.

Orchestrates the four deterministic stages for a composite request:

    detect  →  plan  →  execute  →  synthesize

and returns ONE user-facing response. It is invoked only from
backend.entrypoint.handle_user_query, and only when
settings.ENABLE_MULTI_AGENT_COORDINATOR is on AND detector.is_composite(query)
is true. With the flag off or the request single-intent, this module is never
reached and the existing orchestration runs unchanged.

Import direction (no cycles): this module imports the agent adapters, which
import orchestrator / agents.journey_agent / state.* — never
backend.entrypoint. backend.entrypoint imports THIS module (lazily), so the
dependency edge is one-way: entrypoint → coordinator → (orchestrator, agents).
"""
from __future__ import annotations

from typing import Optional

from state.clarification import parse_applicant_type

from coordination import executor, planner
from coordination.detector import detect_intents, is_composite
from coordination.synthesizer import synthesize


def run(query: str, session_id: str) -> dict:
    """Handle one composite request end to end and return a single response.

    Callers must have already confirmed is_composite(query); run() re-detects
    intents (cheap, pure) to build the plan. If execution halts on a
    clarification (broad discovery input, or an unexpected applicant-type gate),
    that existing, already-valid workflow response is returned verbatim —
    Phase 1 does not persist composite resume state.
    """
    query = (query or "").strip()
    intents = detect_intents(query)

    # Applicant type is extracted once here and propagated through the existing
    # JourneyState interface by the application step (see agents/application_agent
    # .py) — not carried as out-of-band coordinator state.
    applicant_type: Optional[str] = parse_applicant_type(query)

    plan = planner.build_plan(query, intents, applicant_type=applicant_type)
    result = executor.execute(plan, session_id)

    if result.halted:
        return result.clarification

    return synthesize(query, session_id, result, applicant_type=applicant_type)


def maybe_run(query: str, session_id: str) -> Optional[dict]:
    """Convenience gate for the single integration branch: run the coordinator
    iff the request is composite, else return None so the caller falls through
    to the existing orchestration. Keeps the entrypoint branch a one-liner."""
    if is_composite(query):
        return run(query, session_id)
    return None
