"""
next_steps.py
Returns structured next-steps guidance for doctoral applicants.

Uses lightweight intent detection to select the right RAG source for
extra_guidance — FAQ dominates for orientation queries, admissions for
apply queries.  The enriched doctoral steps (steps 2, 5, 8 links etc.)
live in guidance_agent.py and are not affected by this module.

Usage:
    from next_steps import get_next_steps
    result = get_next_steps("I want to apply for a phd, where do I begin?")
"""

from __future__ import annotations

from typing import Optional

from retrieval.admissions_rag import admissions_rag_lookup
from retrieval.faq_rag_module import faq_rag_lookup


# ---------------------------------------------------------------------------
# Intent buckets
# ---------------------------------------------------------------------------

_START_INTENT  = ["start", "confused", "help", "begin", "stuck", "don't know", "lost", "overwhelmed"]
_CHOICE_INTENT = ["choose", "which program", "what should i study", "decide"]
_APPLY_INTENT  = ["apply", "application", "steps", "process"]


# ---------------------------------------------------------------------------
# Fixed base steps
# ---------------------------------------------------------------------------

_BASE_STEPS = [
    "Choose your doctoral program",
    "Review doctoral-specific application deadlines",
    "Prepare required documents (Statement of Purpose, transcripts, Letters of Recommendation)",
    "Submit your application via Cal State Apply",
    "Contact your program advisor for guidance",
]


# ---------------------------------------------------------------------------
# Guidance builder
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    """Strip whitespace and ensure the snippet ends with a period."""
    return text.strip().rstrip(".!?") + "."


def _build_extra_guidance(parts: list[str]) -> Optional[str]:
    """
    Join guidance parts into a clean 1–2 sentence string.
    Deduplicates identical entries and caps output at ~300 chars.
    Returns None if nothing useful was collected.
    """
    if not parts:
        return None

    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        key = p.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p.strip())

    combined = " ".join(unique)
    if len(combined) > 300:
        combined = combined[:297].rsplit(" ", 1)[0] + "…"

    return combined or None


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def format_next_steps(data: dict) -> str:
    """
    Format a get_next_steps() result dict into a clean, readable string.

    Args:
        data: dict returned by get_next_steps() — must have "steps" and
              optionally "extra_guidance".

    Returns:
        A single formatted string ready to display to the user.
    """
    lines: list[str] = []

    lines.append("For doctoral applicants, here are your next steps:")
    lines.append("")

    for i, step in enumerate(data.get("steps", []), start=1):
        lines.append(f"{i}. {step}")

    extra = data.get("extra_guidance")

    if extra:
        lines.append("")
        lines.append("Additional guidance:")
        lines.append(extra)
        lines.append("")
        lines.append("You can also ask me to find your program advisor.")
    else:
        lines.append("")
        lines.append("You can also ask me to find your program advisor or explore deadlines.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_next_steps(query: str) -> Optional[dict]:
    """
    Return structured next-steps guidance using lightweight intent detection.

    Intent routing (checked in priority order):
      START  → FAQ only. User is lost; orient them first.
      CHOICE → FAQ + soft advisor hint. User is deciding between programs.
      APPLY  → Admissions first, then FAQ. User is ready to act.

    The enriched doctoral steps (steps 2, 5, 8 with embedded links) are
    managed by guidance_agent.py and are unaffected by this function.

    Returns:
        {
            "type":           "next_steps",
            "steps":          [ ... ],       # fixed 5-item base list
            "extra_guidance": "..."          # intent-routed RAG tip, or None
        }
        or None if the query matches no intent bucket.
    """
    if not query or not query.strip():
        return None

    q = query.lower()

    is_start  = any(k in q for k in _START_INTENT)
    is_choice = any(k in q for k in _CHOICE_INTENT)
    is_apply  = any(k in q for k in _APPLY_INTENT)

    if not (is_start or is_choice or is_apply):
        return None

    guidance_parts: list[str] = []

    if is_start:
        # FAQ ONLY — do not let admissions override orientation messaging
        faq = faq_rag_lookup(query)
        if faq:
            tip = faq.get("guidance") or ""
            if tip:
                guidance_parts.append(tip)

    elif is_choice:
        # FAQ + soft advisor prompt
        faq = faq_rag_lookup(query)
        if faq:
            tip = faq.get("guidance") or ""
            if tip:
                guidance_parts.append(tip)
        guidance_parts.append(
            "You can also ask me to find a program advisor to discuss your options."
        )

    elif is_apply:
        # Admissions first, then FAQ
        admissions = admissions_rag_lookup(query)
        if admissions:
            snippet = (admissions.get("snippets") or [""])[0]
            if snippet:
                guidance_parts.append(_clean(snippet))

        faq = faq_rag_lookup(query)
        if faq:
            tip = faq.get("guidance") or ""
            if tip:
                guidance_parts.append(tip)

    return {
        "type":           "next_steps",
        "steps":          _BASE_STEPS,
        "extra_guidance": _build_extra_guidance(guidance_parts),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Query: ").strip()
    result = get_next_steps(q)

    if result is None:
        print("No next-steps guidance for that query.")
    else:
        print(json.dumps(result, indent=2))
