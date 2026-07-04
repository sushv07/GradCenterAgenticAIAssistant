"""
frontend/utils/formatting.py
Pure-Python formatting helpers for the Streamlit UI.

No Streamlit imports — these are plain functions so they are easily
testable and reusable across components.
"""
from __future__ import annotations


def safe_text(text: object) -> str:
    """
    Coerce any value to a non-empty string safe for display.

    Returns the string representation of *text*, or an em-dash if the
    result would be empty or the input was None.
    """
    if text is None:
        return "—"
    result = str(text).strip()
    return result if result else "—"


def format_source_label(source: dict) -> str:
    """
    Produce a short human-readable label for a retrieval source dict.

    Expected keys (all optional): ``page_type``, ``url``, ``title``.

    Examples:
        {"page_type": "deadlines", "url": "https://..."} → "Deadlines"
        {"title": "FAQ page"}                             → "FAQ page"
        {}                                                → "Source"

    Phase 10H.1: returns a placeholder. Full mapping in Phase 10H.2.
    """
    if "page_type" in source:
        return source["page_type"].replace("_", " ").title()
    if "title" in source:
        return safe_text(source.get("title"))
    return "Source"
