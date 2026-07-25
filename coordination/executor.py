"""
coordination/executor.py
Deterministic, sequential execution of an ExecutionPlan.

Steps run in the plan's (already dependency-ordered) sequence, each dispatched
to its thin agent adapter. All steps share ONE session_id, so the program the
discovery step resolves into JourneyState is transparently consumed by the
advisor/application steps — the reuse mechanism, not re-derivation.

Phase 1 "safely return a clarification" behavior (no persistent coordinator
resume state — that is deferred to Phase 2): if a step cannot proceed as a
composite step, execution stops and the existing, already-valid workflow
response is handed back verbatim as `clarification`:
  * discovery did not resolve a single program (broad / out-of-scope input) →
    its clarify/redirect response is returned as-is;
  * the application step unexpectedly hit the applicant-type gate → that
    clarification response is returned as-is.
The coordinator returns such a response directly, so the user experiences the
normal single-workflow clarification rather than a broken composite.
"""
from __future__ import annotations

from agents import advisor_agent, application_agent, program_discovery_agent
from coordination.contracts import ExecutionPlan, ExecutionResult, Intent, StepResult


def _application_hit_gate(response: dict) -> bool:
    """True if the application workflow returned the applicant-type clarification
    instead of the workflow (should not happen once applicant type is propagated,
    but handled defensively per Phase 1)."""
    return bool((response.get("tool_result") or {}).get("needs_applicant_type"))


def execute(plan: ExecutionPlan, session_id: str) -> ExecutionResult:
    """Run each planned step in order, aggregating results or halting safely."""
    result = ExecutionResult()

    for step in plan.steps:
        if step.intent is Intent.DISCOVERY:
            response = program_discovery_agent.run(step.prompt, session_id)
            if not program_discovery_agent.recommended(response):
                # No single program resolved — dependent steps can't proceed.
                result.clarification = response
                return result
            result.steps.append(StepResult(Intent.DISCOVERY, response))

        elif step.intent is Intent.ADVISOR:
            response = advisor_agent.run(step.prompt, session_id)
            result.steps.append(StepResult(Intent.ADVISOR, response))

        elif step.intent is Intent.APPLICATION:
            response = application_agent.run(
                step.prompt, session_id, applicant_type=plan.applicant_type)
            if _application_hit_gate(response):
                result.clarification = response
                return result
            result.steps.append(StepResult(Intent.APPLICATION, response))

    return result
