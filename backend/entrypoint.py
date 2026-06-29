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

import orchestrator
from agents.journey_agent import handle_discovery, init_journey_state
from contracts.response_types import OrchestratorResponse
from state.context_manager import get_context


def _is_discovery_active(session_id: str) -> bool:
    """True when the next message for this session should continue an
    in-progress discovery clarification rather than be freshly routed."""
    context = get_context(session_id, default_factory=init_journey_state)
    return context.journey_state.get("phase") == "clarifying"


def handle_user_query(query: str, session_id: str = "default") -> OrchestratorResponse:
    """
    The single backend entry point for all incoming user requests.

    Resolves discovery continuation, then dispatches to either
    agents.journey_agent.handle_discovery() or orchestrator.run() — the same
    two functions every caller used directly before Phase 4F, just no
    longer with the caller deciding which one to use.
    """
    query = (query or "").strip()

    if _is_discovery_active(session_id):
        response, _ = handle_discovery(query, session_id)
        return response

    return orchestrator.run(query, session_id=session_id)
