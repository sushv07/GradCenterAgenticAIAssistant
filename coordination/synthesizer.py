"""
coordination/synthesizer.py
Deterministic synthesis of executed step results into ONE composite response.

The synthesizer does not re-summarize or re-interpret any workflow's output — it
aggregates the untouched per-step responses into a strongly-typed Composite
envelope and composes a short top-level overview by pulling already-computed
fields (recommended program, advisor name, applicant type) from those responses.
Each section is preserved whole so the frontend can render it with the SAME
per-route panels it already uses.

The result is built with responses.builder.build_response() (the shared envelope
builder every route uses) and is a valid CompositeResponseModel — route
"composite", plus a `sections` list — so it passes the FastAPI /query
response_model validation like any other route.
"""
from __future__ import annotations

from typing import Optional

from telemetry.tracing import span

from coordination.contracts import ExecutionResult, Intent, StepResult
from responses.builder import build_response

_GRAD_CENTER_URL = "https://www.csulb.edu/graduate-center"


def _by_intent(result: ExecutionResult, intent: Intent) -> Optional[StepResult]:
    return next((s for s in result.steps if s.intent is intent), None)


def _recommended_program(discovery: Optional[StepResult]) -> str:
    if not discovery:
        return ""
    matches = discovery.response.get("program_matches") or []
    if matches:
        return matches[0].get("name") or matches[0].get("program_id") or ""
    return ""


def _advisor_name(advisor: Optional[StepResult]) -> str:
    if not advisor:
        return ""
    match = (advisor.response.get("advisor_data") or {}).get("match") or {}
    return match.get("advisor_name") or ""


def _compose_summary(result: ExecutionResult, applicant_type: Optional[str]) -> str:
    """A single-sentence overview stitched from already-computed section fields.
    Purely deterministic string assembly — no model, no re-derivation."""
    program = _recommended_program(_by_intent(result, Intent.DISCOVERY))
    parts: list[str] = []
    if program:
        parts.append(f"Recommended program: {program}")
    advisor = _advisor_name(_by_intent(result, Intent.ADVISOR))
    if advisor:
        parts.append(f"advisor {advisor}")
    if _by_intent(result, Intent.APPLICATION):
        who = f"{applicant_type} applicants" if applicant_type else "applicants"
        parts.append(f"application steps for {who}")
    if not parts:
        return "Here's what I found for your request."
    return "Here's a combined answer — " + "; ".join(parts) + "."


def synthesize(query: str, session_id: str, result: ExecutionResult,
               applicant_type: Optional[str] = None) -> dict:
    """Build the composite response from executed steps. Callers guarantee
    result is not halted (the coordinator returns a halted result's
    clarification directly instead of synthesizing)."""
    with span("synthesizer.compose", attributes={"sections.count": len(result.steps)}):
        sections = [{"intent": s.intent.value, "response": s.response} for s in result.steps]

        return build_response(
            query=query,
            route="composite",
            session_id=session_id,
            summary=_compose_summary(result, applicant_type),
            primary_action="Review each section below; verify details on the official CSULB pages.",
            source={"file": "", "url": _GRAD_CENTER_URL},
            next_actions=[
                "Ask for the application deadline for this program",
                "Draft an email to the advisor",
            ],
            extra={"sections": sections},
        )
