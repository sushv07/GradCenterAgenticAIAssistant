"""
responses/builder.py
Phase 4E — unified Response Builder.

Problem this solves:
    Six call sites assembled response dicts independently — orchestrator.py's
    _format_response() (guidance/answer), _build_topic_response() (deadlines/
    eligibility/application), _build_advisor_response() (advisor, 3 return
    paths), _build_next_steps_response() (next_steps), _dispatch()'s welcome
    branch, and agents/journey_agent.py's _build_response() (discovery).
    Every one of them builds the same handful of common fields — query,
    route, session_id, summary, primary_action, source, next_actions — by
    hand, then adds its own route-specific extra fields.

What this module does:
    build_response() assembles exactly those common fields plus whatever
    route-specific fields the caller passes in `extra`. It does not decide
    *what* summary/primary_action/extra fields should be — that business
    logic stays in orchestrator.py and journey_agent.py exactly as before.
    This module only owns final dict assembly.

What this module deliberately does NOT do (Phase 4E non-goals):
    - It does not invent new schemas — every field it writes already exists
      in contracts/response_types.py's TypedDicts.
    - It does not change response wording, routing, recommendation logic,
      retrieval, JourneyState, or scoring.
    - It does not enforce key ordering as meaningful — Python dict equality
      and every test/eval in this codebase compare fields by key, never by
      serialized text, so this module is free to assemble fields in one
      canonical order rather than reproducing each call site's original
      (and mutually inconsistent) literal order.

Usage:
    from responses.builder import build_response

    return build_response(
        query=query, route="deadlines", session_id=session_id,
        summary=summary, primary_action=primary_action,
        source={"file": "", "url": source_url},
        next_actions=next_actions,
        extra={"tool_result": result},
    )
"""
from __future__ import annotations

from typing import Optional


def build_response(
    *,
    route:          Optional[str],
    summary:        str,
    primary_action: str,
    next_actions:   list[str],
    query:          Optional[str] = None,
    session_id:     Optional[str] = None,
    source:         Optional[dict] = None,
    extra:          Optional[dict] = None,
) -> dict:
    """
    Assemble the common response envelope, then merge in route-specific fields.

    query, session_id, and source are omitted entirely when None — this
    reproduces the welcome response's existing shape (no query, no source
    key) without a special case here.
    """
    response: dict = {}

    if query is not None:
        response["query"] = query

    response["route"] = route

    if session_id is not None:
        response["session_id"] = session_id

    response["summary"]        = summary
    response["primary_action"] = primary_action

    if extra:
        response.update(extra)

    if source is not None:
        response["source"] = source

    response["next_actions"] = next_actions

    return response
