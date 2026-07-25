"""
coordination/detector.py
Deterministic composite-intent detection.

A request is "composite" when a single message carries the DISCOVERY intent
plus at least one dependent intent (ADVISOR and/or APPLICATION) — i.e. the user
asks us to recommend a program AND do something that depends on that program, in
one breath. That is exactly the class of request the coordinator adds value for;
everything else is left to the existing single-intent orchestration untouched.

Detection is pure keyword/verb matching — no model, no state, no side effects —
so it is trivially explainable and testable. It is intentionally conservative:
requiring DISCOVERY to be present guarantees a program gets resolved to feed the
dependent steps within the same turn, which keeps Phase 1 self-contained (no
reliance on pre-existing session state).
"""
from __future__ import annotations

import re

from coordination.contracts import Intent

# Each intent is signalled by any one of its phrases. Word-boundary anchored so
# "application" doesn't accidentally fire on unrelated substrings.
_INTENT_PATTERNS: dict[Intent, re.Pattern] = {
    Intent.DISCOVERY: re.compile(
        r"\b(recommend|suggest|which program|what program|find me a program|"
        r"best program|interested in|looking for a (?:program|degree))\b",
        re.IGNORECASE,
    ),
    Intent.ADVISOR: re.compile(
        r"\b(advisor|advisers?|faculty contact|who (?:is|would be) (?:the|my))\b",
        re.IGNORECASE,
    ),
    Intent.APPLICATION: re.compile(
        r"\b(apply|application|how (?:do|to) .*apply|admission steps|"
        r"application (?:steps|process))\b",
        re.IGNORECASE,
    ),
}


def detect_intents(query: str) -> set[Intent]:
    """The set of intents whose signal phrases appear in the query. Pure."""
    q = query or ""
    return {intent for intent, pat in _INTENT_PATTERNS.items() if pat.search(q)}


def is_composite(query: str) -> bool:
    """True when the coordinator should handle this request instead of the
    existing orchestration: DISCOVERY plus at least one dependent intent.

    Requiring DISCOVERY (not merely 'two or more intents') is deliberate for
    Phase 1 — a dependent step needs a resolved program, and discovery is what
    resolves one within the same turn. A bare "who is the advisor and how do I
    apply" (no discovery) is left to the existing routes, which already handle
    program continuity from prior turns.
    """
    intents = detect_intents(query)
    return Intent.DISCOVERY in intents and bool(intents & {Intent.ADVISOR, Intent.APPLICATION})
