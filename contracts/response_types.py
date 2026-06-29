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
  "discovery"         → DiscoveryResponse
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
# Retrieval result contracts
# ---------------------------------------------------------------------------

class RetrievalResult(TypedDict, total=False):
    """
    Annotation-only base for retrieval backend return shapes.
    All fields optional (total=False) — backends fill what they have.
    Do NOT add confidence here until Phase 9D normalizes scores across all backends.
    """
    backend:    str   # "faq_rag" | "admissions" | "advisor" | "keyword"
    source_url: str   # canonical source page URL
    found:      bool  # True if backend returned usable content


class FaqRagResult(RetrievalResult, total=False):
    guidance: str  # markdown bullets with embedded [text](url) links
    source:   str  # URL alias for source_url — value IS a URL here


class AdmissionsRagResult(RetrievalResult, total=False):
    snippets: list[str]  # 1–3 actionable snippet strings
    source:   str        # literal label "admissions" — NOT a URL


class AdvisorRetrievalResult(RetrievalResult, total=False):
    match:       dict | None  # full advisor record or None
    confidence:  int          # RapidFuzz partial_ratio score 0–100
    suggestions: list[str]    # top-3 program names when no match found


class KeywordRetrievalResult(RetrievalResult, total=False):
    query:         str        # echoed user query
    matched_files: list[str]  # scored data file basenames
    results:       list[dict] # extracted section dicts from data files
    next_steps:    list[str]  # contextual next-step suggestions


# ---------------------------------------------------------------------------
# Retrieved chunk contract (Phase 4B — Retrieval Abstraction)
#
# RetrievalResult (above) is a per-backend ENVELOPE shape — each backend
# (faq_rag, admissions, advisor, keyword) has its own fields layered on top.
# RetrievedChunk is different: it is the single, normalized shape every
# backend's individual hits are converted INTO by the Retriever service in
# retrieval/retriever_service.py, so callers depend on one chunk shape
# regardless of which vector/keyword/fuzzy backend produced it.
# ---------------------------------------------------------------------------

class RetrievedChunk(TypedDict):
    """
    One normalized retrieval hit, backend-agnostic.

    text, title, url, and score are the fields every backend can populate
    (a vector store, a keyword matcher, or a future Pinecone/pgvector/Azure
    backend all have some notion of "matched text, where it came from, how
    confident"). Anything backend- or domain-specific (page_type,
    program_name, content_category, chunk_id, ...) lives in metadata so the
    top-level shape never has to grow per backend.
    """
    text:     str         # matched chunk text
    title:    str         # source page title ("" if unknown)
    url:      str         # citation URL ("" if unknown)
    score:    float       # relevance score in [0.0, 1.0]; backend-defined similarity metric
    metadata: dict         # backend/domain-specific extras (e.g. page_type, chunk_id)


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


class ProgramMatch(TypedDict, total=False):
    """Rich per-program result populated by Phase D recommendation engine."""
    program_id:    str
    confidence:    str         # "high" | "medium" | "low"
    advisor_email: str
    deadline_fall: str
    score_basis:   list[str]  # human-readable scoring factors


class _DiscoveryBase(BaseResponse):
    """Required fields for every discovery response."""
    recommended_programs: list[str]  # program_ids from program_taxonomy.json; [] when behavior="clarify"
    confidence:           str        # "high" | "medium" | "low" | "none"
    behavior:             str        # "recommend" | "multi_recommend" | "clarify" | "redirect" | "partial_match_with_caveat"


class DiscoveryResponse(_DiscoveryBase, total=False):
    # Present only when behavior="clarify" — the question to pose to the student next.
    clarification_question: str
    # Phase D fills this with per-program scoring details.
    program_matches: list[ProgramMatch]


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
    | DiscoveryResponse
)
