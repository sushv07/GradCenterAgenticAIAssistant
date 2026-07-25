"""
coordination/planner.py
Deterministic execution planning.

Given the intents the detector found in a request, produce an ordered
ExecutionPlan. There is NO autonomous planning and NO LLM in this decision:
intents map to a fixed, dependency-ordered sequence of steps, each carrying a
canonical prompt the existing workflows already recognize.

Why canonical prompts (not the raw user words) for the dependent steps:
    The existing continuity resolver recognizes specific phrasings when
    resolving "the active program" — e.g. "Who is the advisor?" resolves against
    active_program, but "who is the advisor for it" does not. The planner emits
    the phrasings that are verified to route correctly, so each step reuses the
    production routing/augmentation path exactly rather than depending on however
    the user happened to word a clause. The DISCOVERY step, by contrast, is fed
    the original query because recommendation keys off the user's own interest
    signals.
"""
from __future__ import annotations

from typing import Optional

from coordination.contracts import ExecutionPlan, Intent, INTENT_ORDER, PlanStep

# Canonical, continuity-recognized prompts for the dependent steps. Verified to
# resolve against active_program set by the discovery step (see the Phase 1
# validation notes). Do not "improve" these without re-verifying routing.
_ADVISOR_PROMPT     = "Who is the advisor?"
_APPLICATION_PROMPT = "how do I apply to it"


def build_plan(
    query: str,
    intents: set[Intent],
    applicant_type: Optional[str] = None,
) -> ExecutionPlan:
    """Assemble the ordered plan. Steps are emitted in INTENT_ORDER so discovery
    always precedes the steps that depend on it."""
    depends_on_discovery = (Intent.DISCOVERY,) if Intent.DISCOVERY in intents else ()

    prompts: dict[Intent, tuple[str, tuple[Intent, ...]]] = {
        Intent.DISCOVERY:   (query, ()),
        Intent.ADVISOR:     (_ADVISOR_PROMPT, depends_on_discovery),
        Intent.APPLICATION: (_APPLICATION_PROMPT, depends_on_discovery),
    }

    steps = tuple(
        PlanStep(intent=intent, prompt=prompts[intent][0], depends_on=prompts[intent][1])
        for intent in INTENT_ORDER
        if intent in intents
    )
    return ExecutionPlan(original_query=query, steps=steps, applicant_type=applicant_type)
