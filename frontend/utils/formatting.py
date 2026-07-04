"""
frontend/utils/formatting.py
Pure-Python formatting helpers for the Streamlit UI.

No Streamlit imports — these are plain functions so they are easily
testable and reusable across components.
"""
from __future__ import annotations

from pathlib import Path


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

    Expected keys (all optional): ``page_type``, ``title``, ``file``, ``url``.

    Examples:
        {"page_type": "deadlines"}          → "Deadlines"
        {"title": "FAQ page"}               → "FAQ page"
        {"file": "grad_deadlines.txt"}      → "grad deadlines"
        {"url": "https://example.edu/faq"}  → "faq"
        {}                                  → "Source"
    """
    if "page_type" in source:
        return source["page_type"].replace("_", " ").title()
    if "title" in source:
        return safe_text(source.get("title"))
    if "file" in source:
        stem = Path(source["file"]).stem.replace("_", " ").replace("-", " ")
        return stem if stem.strip() else "Source"
    if "url" in source:
        path = source["url"].rstrip("/").rsplit("/", 1)[-1]
        label = path.replace("_", " ").replace("-", " ").replace(".html", "").replace(".htm", "")
        return label if label.strip() else "Source"
    return "Source"
