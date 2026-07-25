"""
agents/advisor_agent.py
Thin adapter over the existing advisor-lookup workflow.

It calls orchestrator.run() — the stable public seam — with a canonical,
continuity-recognized prompt ("Who is the advisor?"). orchestrator.run() is used
deliberately rather than any lower function: it is the single place that composes
active-program augmentation (resolving the discovered program) + routing +
advisor response building. The lower pieces (_build_advisor_response, find_advisor
against an augmented query) are private and would require re-implementing that
composition here — exactly the duplication the coordinator must avoid.
"""
from __future__ import annotations

import orchestrator


def run(prompt: str, session_id: str) -> dict:
    """Resolve the advisor for the session's active program via the existing
    advisor route. The active program was set by the discovery step earlier in
    the same session, so the pronoun/bare prompt resolves to it."""
    return orchestrator.run(prompt, session_id=session_id)
