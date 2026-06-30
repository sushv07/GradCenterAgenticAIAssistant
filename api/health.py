"""
api/health.py
Phase 5E — health and readiness check logic.

Problem this solves:
    GET /health (Phase 5C) only confirmed the process is up enough to
    construct AppDependencies — it never checked whether the backend's
    actual components (config, taxonomy file, context manager, vector
    store) are in a state where requests would actually succeed. There was
    no way to distinguish "the process is alive" from "the process can
    serve real traffic."

What this module does:
    Liveness (build_health_response): the process is running. Nothing more
    to check — if this code executes, the answer is "ok" by definition.

    Readiness (build_readiness_response): runs five independent,
    deterministic checks and aggregates them into one status:
        - configuration  — config.settings loaded with sane values
        - dependencies   — backend.dependencies.get_dependencies() succeeds
        - taxonomy_file  — the program taxonomy JSON exists and parses
        - context_manager — a session_id round-trips through
                              get_context/save_context/clear_context
        - vector_store   — rag.store.get_or_build_store() returns a store

    Each check is wrapped so one failing check cannot crash the others or
    the endpoint itself — every check independently reports ok/detail, and
    the aggregate status is "ok" (all pass), "degraded" (some pass), or
    "unavailable" (none pass).

Why vector_store calls get_or_build_store() instead of a passive disk check:
    get_or_build_store() is the same lazy-singleton every real query already
    goes through (rag/retriever.py -> rag/store.py). If it's already loaded
    (the common case once the app has served any RAG-backed query), this is
    instant. If not yet loaded but the on-disk store is fresh (within
    config.settings.CHROMA_STORE_TTL_SECONDS), it's a normal disk load — the
    same cost the first real query would pay regardless of whether this
    check exists. The one edge case where this is more expensive (on-disk
    store stale/missing -> full rebuild) is pre-existing behavior of
    get_or_build_store() itself; this check does not introduce that
    behavior, only observes it. Deliberately NOT performing an actual
    similarity search here — that would be "an expensive query" in the
    sense Phase 5E's non-goals warn against, and is unnecessary to answer
    "is the store accessible."

Why no business logic lives here:
    Every check calls existing backend functions unmodified
    (get_dependencies(), get_context()/save_context()/clear_context(),
    rag.store.get_or_build_store()) and only inspects their return values.
    Nothing here recomputes or reinterprets backend state.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from api.contracts import CheckResult, HealthResponse, ReadinessResponse
from backend.dependencies import get_dependencies
from agents.journey_agent import init_journey_state
from config.settings import DEFAULT_SESSION_ID, PROGRAM_TAXONOMY_PATH

_SERVICE_NAME = "csulb-grad-center-assistant"
_READINESS_SENTINEL_SESSION_ID = "__readiness_check__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_configuration() -> CheckResult:
    try:
        if not DEFAULT_SESSION_ID or not isinstance(DEFAULT_SESSION_ID, str):
            return CheckResult(ok=False, detail="DEFAULT_SESSION_ID is empty or not a string")
        if not PROGRAM_TAXONOMY_PATH:
            return CheckResult(ok=False, detail="PROGRAM_TAXONOMY_PATH is not set")
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001 — a check must never raise
        return CheckResult(ok=False, detail=str(exc))


def _check_dependencies() -> CheckResult:
    try:
        deps = get_dependencies()
        if deps.retriever is None or deps.context_manager is None or deps.response_builder is None:
            return CheckResult(ok=False, detail="one or more AppDependencies fields are None")
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(ok=False, detail=str(exc))


def _check_taxonomy_file() -> CheckResult:
    try:
        if not PROGRAM_TAXONOMY_PATH.exists():
            return CheckResult(ok=False, detail=f"not found: {PROGRAM_TAXONOMY_PATH}")
        with PROGRAM_TAXONOMY_PATH.open() as f:
            data = json.load(f)
        if "programs" not in data:
            return CheckResult(ok=False, detail="taxonomy JSON missing 'programs' key")
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(ok=False, detail=str(exc))


def _check_context_manager() -> CheckResult:
    try:
        deps = get_dependencies()
        cm = deps.context_manager
        cm.clear_context(_READINESS_SENTINEL_SESSION_ID)
        ctx = cm.get_context(_READINESS_SENTINEL_SESSION_ID, default_factory=init_journey_state)
        cm.save_context(_READINESS_SENTINEL_SESSION_ID, ctx.journey_state)
        cm.clear_context(_READINESS_SENTINEL_SESSION_ID)
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(ok=False, detail=str(exc))


def _check_vector_store() -> CheckResult:
    try:
        from rag.store import get_or_build_store
        store = get_or_build_store()
        if store is None:
            return CheckResult(ok=False, detail="get_or_build_store() returned None")
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(ok=False, detail=str(exc))


def _run_check(fn) -> CheckResult:
    """
    Defense in depth: every _check_* function already wraps its own body in
    try/except, but a readiness endpoint must never 500 under any
    circumstance — including a check that fails in some way its own
    try/except didn't anticipate. This second layer guarantees that.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(ok=False, detail=str(exc))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_health_response() -> HealthResponse:
    return HealthResponse(status="ok", service=_SERVICE_NAME, timestamp=_now_iso())


def build_readiness_response() -> ReadinessResponse:
    # Each check is looked up by module-level name at call time (not via a
    # dict built once at import time) so tests can patch e.g.
    # api.health._check_vector_store and have it actually take effect.
    checks = {
        "configuration":   _run_check(_check_configuration),
        "dependencies":    _run_check(_check_dependencies),
        "taxonomy_file":   _run_check(_check_taxonomy_file),
        "context_manager": _run_check(_check_context_manager),
        "vector_store":    _run_check(_check_vector_store),
    }
    passed = sum(1 for c in checks.values() if c.ok)

    if passed == len(checks):
        status = "ok"
    elif passed == 0:
        status = "unavailable"
    else:
        status = "degraded"

    return ReadinessResponse(
        status=status, service=_SERVICE_NAME, timestamp=_now_iso(), checks=checks
    )
