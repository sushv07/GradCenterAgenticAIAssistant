"""
backend/entrypoint.py
Phase 4F — unified backend entry point.

Problem this solves:
    Streamlit's app.py decided, on every turn, whether the next query should
    bypass the router and go straight to handle_discovery() — by inspecting
    its own UI-level st.session_state["messages"] transcript
    (_should_continue_discovery() / _is_discovery_clarify()). That's a
    backend routing decision being made by the UI layer, which means any
    other caller (a test, an eval runner, a future FastAPI handler or CLI)
    had to either re-implement that same check or skip it and get different
    behavior than the Streamlit app.

What this module does:
    handle_user_query() is the one function every caller should use. It
    resolves whether discovery is already active for this session_id —
    using JourneyState.phase, which handle_discovery() already maintains —
    and either continues the journey or falls through to orchestrator.run().
    The continuation decision moves into the backend; the UI no longer makes
    it.

Why JourneyState.phase is sufficient (no new field needed):
    handle_discovery() already sets phase="clarifying" exactly when it
    returns behavior="clarify" (both from the Step 5 should_clarify() gate
    and the Step 6 Phase D clarify fallback — see agents/journey_agent.py),
    and sets phase="recommending" or phase="init" (redirect) on every other
    exit. Since handle_discovery() is the *only* code that ever writes
    JourneyState for a session, and the old UI check was itself only ever
    triggered by a previous handle_discovery() call, phase=="clarifying" is
    an exact backend-side reproduction of what _should_continue_discovery()
    computed from the UI transcript — confirmed by side-by-side comparison
    in the Phase 4F validation report.

What this module deliberately does NOT do (Phase 4F non-goals):
    - It does not change routing, recommendation, retrieval, or response
      wording — it only decides which of two existing functions to call.
    - It does not introduce FastAPI, LangGraph, LangChain, or dependency
      injection.
    - It does not add a new JourneyState field or a new session store.

Usage:
    from backend.entrypoint import handle_user_query
    response = handle_user_query(query, session_id=session_id)
"""
from __future__ import annotations

import time
from typing import Optional

import orchestrator
from agents.journey_agent import handle_discovery, init_journey_state
from contracts.response_types import OrchestratorResponse
from context.trace_context import TraceContext, create_trace_context, record_route
from config.settings import DEFAULT_SESSION_ID
from backend.dependencies import AppDependencies, get_dependencies
from responses.builder import build_response
from telemetry import metrics
from telemetry.tracing import set_attributes, traced
from gradcenter_logging import emit, set_session_id, set_request_id, new_request_id, get_request_id


def _is_discovery_active(session_id: str, deps: Optional[AppDependencies] = None) -> bool:
    """True when the next message for this session should continue an
    in-progress discovery clarification rather than be freshly routed."""
    deps = deps or get_dependencies()
    context = deps.context_manager.get_context(session_id, default_factory=init_journey_state)
    return context.journey_state.get("phase") == "clarifying"


def _resume_pending_clarification(
    query: str, session_id: str, deps: AppDependencies,
) -> Optional[OrchestratorResponse]:
    """The single resume seam. If the session is awaiting a reply to a pending
    clarification, dispatch the reply to its resumer and return the resumed
    response; otherwise return None so the caller routes the message normally.

    Two clarification mechanisms live under this one seam:
      1. The generic typed PendingClarification (state/clarification.py) — a
         resumer registry keyed by `kind` (e.g. applicant_type). New
         clarification types reuse this with no parallel path.
      2. The existing discovery continuation (phase == "clarifying") — kept as
         its own branch here rather than refactored into the typed object.
    """
    import state.clarification as clarification

    context = deps.context_manager.get_context(session_id, default_factory=init_journey_state)
    js = context.journey_state

    pending = clarification.get_pending(js)
    if pending:
        resumed = clarification.resume(query, session_id, pending)
        if resumed is not None:
            return resumed
        # resumer declined (reply wasn't the expected kind) → route normally

    if js.get("phase") == "clarifying":
        response, _ = handle_discovery(query, session_id)
        return response

    return None


def _maybe_run_coordinator(query: str, session_id: str) -> Optional[OrchestratorResponse]:
    """The single, flag-gated integration point for the Multi-Agent Coordinator
    (Version 2). Returns the coordinator's composite response ONLY when the flag
    is on AND the request is composite; otherwise None so the caller falls
    through to the existing orchestration, unchanged.

    The coordinator import is local (not module-level) so that: (1) with the flag
    off, the coordination package is never imported and adds zero startup cost or
    risk to the production path; and (2) the import edge stays strictly one-way —
    entrypoint → coordinator — with the coordinator never importing back from
    here, so no circular import is possible.
    """
    from config.settings import ENABLE_MULTI_AGENT_COORDINATOR
    if not ENABLE_MULTI_AGENT_COORDINATOR:
        return None
    from coordination import coordinator
    return coordinator.maybe_run(query, session_id)


def _build_error_response(query: str, session_id: str, exc: Exception) -> dict:
    """
    Phase 6A — the controlled fallback returned when routing/retrieval/
    recommendation raises anything unexpected. Logs the FULL exception
    detail server-side (so the failure is never hidden), but the returned
    `error` field is the exception's type name only — never the raw
    message or a traceback, which could leak internal details to a client.
    """
    emit("backend.unhandled_exception", level="ERROR",
         error=str(exc)[:500], error_type=type(exc).__name__, session_id=session_id)
    return build_response(
        query=query,
        route="error",
        session_id=session_id,
        summary="Something went wrong while processing your request.",
        primary_action="Please try again, or contact GraduateCenter@csulb.edu if this keeps happening.",
        source={"file": "", "url": "https://www.csulb.edu/graduate-center"},
        next_actions=[
            "Try rephrasing your question",
            "Ask about application deadlines",
            "Find my program advisor",
        ],
        extra={"error": type(exc).__name__},
    )


@traced("pipeline.request")
def handle_user_query(
    query: str,
    session_id: str = DEFAULT_SESSION_ID,
    deps: Optional[AppDependencies] = None,
) -> OrchestratorResponse:
    """
    The single backend entry point for all incoming user requests.

    Resolves discovery continuation, then dispatches to either
    agents.journey_agent.handle_discovery() or orchestrator.run() — the same
    two functions every caller used directly before Phase 4F, just no
    longer with the caller deciding which one to use.

    Phase 4G: also assembles a TraceContext (request_id/session_id/route/
    started_at) for this call. It is not yet returned or logged — see the
    Phase 4G output report — but every field on it reflects this real
    request, ready for a future caller (FastAPI, observability) to consume
    without any further redesign.

    Phase 5B: accepts an optional AppDependencies (deps). When omitted, the
    real production dependencies are constructed via get_dependencies() —
    identical to this function's pre-Phase-5B behavior. Passing a custom
    AppDependencies (e.g. with a fake context manager) lets a test exercise
    this function without touching the real session store.

    Phase 6A: this is the one place graceful degradation against unexpected
    exceptions belongs. Lower-level functions (handle_discovery(),
    orchestrator.run(), individual tools) are NOT each wrapped in their own
    try/except for this purpose — that would scatter defensive code across
    many call sites for no behavioral gain, and several callers (eval
    runners, tests) deliberately call those functions directly because they
    *want* a hard failure if something is broken, not a graceful fallback.
    This function is the single, designated boundary between "the backend
    might raise" and "the caller (UI, API) never sees an unhandled
    exception."

    Phase 8E: this is also the one place every production caller passes
    through (app.py's Streamlit UI, api/app.py's FastAPI endpoint, eval
    runners, the CLI), so it is the correct, single place to guarantee two
    things the Phase 8E traceability audit found missing:
      1. request_id is always populated. app.py already mints a fresh one
         unconditionally before calling in (new_request_id() +
         set_request_id() in _submit_query()) and api/app.py's /query
         handler now does the same (see api/app.py) — so this function
         mints one ONLY when none is already active, deliberately NOT
         unconditionally: app.py sets its own id before this call so that
         its request.start/request.complete events share one request_id
         with everything handle_user_query() does internally. Minting a
         second, different id in here unconditionally would silently
         split that one logical request into two disconnected groups in
         the logs — exactly the correlation breakage this phase exists to
         prevent. The conditional mint here is strictly a safety net for
         a caller that does NOT mint its own (a bare test or script
         calling this function directly) — every real production caller
         already mints explicitly, matching app.py's pattern.
      2. request.started / request.completed bookend events exist at the
         backend level. app.py already emits its own request.start /
         request.complete, but only around its own call into this
         function, and only for Streamlit traffic — and discovery
         continuation turns (the _is_discovery_active() branch below)
         never emit route.decision at all, so previously nothing in the
         logs recorded the route for those turns except the final
         in-memory response object. record_route() already computes the
         right value (trace.route); request.completed just logs it.
    Deliberately named request.started/.completed (not request.start/
    .complete) to stay visually and programmatically distinct from
    app.py's existing pair — no consumer of the old events is affected,
    and obs/request_trace.py treats both pairs as valid bookends.
    """
    deps = deps or get_dependencies()
    query = (query or "").strip()
    set_session_id(session_id)  # Phase 8B — lets retrieval (and future) observability
                                 # events correlate back to this session without a new
                                 # parameter threaded through every retrieval call site.
    if not get_request_id():
        set_request_id(new_request_id())
    trace: TraceContext = create_trace_context(session_id)

    _t0 = time.perf_counter()
    _q_trunc = query[:200].rsplit(" ", 1)[0] if len(query) > 200 and " " in query[:200] else query[:200]
    emit("request.started", level="INFO",
         session_id=session_id, query=_q_trunc, query_len=len(query))

    try:
        response = _resume_pending_clarification(query, session_id, deps)
        if response is None:
            response = _maybe_run_coordinator(query, session_id)
        if response is None:
            response = orchestrator.run(query, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 — last line of defense, by design
        response = _build_error_response(query, session_id, exc)

    record_route(trace, response.get("route"))

    _elapsed = round((time.perf_counter() - _t0) * 1000, 1)
    _had_error = bool(response.get("error"))
    emit("request.completed", level="WARNING" if _had_error else "INFO",
         session_id=session_id, route=trace.route or "",
         elapsed_ms=_elapsed, had_error=_had_error)

    # Pipeline (domain) metrics — recorded here, the single seam every caller
    # passes through, using the route/elapsed/error values already computed for
    # the request.completed log event above. Same data, second signal: the log
    # line is the per-request record; the metric is the aggregate. record_pipeline
    # only touches in-process Prometheus counters and never raises.
    metrics.record_pipeline(trace.route or "", _had_error, _elapsed / 1000.0)

    # Annotate the root pipeline.request span (opened by @traced) with the
    # values now known. Safe no-op when tracing is disabled.
    set_attributes(**{
        "session.id":     session_id,
        "route":          trace.route or "unknown",
        "query.len":      len(query),
        "pipeline.error": _had_error,
    })

    return response
