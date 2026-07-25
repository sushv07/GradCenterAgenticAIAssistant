"""
coordination/contracts.py
Strongly-typed, internal data structures the coordinator passes between its
deterministic stages (detect → plan → execute → synthesize).

These are plain frozen dataclasses / enums — the *internal* wiring of the
coordinator. They are distinct from the *response* contracts a caller sees:
the synthesized user-facing response is a CompositeResponse
(contracts/response_types.py) validated by CompositeResponseModel
(api/contracts.py). Keeping the two separate means the coordinator's internal
plan representation can evolve without touching the public API schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    """The composite intents Phase 1 understands. Each maps 1:1 to an existing
    workflow via a thin agent adapter (agents/*_agent.py) — no new capability."""
    DISCOVERY   = "discovery"     # recommend a program  → handle_discovery()
    ADVISOR     = "advisor"       # who is the advisor    → orchestrator.run()
    APPLICATION = "application"   # how do I apply         → orchestrator.run()


# Deterministic execution order. The coordinator never reorders beyond this;
# discovery must run first because advisor/application depend on the program it
# resolves into the shared JourneyState (active_program).
INTENT_ORDER: tuple[Intent, ...] = (Intent.DISCOVERY, Intent.ADVISOR, Intent.APPLICATION)


@dataclass(frozen=True)
class PlanStep:
    """One unit of work in an ExecutionPlan.

    `prompt` is the canonical natural-language phrasing handed to the agent
    adapter — deliberately a phrasing the EXISTING continuity resolver already
    recognizes (e.g. "Who is the advisor?"), not a free-form paraphrase, so the
    step reuses the production routing/augmentation path exactly.
    `depends_on` names intents whose output (the discovered program in shared
    state) this step consumes; the executor runs steps in INTENT_ORDER so a
    dependency is always satisfied before its dependent runs.
    """
    intent:     Intent
    prompt:     str
    depends_on: tuple[Intent, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    """A deterministic, ordered plan produced by the planner from detected
    intents. `applicant_type` is extracted once from the original request and
    propagated through the existing JourneyState interface before the
    application step (so no applicant-type clarification is required in Phase 1)."""
    original_query: str
    steps:          tuple[PlanStep, ...]
    applicant_type: Optional[str] = None

    @property
    def intents(self) -> tuple[Intent, ...]:
        return tuple(s.intent for s in self.steps)


@dataclass
class StepResult:
    """The real workflow response for one executed step, tagged with its intent.
    `response` is the untouched dict the existing workflow returned — the
    coordinator never reshapes a workflow's output, it only aggregates."""
    intent:   Intent
    response: dict
    ok:       bool = True


@dataclass
class ExecutionResult:
    """The executor's output. Either every planned step ran (`clarification`
    is None → the synthesizer builds a composite response), or execution
    stopped early because a step returned a clarification / could not proceed
    (`clarification` holds that existing, already-valid response, which the
    coordinator returns verbatim — Phase 1's 'safely return it' behavior)."""
    steps:         list[StepResult] = field(default_factory=list)
    clarification: Optional[dict] = None

    @property
    def halted(self) -> bool:
        return self.clarification is not None
