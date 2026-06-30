"""
api/app.py
Phase 5C — thin FastAPI service layer.
Phase 5D — explicit, Pydantic-backed API contracts (see api/contracts.py).

Problem this solves:
    The backend has had one entry point since Phase 4F
    (backend.entrypoint.handle_user_query()), centralized dependency
    construction since Phase 5B (backend.dependencies.get_dependencies()),
    and centralized configuration since Phase 5A — but the only way to
    reach any of it was a Python import (Streamlit, a test, an eval
    runner). This module exposes that same entry point over HTTP.

What this module does NOT do (Phase 5C/5D non-goals):
    - No business logic. Every route is a direct, unmodified call into
      handle_user_query() — no reshaping, filtering, or reinterpreting of
      its return value.
    - No response schema redesign. /query's response_model (api.contracts.
      QueryResponse) is a faithful Pydantic mirror of
      contracts/response_types.py's OrchestratorResponse union, verified
      against real runtime output for every route — not a new shape. Every
      mirrored model allows extra fields (extra="allow"), so even an
      imperfect or future-stale mirror cannot cause a field to be silently
      dropped from the actual HTTP response.
    - No new validation behavior beyond what the backend already does.
      An empty query string is NOT rejected with a 422 — handle_user_query("")
      already returns a graceful WelcomeResponse, and this layer preserves
      that rather than inventing a stricter rule.
    - No authentication, no database, no Docker/deployment config, no
      custom exception handling — unhandled exceptions surface through
      FastAPI's own default 500 behavior, unchanged.

Ownership boundary:
    FastAPI owns: endpoint definitions, request validation (QueryRequest),
    response documentation/validation (QueryResponse), HTTP status codes
    (FastAPI's defaults — 200, 422, 500).
    Backend owns: everything else — routing, retrieval, recommendation,
    response construction. This file never imports orchestrator.py,
    agents/, routing/, or retrieval/ directly; it only knows about
    backend.entrypoint, backend.dependencies, and api.contracts (which
    itself never imports backend code — see api/contracts.py's docstring).

Run locally:
    uvicorn api.app:app --reload
"""
from __future__ import annotations

from fastapi import Depends, FastAPI

from backend.entrypoint import handle_user_query
from backend.dependencies import AppDependencies, get_dependencies
from config.settings import DEFAULT_SESSION_ID
from api.contracts import QueryRequest, QueryResponse

app = FastAPI(title="CSULB Grad Center Assistant API")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> dict:
    """Service identity — confirms the API is reachable."""
    return {"service": "csulb-grad-center-assistant", "status": "ok"}


@app.get("/health")
def health() -> dict:
    """Liveness check. Deliberately does not exercise retrieval or the
    recommendation engine — that would make this a slow readiness probe,
    not a liveness check. Constructing AppDependencies still catches
    import-time wiring failures."""
    get_dependencies()
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse, response_model_exclude_unset=True)
def query(
    req: QueryRequest,
    deps: AppDependencies = Depends(get_dependencies),
) -> dict:
    """
    The one functional endpoint. Thin wrapper over handle_user_query() —
    no logic of its own beyond defaulting session_id. response_model
    documents and validates the shape; it does not change what's returned —
    every model in api.contracts.QueryResponse allows extra fields.

    response_model_exclude_unset=True matters here: several optional fields
    (program_matches, clarification_question, email_draft) are only present
    in the backend's dict when they apply — journey_agent._build_response()
    and orchestrator._build_advisor_response() literally omit the key
    otherwise, rather than setting it to None. Without exclude_unset, Pydantic
    would fill in the model's declared default (None) for any missing
    optional field and serialize it anyway, adding a key
    (e.g. "program_matches": null) that the real backend response never has
    — a real behavior change. exclude_unset keeps "key absent" and "key
    present with value null" distinct, exactly matching backend behavior
    (verified directly: see the Phase 5D output report's validation step).
    """
    session_id = req.session_id or DEFAULT_SESSION_ID
    return handle_user_query(req.query, session_id=session_id, deps=deps)
