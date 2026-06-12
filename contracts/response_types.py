"""
response_types.py
Typed contracts for every shape returned by orchestrator.run().

Pure annotation layer — no runtime enforcement, no Pydantic dependency.
Stdlib typing only (TypedDict). These TypedDicts document the implicit dict
contracts that existed in the codebase and make them verifiable by type
checkers and IDEs.

Route → TypedDict mapping
────────────────────────────────────
  None (empty query)  → WelcomeResponse
  "guidance"          → GuidanceResponse
  "answer"            → AnswerResponse
  "deadlines"         → TopicResponse
  "eligibility"       → TopicResponse
  "application"       → TopicResponse
  "advisor"           → AdvisorResponse
  "next_steps"        → NextStepsResponse
"""

from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Sub-shapes
# ---------------------------------------------------------------------------

class SourceInfo(TypedDict):
    file: str
    url:  str


class GuidanceStepItem(TypedDict):
    """Rich step shape returned by the guidance route."""
    number:    int | None        # None when source step is missing the "step" key
    do:        str               # imperative action phrase
    why:       str               # outcome / goal sentence
    details:   str
    prep:      list[str]         # what to have ready before starting
    how:       list[str]         # ordered sub-steps
    time:      str               # rough time estimate ("15–30 min")
    glossary:  dict[str, str]    # jargon → plain-English
    watch_out: str | None        # first warning; None when no warnings
    link:      str | None        # first resource URL; None when no resources


class SimpleStepItem(TypedDict):
    """Minimal step shape used by the next_steps route only."""
    number: int
    do:     str


class EmailDraft(TypedDict):
    found:       bool
    subject:     str
    body:        str
    to:          str
    outlook_url: str


# ---------------------------------------------------------------------------
# Base response — fields present on every non-empty response
# ---------------------------------------------------------------------------

class BaseResponse(TypedDict):
    query:          str
    route:          str
    session_id:     str
    summary:        str
    primary_action: str
    source:         SourceInfo
    next_actions:   list[str]


# ---------------------------------------------------------------------------
# Route-specific responses
# ---------------------------------------------------------------------------

class GuidanceResponse(BaseResponse):
    steps:       list[GuidanceStepItem]
    total_steps: int


class AnswerResponse(BaseResponse):
    answer:     Any   # str | dict | list — polymorphic, depends on answer_type
    confidence: str   # "high" | "medium" | "low"


class TopicResponse(BaseResponse):
    """Covers route="deadlines", "eligibility", and "application"."""
    tool_result: dict   # full raw tool output; each tool has its own schema


# AdvisorResponse uses the two-class pattern so email_draft can be optional.
# total=False applies only to fields defined *in that class*, not inherited
# ones — so all BaseResponse fields and advisor_data remain required.

class _AdvisorBase(BaseResponse):
    advisor_data: dict   # match, confidence, suggestions; optionally known_programs


class AdvisorResponse(_AdvisorBase, total=False):
    # email_draft is only present when the matched advisor has both name + email
    email_draft: EmailDraft


class NextStepsResponse(BaseResponse):
    steps:     list[SimpleStepItem]
    resources: list   # always [] currently; reserved for future use


# ---------------------------------------------------------------------------
# Welcome response — returned when query is empty.
# route=None and query/session_id are absent on this shape only.
# ---------------------------------------------------------------------------

class WelcomeResponse(TypedDict):
    route:          None
    summary:        str
    primary_action: str
    next_actions:   list[str]


# ---------------------------------------------------------------------------
# Union — the complete return type of orchestrator.run()
# ---------------------------------------------------------------------------

OrchestratorResponse = (
    WelcomeResponse
    | GuidanceResponse
    | AnswerResponse
    | TopicResponse
    | AdvisorResponse
    | NextStepsResponse
)
