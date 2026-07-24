"""
state/program_context.py
Shared program-context continuity for the assistant (generic, not per-program).

Problem it solves
─────────────────
Every route detects the program from the CURRENT message text only, so a
follow-up like "what is the deadline for this program" or "how do I apply to
it" carries no program and the route asks for clarification or falls back to
generic guidance — even though a program was just recommended or named.

Design
──────
One canonical `active_program` lives in JourneyState. This module is the single
place that (a) decides what the active program is for a given turn and (b)
produces an INTERNAL augmented query the existing stateless route tools can
consume, without changing the user-facing query.

Resolution precedence (mirrors the approved spec):
  a. explicit program named in the current query      → overrides, becomes active
  b. explicit clarification selection                  → handled by the caller
  c. single confident recommendation / route result    → set by the caller
  d. existing active program + a contextual reference  → reuse, augment the query
  e. otherwise unresolved                              → preserve normal clarification

Genericity
──────────
No program is special-cased. The program_id → tool_name bridge is DERIVED by
feeding each taxonomy canonical_name through the tools' own alias detector
(`tools.application_steps_tool._detect_program`), so DrPH / DPT / DNP / EdD /
PhD are just data flowing through the existing catalog + aliases.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, TypedDict

from contracts.journey_state import ActiveProgram, JourneyState

_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "program_taxonomy.json"

# Contextual references that point at the already-established active program.
# Only consulted when the current query names NO explicit program (explicit
# always wins). Phrase set + whole-word it/its/it's.
_REFERENCE_PHRASES = (
    "this program", "that program", "the program",
    "this degree", "that degree", "the degree",
    "this one", "that one",
)
_REFERENCE_WORD_RE = re.compile(r"\b(?:it|its|it's)\b", re.IGNORECASE)


def _detect_program(text: str) -> Optional[str]:
    """The tools' own alias detector — imported lazily to avoid import cycles."""
    from tools.application_steps_tool import _detect_program as _dp
    return _dp(text or "")


# ---------------------------------------------------------------------------
# Catalog + the generic program_id ↔ tool_name bridge
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _catalog() -> tuple[tuple[dict, ...], dict]:
    """Return (entries, by_tool_name).

    entries: one dict per taxonomy program {program_id, canonical_name, tool_name}
    by_tool_name: tool_name -> (program_id, canonical_name)  (reverse lookup)
    """
    try:
        data = json.loads(_TAXONOMY_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return (), {}
    progs = data["programs"] if isinstance(data, dict) and "programs" in data else data
    entries: list[dict] = []
    by_tool_name: dict[str, tuple[str, str]] = {}
    for p in progs:
        pid = p.get("program_id", "")
        cname = p.get("canonical_name", "")
        tool_name = _tool_name_for(pid, cname)
        entries.append({"program_id": pid, "canonical_name": cname, "tool_name": tool_name})
        if tool_name:
            by_tool_name.setdefault(tool_name, (pid, cname))
    return tuple(entries), by_tool_name


def _tool_name_for(program_id: str, canonical_name: str) -> str:
    """Derive the tools' program_name for a taxonomy program, generically.

    Reuses the existing alias detector: the canonical_name (or the id turned
    into words) is fed through _detect_program, which returns the tool name.
    Falls back to the canonical_name if no alias matches.
    """
    for probe in (canonical_name, (program_id or "").replace("-", " ")):
        if probe:
            tool_name = _detect_program(probe)
            if tool_name:
                return tool_name
    return canonical_name or program_id


def make_active_program(
    program_id: str = "",
    canonical_name: str = "",
    *,
    source: str,
    tool_name: str = "",
) -> ActiveProgram:
    """Build an ActiveProgram, deriving any missing field from the catalog."""
    if not tool_name:
        tool_name = _tool_name_for(program_id, canonical_name)
    if (not program_id or not canonical_name) and tool_name:
        _, by_tool_name = _catalog()
        pid, cname = by_tool_name.get(tool_name, ("", ""))
        program_id = program_id or pid
        canonical_name = canonical_name or cname
    return ActiveProgram(
        program_id=program_id,
        canonical_name=canonical_name,
        tool_name=tool_name,
        source=source,
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def query_uses_program_reference(query: str) -> bool:
    """True when the query points at 'the current program' via a pronoun/phrase
    ("this program", "it", …)."""
    q = (query or "").lower()
    if any(phrase in q for phrase in _REFERENCE_PHRASES):
        return True
    return bool(_REFERENCE_WORD_RE.search(query or ""))


def _program_topic_tokens() -> frozenset:
    """Union of the router's program-aware topic signals (advisor / deadline /
    eligibility / application). A program-less question containing one of these
    is a program-scoped follow-up that refers to the active program. Imported
    lazily from the router so the vocabulary stays single-sourced (no drift)."""
    from routing.router import (
        _ADVISOR_SIGNALS, _DEADLINE_SIGNALS, _ELIGIBILITY_SIGNALS,
        _PROCESS_STEP_SIGNALS,
    )
    return frozenset(_ADVISOR_SIGNALS) | frozenset(_DEADLINE_SIGNALS) \
        | frozenset(_ELIGIBILITY_SIGNALS) | frozenset(_PROCESS_STEP_SIGNALS)


def query_is_program_scoped_followup(query: str) -> bool:
    """True when the query asks about a program-scoped topic (advisor, deadline,
    eligibility, application) without naming a program — e.g. "Who is the
    advisor?", "What is the deadline?". Such a question refers to the active
    program even though it uses no pronoun. (Explicit program mentions are
    handled earlier, so they never reach this check.)"""
    toks = set(re.findall(r"[a-z]+", (query or "").lower()))
    return bool(toks & _program_topic_tokens())


def detect_explicit_program(query: str) -> Optional[ActiveProgram]:
    """If the current query explicitly names a known program, return it as an
    ActiveProgram (source=explicit_mention); else None."""
    tool_name = _detect_program(query)
    if not tool_name:
        return None
    return make_active_program(source="explicit_mention", tool_name=tool_name)


def augment_query_with_active_program(query: str, active_program: Optional[ActiveProgram]) -> str:
    """Append the active program's plain canonical name so the stateless tools
    resolve it.

    Uses `canonical_name` (e.g. "Nursing"), NOT the decorated `tool_name`
    (e.g. "Nursing (D.N.P.)"): the advisor fuzzy matcher rejects the decorated
    form for some programs, while the plain canonical name is recognized by
    every program-aware tool (advisor, deadlines, application) — the alias
    detector still matches it because the canonical name contains the alias.
    Falls back to tool_name if no canonical name is stored.

    Internal only — the user-facing query is never modified by this function's
    caller; the returned string is passed to the route/tool exclusively.
    """
    ap = active_program or {}
    program_name = ap.get("canonical_name") or ap.get("tool_name", "")
    if not program_name:
        return query
    return f"{query} {program_name}".strip()


class ProgramResolution(TypedDict):
    active:     Optional[ActiveProgram]  # the resolved active program (or None)
    tool_query: str                      # query to hand the route/tool (may be augmented)
    changed:    bool                     # True when `active` should be persisted to state


def resolve_program_context(query: str, journey_state: Optional[JourneyState]) -> ProgramResolution:
    """Resolve the active program for this turn and produce the tool query.

    Precedence:
      a. explicit program in `query`  → that program becomes active (override);
         tool_query is the ORIGINAL query (the program is already present).
      d. contextual reference + an existing active program → reuse it and
         augment the tool_query.
      e. otherwise → no change; tool_query is the original query (routes keep
         their normal clarification behavior).

    A broad subject that is not a known program alias never matches (a), so it
    can never overwrite a specific active program here.
    """
    existing = (journey_state or {}).get("active_program")

    explicit = detect_explicit_program(query)
    if explicit is not None:
        return ProgramResolution(active=explicit, tool_query=query, changed=True)

    # A pronoun/phrase reference OR a program-less program-scoped question
    # ("Who is the advisor?") resolves to the active program.
    if existing and (query_uses_program_reference(query)
                     or query_is_program_scoped_followup(query)):
        return ProgramResolution(
            active=existing,
            tool_query=augment_query_with_active_program(query, existing),
            changed=False,
        )

    return ProgramResolution(active=existing, tool_query=query, changed=False)


def update_active_program(journey_state: JourneyState, active_program: ActiveProgram) -> JourneyState:
    """Set the active program on the state (in place) and return it."""
    journey_state["active_program"] = active_program
    return journey_state
