"""
api/app.py
Phase 5C — thin FastAPI service layer.

Problem this solves:
    The backend has had one entry point since Phase 4F
    (backend.entrypoint.handle_user_query()), centralized dependency
    construction since Phase 5B (backend.dependencies.get_dependencies()),
    and centralized configuration since Phase 5A — but the only way to
    reach any of it was a Python import (Streamlit, a test, an eval
    runner). This module exposes that same entry point over HTTP.

What this module does NOT do (Phase 5C non-goals):
    - No business logic. Every route is a direct, unmodified call into
      handle_user_query() — no reshaping, filtering, or reinterpreting of
      its return value.
    - No response schema redesign. Routes return the same plain dict
      handle_user_query() already returns; FastAPI serializes it via its
      default JSON encoder. No response_model is declared, deliberately —
      OrchestratorResponse is a TypedDict union with a different shape per
      route (welcome/guidance/answer/topic/advisor/next_steps/discovery);
      forcing that into one Pydantic response model would mean either a
      complex discriminated union duplicating contracts/response_types.py,
      or a permissive model that could silently drop/rename fields. A bare
      dict return guarantees byte-for-byte the same JSON shape as every
      other caller already gets.
    - No new validation behavior beyond what the backend already does.
      An empty query string is NOT rejected with a 422 — handle_user_query("")
      already returns a graceful WelcomeResponse, and this layer preserves
      that rather than inventing a stricter rule.
    - No authentication, no database, no Docker/deployment config, no
      custom exception handling — unhandled exceptions surface through
      FastAPI's own default 500 behavior, unchanged.

Ownership boundary:
    FastAPI owns: endpoint definitions, request validation (via QueryRequest),
    HTTP status codes (FastAPI's defaults — 200, 422, 500).
    Backend owns: everything else — routing, retrieval, recommendation,
    response construction. This file never imports orchestrator.py,
    agents/, routing/, or retrieval/ directly; it only knows about
    backend.entrypoint and backend.dependencies.

Run locally:
    uvicorn api.app:app --reload
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from backend.entrypoint import handle_user_query
from backend.dependencies import AppDependencies, get_dependencies
from config.settings import DEFAULT_SESSION_ID

app = FastAPI(title="CSULB Grad Center Assistant API")


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


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


@app.post("/query")
def query(
    req: QueryRequest,
    deps: AppDependencies = Depends(get_dependencies),
) -> dict:
    """The one functional endpoint. Thin wrapper over handle_user_query() —
    no logic of its own beyond defaulting session_id."""
    session_id = req.session_id or DEFAULT_SESSION_ID
    return handle_user_query(req.query, session_id=session_id, deps=deps)
