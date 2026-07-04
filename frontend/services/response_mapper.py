"""
frontend/services/response_mapper.py
Translate raw backend JSON into a flat, UI-friendly dict.
"""
from __future__ import annotations


def map_response(raw: dict) -> dict:
    """
    Normalize a backend /query response into a UI-ready dict.

    All backend routes return:
        route:        str  — e.g. "guidance", "answer", "topic", ...
        summary:      str  — human-readable answer (present on all routes)
        source:       dict — {"file": str, "url": str}
        next_actions: list[str] — suggested follow-up questions

    The "answer" route additionally has:
        answer: Any — preferred as answer text when it is a non-empty string

    Returns:
        {
            "route":     str,
            "answer":    str,
            "sources":   list[dict],
            "followups": list[str],
            "raw":       dict,
        }
    """
    if not isinstance(raw, dict):
        return {
            "route": "", "answer": str(raw),
            "sources": [], "followups": [], "raw": {},
        }

    route = raw.get("route", "") or ""

    # Determine answer text
    answer = ""
    if route == "answer":
        candidate = raw.get("answer")
        if isinstance(candidate, str) and candidate.strip():
            answer = candidate.strip()

    if not answer:
        answer = (raw.get("summary") or "").strip()

    if not answer:
        answer = "I'm sorry, I didn't receive a response. Please try again."

    # Sources: normalize single source dict → list
    sources: list[dict] = []
    source = raw.get("source")
    if isinstance(source, dict) and (source.get("url") or source.get("file")):
        sources.append(source)

    # Follow-ups
    raw_actions = raw.get("next_actions", [])
    followups = (
        [a for a in raw_actions if isinstance(a, str)]
        if isinstance(raw_actions, list)
        else []
    )

    return {
        "route":     route,
        "answer":    answer,
        "sources":   sources,
        "followups": followups,
        "raw":       raw,
    }
