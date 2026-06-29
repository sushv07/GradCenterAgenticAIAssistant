"""
state/context_manager.py
Phase 4D — Context Manager.

Problem this solves:
    Conversation state previously had no single owner. The actual cross-turn
    backend state — JourneyState — lived as a module-level dict
    (_SESSION_STORE) inside agents/journey_agent.py, mutated directly at
    four call sites inside handle_discovery(). Everything else that looks
    like "session state" (Streamlit's st.session_state in app.py) is a
    UI-layer concern that never crosses into the backend.

What this module does:
    Owns the per-session JourneyState store and exposes a single resolve/
    persist API — get_context() / save_context() — built around a small
    ConversationContext value object. agents/journey_agent.py now imports
    its session store from here instead of defining its own.

What this module deliberately does NOT do (Phase 4D non-goals):
    - It does not change JourneyState's fields or schema.
    - It does not change routing, recommendation, retrieval, or scoring.
    - It does not change UI behavior — st.session_state in app.py is
      untouched; this module has no knowledge of it.
    - It does not model conversation history. No backend-owned transcript
      exists today (only the UI-level message list in app.py), so
      ConversationContext does not invent a history field.
    - It does not introduce Redis, a database, or any persistence beyond
      the same in-memory, process-scoped dict that existed before.

Usage:
    from state.context_manager import get_context, save_context

    context = get_context(session_id, default_factory=init_journey_state)
    # ... mutate context.journey_state ...
    save_context(session_id, context.journey_state)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from contracts.journey_state import JourneyState


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------
# Ephemeral, process-scoped — identical in nature to the dict this replaces
# inside agents/journey_agent.py. Not thread/process-safe; same as before.

_SESSION_STORE: dict[str, JourneyState] = {}


# ---------------------------------------------------------------------------
# ConversationContext
# ---------------------------------------------------------------------------

@dataclass
class ConversationContext:
    """
    The resolved conversation context for one turn.

    Fields mirror exactly what already flows through orchestrator.run() and
    handle_discovery() today. No additional fields (history, request
    metadata) are included because no backend-owned equivalent exists yet —
    see the module docstring.
    """
    session_id:    str
    journey_state: JourneyState


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_context(
    session_id: str,
    default_factory: Callable[[str], JourneyState],
) -> ConversationContext:
    """
    Resolve the ConversationContext for a session.

    Returns the stored JourneyState if one exists, otherwise constructs a
    fresh one via default_factory(session_id) — the same
    "stored or init" pattern handle_discovery() used directly against
    _SESSION_STORE before Phase 4D.
    """
    journey_state = _SESSION_STORE.get(session_id)
    if journey_state is None:
        journey_state = default_factory(session_id)
    return ConversationContext(session_id=session_id, journey_state=journey_state)


def save_context(session_id: str, journey_state: JourneyState) -> None:
    """Persist a JourneyState for a session. Overwrites any prior value."""
    _SESSION_STORE[session_id] = journey_state


def clear_context(session_id: str) -> None:
    """
    Remove any stored state for a session. No-op if none exists.

    Phase 4H: added because every caller that needed to reset a session
    (test setup/teardown, eval-runner fresh-session-per-case) was reaching
    into _SESSION_STORE directly with .pop(session_id, None) — bypassing
    this module's API even though get_context()/save_context() already
    existed. Swapping the in-memory dict for Redis/a database later means
    this is the only function that needs to change.
    """
    _SESSION_STORE.pop(session_id, None)
