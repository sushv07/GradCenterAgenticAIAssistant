"""
context/trace_context.py
Phase 4G — Trace Context.

Problem this solves:
    Request metadata — session_id, request_id, route, timing — was scattered
    across layers with no shared object: app.py minted request_id into
    gradcenter_logging's contextvar; routing/router.py independently derived
    route for its own "route.decision" log event; app.py independently
    re-derived route from the final response for its own "request.complete"
    event; session_id was threaded as a plain string through every function
    signature but never appeared in a log line at all. Nothing tied these
    together as "the metadata for this one request."

What this module does:
    TraceContext bundles exactly those fields into one object, created once
    per call into backend.entrypoint.handle_user_query() — the single
    backend entry point established in Phase 4F.

Why this is NOT the same as state.context_manager.ConversationContext:
    ConversationContext (Phase 4D) wraps JourneyState — state that persists
    ACROSS requests for a session, stored in _SESSION_STORE. TraceContext
    represents ONE request's identity as it moves through the backend; it is
    created fresh every call and is discarded when that call returns. A
    session has many requests; each request gets its own TraceContext but
    they all share one ConversationContext.

Why this is NOT JourneyState:
    JourneyState is domain data (interests, academic_background, phase,
    etc.) — what the journey agent knows about a student. TraceContext
    carries no domain data at all; it only identifies and timestamps the
    request itself.

What this module deliberately does NOT do (Phase 4G non-goals):
    - It does not mint request_id — it reads whatever gradcenter_logging's
      existing set_request_id()/new_request_id() pair already produced.
      app.py is unchanged: it still mints and sets the id before calling
      into the backend, exactly as before.
    - It does not call emit() or change any existing logging event — see
      the Phase 4G output report's Step 7 for why this is deferred rather
      than wired in now.
    - It is not threaded into orchestrator.run(), handle_discovery(), or
      build_response()'s signatures — those are heavily used externally
      with plain session_id strings, and changing their signatures would be
      an unforced, behavior-risking change for no behavioral gain this phase.

Usage:
    from context.trace_context import create_trace_context, record_route

    trace = create_trace_context(session_id)
    # ... handle the request ...
    record_route(trace, response.get("route"))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from gradcenter_logging import get_request_id


@dataclass
class TraceContext:
    """
    One request's identity as it moves through the backend.

    request_id: whatever id gradcenter_logging has active for this request
                (set by app.py before calling the backend; "" if none was set
                — e.g. for tests/eval runners that call the backend directly,
                matching their existing logging behavior exactly).
    session_id: the conversation this request belongs to.
    route:      None until the request has been routed; set once known.
    started_at: when this TraceContext was created (UTC).
    """
    request_id: str
    session_id: str
    route:      Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def create_trace_context(session_id: str) -> TraceContext:
    """Create a TraceContext for a new request, capturing the currently-active
    request_id (if any) without minting a new one."""
    return TraceContext(request_id=get_request_id(), session_id=session_id)


def record_route(trace: TraceContext, route: Optional[str]) -> TraceContext:
    """Stamp the route a request resolved to, once known. Returns trace for
    convenient chaining; mutates in place."""
    trace.route = route
    return trace
