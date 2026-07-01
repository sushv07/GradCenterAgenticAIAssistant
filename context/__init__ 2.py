"""
context — Trace Context for a single request's lifetime.

  trace_context.py — TraceContext: request_id/session_id/route/started_at
                      bundled into one object, created at the backend entry
                      point. Distinct from state.context_manager's
                      ConversationContext (session-scoped, persists across
                      requests) and from JourneyState (domain-scoped).
"""
