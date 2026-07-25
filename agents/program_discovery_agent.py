"""
agents/program_discovery_agent.py
Thin adapter over the existing discovery/recommendation workflow.

It adds NO recommendation logic of its own — it calls the lowest-level stable
handler, agents.journey_agent.handle_discovery(), which is the same function the
production discovery route already uses. handle_discovery() also persists the
resolved program into the shared JourneyState (active_program) via
state.context_manager, which is precisely how the coordinator's later
advisor/application steps reuse the discovered program without re-deriving it.
"""
from __future__ import annotations

from agents.journey_agent import handle_discovery


def run(query: str, session_id: str) -> dict:
    """Run the discovery workflow and return its response dict.

    handle_discovery() returns (response, state) and saves state internally; we
    only need the response — the persisted active_program is read back by the
    dependent steps through the normal context manager.
    """
    response, _state = handle_discovery(query, session_id)
    return response


def recommended(response: dict) -> bool:
    """Whether discovery actually resolved a single program to build on, versus
    asking a clarifying question or redirecting (broad/out-of-scope input). Used
    by the executor to decide whether dependent steps can proceed."""
    return response.get("behavior") == "recommend" and bool(response.get("program_matches"))
