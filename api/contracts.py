"""
api/contracts.py
Phase 5D — explicit API contracts (Pydantic).

Problem this solves:
    Phase 5C's /query endpoint returned a bare dict with no response_model —
    a deliberate choice at the time to guarantee zero risk of FastAPI
    silently dropping fields, since contracts/response_types.py's
    OrchestratorResponse is a TypedDict union with a different shape per
    route. That meant the OpenAPI docs for /query showed no real schema.
    This module adds that schema back, as a faithful Pydantic mirror of
    each existing TypedDict — not a redesign.

Why these models live in api/, not contracts/:
    contracts/response_types.py's TypedDicts are an annotation-only layer
    (no runtime enforcement) used by the *backend* — orchestrator.py,
    agents/journey_agent.py, responses/builder.py. They predate this API
    and have nothing to do with HTTP. These Pydantic models exist purely so
    FastAPI can validate/document an HTTP response; the backend never
    imports this module, and this module never feeds business logic.

How each model was derived:
    Not copied from the TypedDict source blindly — verified against the
    REAL runtime dict for every route (welcome, guidance, answer, deadlines/
    eligibility/application, advisor with and without email_draft, next_steps,
    discovery both clarify and recommend). This caught one real discrepancy
    between the TypedDict contract and actual behavior: WelcomeResponse's
    TypedDict omits session_id, but orchestrator.py's actual welcome branch
    includes it (passed to responses.builder.build_response()). The model
    below reflects the real runtime shape, not the slightly-stale TypedDict
    comment, so response_model= cannot silently drop it.

Why every model allows extra fields:
    `model_config = ConfigDict(extra="allow")`. These are accurate mirrors
    today, but the whole point of "wrap, don't replace" is that the backend
    response is the source of truth. If a backend field is ever added that
    this mirror doesn't yet know about, extra="allow" means it still passes
    through in the JSON response instead of being silently dropped — the
    failure mode this module exists to prevent stays prevented even as the
    backend evolves out from under it. (OpenAPI docs will simply not
    advertise that field until this module is updated to match.)
"""
from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """
    query is required — handle_user_query() always needs a string (possibly
    empty; an empty query is valid and returns a WelcomeResponse, not an
    error, so no min_length is enforced here — that would be NEW validation
    behavior, not a mirror of an existing rule).
    session_id is optional; omitting it falls back to
    config.settings.DEFAULT_SESSION_ID, exactly as before this phase.
    No other constraints are added — there's no existing length/pattern
    rule on either field to mirror, and inventing one would be unnecessary
    validation the Phase 5D goal explicitly warns against.
    """
    query: str
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-shapes (mirror contracts/response_types.py exactly)
# ---------------------------------------------------------------------------

class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    file: str
    url: str


class GuidanceStepItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    number:    Optional[int] = None
    do:        str
    why:       str
    details:   str
    prep:      list[str]
    how:       list[str]
    time:      str
    glossary:  dict[str, str]
    watch_out: Optional[str] = None
    link:      Optional[str] = None


class SimpleStepItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    number: int
    do:     str


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="allow")
    found:       bool
    subject:     str
    body:        str
    to:          str
    outlook_url: str


class ProgramMatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    program_id:    Optional[str] = None
    confidence:    Optional[str] = None
    advisor_email: Optional[str] = None
    deadline_fall: Optional[str] = None
    score_basis:   Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Base fields shared by every non-welcome response
# ---------------------------------------------------------------------------

class _BaseResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    query:          str
    route:          str
    session_id:     str
    summary:        str
    primary_action: str
    source:         SourceInfo
    next_actions:   list[str]


# ---------------------------------------------------------------------------
# Route-specific response models
# ---------------------------------------------------------------------------

class WelcomeResponseModel(BaseModel):
    """
    route=None and query/source are absent here, matching
    contracts.response_types.WelcomeResponse. session_id IS included
    (Optional, since it's not in the TypedDict) because the real welcome
    response includes it — see this module's docstring.
    """
    model_config = ConfigDict(extra="allow")
    route:          None = None
    session_id:     Optional[str] = None
    summary:        str
    primary_action: str
    next_actions:   list[str]


class GuidanceResponseModel(_BaseResponseModel):
    steps:       list[GuidanceStepItem]
    total_steps: int


class AnswerResponseModel(_BaseResponseModel):
    answer:     Any
    confidence: str


class TopicResponseModel(_BaseResponseModel):
    """Covers route="deadlines", "eligibility", and "application"."""
    tool_result: dict


class AdvisorResponseModel(_BaseResponseModel):
    advisor_data: dict
    email_draft:  Optional[EmailDraft] = None


class NextStepsResponseModel(_BaseResponseModel):
    steps:     list[SimpleStepItem]
    resources: list


class DiscoveryResponseModel(_BaseResponseModel):
    recommended_programs:   list[str]
    confidence:              str
    behavior:                str
    clarification_question: Optional[str] = None
    program_matches:         Optional[list[ProgramMatch]] = None


# ---------------------------------------------------------------------------
# Union — mirrors contracts.response_types.OrchestratorResponse
# ---------------------------------------------------------------------------

QueryResponse = Union[
    WelcomeResponseModel,
    GuidanceResponseModel,
    AnswerResponseModel,
    TopicResponseModel,
    AdvisorResponseModel,
    NextStepsResponseModel,
    DiscoveryResponseModel,
]
