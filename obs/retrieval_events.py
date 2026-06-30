"""
obs/retrieval_events.py
Phase 8B — structured, stage-level retrieval observability events.

Five events, one per pipeline stage in rag/retriever.py:retrieve():

    retrieval.started       — query received, parameters resolved
    retrieval.vector_search — Chroma similarity search returned candidates
    retrieval.filtering     — MIN_RELEVANCE threshold applied
    retrieval.completed     — final result set assembled
    retrieval.failed        — vector store unavailable, or the search itself raised

Each wraps gradcenter_logging.emit() — no second logging system. The only
addition beyond emit()'s existing envelope (ts/level/event/request_id/
logger) is session_id, read from gradcenter_logging.get_session_id()
(Phase 8B's new ContextVar, set once per request in
backend.entrypoint.handle_user_query() — mirrors how request_id has always
worked) and retrieval_stage, a fixed string per event for easy log
filtering without parsing the event name itself.

Why ContextVar-based session_id instead of a new retrieve() parameter:
    rag.retriever.retrieve() is called from many places — four tools,
    retrieval/retriever_service.py, the Phase 8A eval runner, the CLI —
    several of which have no session_id at all (CLI usage, eval runs). A
    new required or optional parameter would mean touching every call
    site for a logging-only feature, or leaving it inconsistently
    populated. Reading an ambient ContextVar (the exact mechanism
    request_id already uses, and the same mechanism OpenTelemetry's own
    context propagation is built on) means retrieve()'s signature and
    every caller stay completely unchanged — true zero-risk additive
    instrumentation.

route is deliberately NOT part of this schema: by the time retrieve() is
called, routing/router.py has already decided a route, but there is no
similarly safe, already-existing ambient channel carrying it down to this
layer (unlike session_id, which backend/entrypoint.py already owns for
the whole request). page_type (already a parameter on most calls) is the
closest practical proxy and is included instead — see
ARCHITECTURE_ANALYSIS.md's Phase 8B section for the full reasoning.

Never logs retrieved chunk text — only metadata (counts, scores, ids,
page_types, elapsed time).
"""
from __future__ import annotations

from typing import Optional

from gradcenter_logging import emit, get_session_id


def _truncate_query(query: str) -> str:
    """Mirrors app.py's own _q_trunc convention — cap logged query length
    without splitting mid-word."""
    if len(query) <= 200:
        return query
    head = query[:200]
    return head.rsplit(" ", 1)[0] if " " in head else head


def emit_retrieval_started(
    query: str,
    k: int,
    min_score: float,
    page_type: Optional[str],
    program_name: Optional[str],
) -> None:
    emit(
        "retrieval.started", level="INFO",
        retrieval_stage="started",
        session_id=get_session_id(),
        query=_truncate_query(query),
        top_k=k,
        min_score=min_score,
        page_type=page_type or "",
        program_name=program_name or "",
    )


def emit_retrieval_vector_search(
    candidate_count: int,
    elapsed_ms: float,
    page_type: Optional[str],
) -> None:
    emit(
        "retrieval.vector_search", level="INFO",
        retrieval_stage="vector_search",
        session_id=get_session_id(),
        candidate_count=candidate_count,
        elapsed_ms=elapsed_ms,
        page_type=page_type or "",
    )


def emit_retrieval_filtering(
    candidate_count: int,
    survived_count: int,
    min_score: float,
) -> None:
    emit(
        "retrieval.filtering", level="INFO",
        retrieval_stage="filtering",
        session_id=get_session_id(),
        candidate_count=candidate_count,
        filtered_count=candidate_count - survived_count,
        survived_count=survived_count,
        min_score=min_score,
    )


def emit_retrieval_completed(
    returned_count: int,
    scores: list[float],
    chunk_ids: list[str],
    page_types: list[str],
    elapsed_ms: float,
) -> None:
    emit(
        "retrieval.completed", level="INFO" if returned_count else "WARNING",
        retrieval_stage="completed",
        session_id=get_session_id(),
        returned_count=returned_count,
        top_score=scores[0] if scores else 0.0,
        min_score_returned=min(scores) if scores else 0.0,
        max_score_returned=max(scores) if scores else 0.0,
        chunk_ids=chunk_ids,
        page_types=page_types,
        elapsed_ms=elapsed_ms,
    )


def emit_retrieval_failed(
    reason: str,
    error: str = "",
    error_type: str = "",
    elapsed_ms: float = 0.0,
) -> None:
    """reason: a short, fixed code — "store_unavailable" or "search_exception"
    — distinct from the free-text error/error_type, so failures can be
    grouped without string-matching error messages."""
    emit(
        "retrieval.failed", level="ERROR",
        retrieval_stage="failed",
        session_id=get_session_id(),
        reason=reason,
        error=error[:200],
        error_type=error_type,
        elapsed_ms=elapsed_ms,
    )
