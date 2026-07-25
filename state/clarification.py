"""
state/clarification.py
Generic, reusable pending-clarification framework.

The assistant sometimes needs one piece of information before it can fulfil a
request (e.g. the applicant type before showing an application workflow). Rather
than a per-type boolean and a parallel resume path, a single typed
`PendingClarification` is stored on the session, and a small registry maps its
`kind` to a resumer that consumes the user's next reply. `backend.entrypoint`
dispatches through `resume()` — the ONE resume seam — so adding a new
clarification type is: register a resumer + set the pending object.

This module owns only the mechanism + the applicant-type parser; the resumers
themselves live where the response is built (orchestrator) and register at
import time.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from contracts.journey_state import JourneyState, PendingClarification

# ---------------------------------------------------------------------------
# Typed pending-clarification state helpers
# ---------------------------------------------------------------------------

def set_pending(journey_state: JourneyState, kind: str, **context) -> None:
    """Record that the assistant is awaiting a reply of type `kind`."""
    journey_state["pending_clarification"] = PendingClarification(kind=kind, **context)


def get_pending(journey_state: JourneyState) -> Optional[PendingClarification]:
    return journey_state.get("pending_clarification") or None


def clear_pending(journey_state: JourneyState) -> None:
    journey_state.pop("pending_clarification", None)


# ---------------------------------------------------------------------------
# Resumer registry — kind -> (query, session_id, pending) -> response | None
# ---------------------------------------------------------------------------

Resumer = Callable[[str, str, PendingClarification], Optional[dict]]
_RESUMERS: dict[str, Resumer] = {}


def register_resumer(kind: str, fn: Resumer) -> None:
    _RESUMERS[kind] = fn


def resume(query: str, session_id: str, pending: PendingClarification) -> Optional[dict]:
    """Dispatch a pending clarification's reply to its registered resumer.
    Returns the resumed response, or None when the kind has no resumer (caller
    then falls through to normal routing)."""
    fn = _RESUMERS.get((pending or {}).get("kind", ""))
    return fn(query, session_id, pending) if fn else None


# ---------------------------------------------------------------------------
# Applicant-type parsing (generic — no program specifics)
# ---------------------------------------------------------------------------

_INTERNATIONAL_RE = re.compile(
    r"\binternational\b|\bint'?l\b|\bf-?1\b|\bvisa\b|\bforeign\b|\bnon-?resident\b",
    re.IGNORECASE)
_DOMESTIC_RE = re.compile(
    r"\bdomestic\b|\bu\.?s\.?\s*(citizen|applicant|resident|national)\b|"
    r"\bin-?state\b|\bpermanent\s+resident\b|\bgreen\s+card\b",
    re.IGNORECASE)


def parse_applicant_type(query: str) -> Optional[str]:
    """Return "domestic" | "international" from a reply/statement, or None if
    the query does not unambiguously state an applicant type."""
    q = query or ""
    intl = bool(_INTERNATIONAL_RE.search(q))
    dom = bool(_DOMESTIC_RE.search(q))
    if intl and not dom:
        return "international"
    if dom and not intl:
        return "domestic"
    return None


# Words that signal the message is an actionable question/request, not merely a
# bare "I am an international student" status statement.
_ACTIONABLE_RE = re.compile(
    r"\b(what|how|when|where|which|who|why|show|list|deadline|deadlines|advisor|"
    r"advis|gpa|requirements?|eligib|apply|application|steps?|process|tuition|"
    r"cost|fee|curriculum|program|programs)\b",
    re.IGNORECASE)


def is_bare_applicant_statement(query: str) -> bool:
    """True when the message only states the applicant type (e.g. "international",
    "Actually, I am an international student") with no other actionable intent."""
    return parse_applicant_type(query) is not None and not _ACTIONABLE_RE.search(query or "")
