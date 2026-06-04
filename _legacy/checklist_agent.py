"""
CSULB Grad Center – Checklist Agent
Input:  guidance steps (output of guidance_agent.guide())
Output: flat checklist where every item has task + status
"""

from __future__ import annotations

import json
import sys
from typing import Any

from guidance_agent import guide_from_file


# ---------------------------------------------------------------------------
# Checklist item
# ---------------------------------------------------------------------------

VALID_STATUSES = {"pending", "in_progress", "completed"}


def _make_item(step: int, task: str, sub_items: list[str] | None = None,
               warning: str | None = None, resource: str | None = None) -> dict:
    item: dict[str, Any] = {
        "step": step,
        "task": task,
        "status": "pending",
    }
    if sub_items:
        item["sub_items"] = [{"task": t, "status": "pending"} for t in sub_items]
    if warning:
        item["warning"] = warning
    if resource:
        item["resource"] = resource
    return item


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------

def to_checklist(guidance: dict) -> dict:
    """
    Convert guidance_agent output into a checklist.

    Args:
        guidance: dict returned by guidance_agent.guide().

    Returns:
        Structured checklist JSON.
    """
    steps = guidance.get("steps", [])

    if not steps:
        return {
            "query": guidance.get("query", ""),
            "intent": guidance.get("intent", ""),
            "checklist": [],
            "total_items": 0,
            "source_file": guidance.get("source_file", ""),
            "source_url": guidance.get("source_url", ""),
        }

    checklist = []
    for s in steps:
        # Build sub-items from the details field when it contains a list separator
        details: str = s.get("details", "")
        sub_items: list[str] | None = None
        if details:
            # Semicolons or pipe characters separate parallel requirements
            if "|" in details:
                parts = [p.strip() for p in details.split("|") if p.strip()]
                if len(parts) > 1:
                    sub_items = parts
            elif ";" in details and details.count(";") >= 2:
                parts = [p.strip() for p in details.split(";") if p.strip()]
                sub_items = parts

        # Use the first warning (most critical) if present
        warnings = s.get("warnings", [])
        warning = warnings[0] if warnings else None

        # Use the first resource label + URL if present
        resources = s.get("resources", [])
        resource = f"{resources[0]['label']}: {resources[0]['url']}" if resources else None

        # Compose the task string as "Action — Details" when details add substance
        action: str = s.get("action", s.get("title", ""))
        task = action if sub_items else _compose_task(action, details)

        checklist.append(_make_item(
            step=s.get("step", len(checklist) + 1),
            task=task,
            sub_items=sub_items,
            warning=warning,
            resource=resource,
        ))

    return {
        "query": guidance.get("query", ""),
        "intent": guidance.get("intent", ""),
        "total_items": len(checklist),
        "checklist": checklist,
        "source_file": guidance.get("source_file", ""),
        "source_url": guidance.get("source_url", ""),
    }


def _compose_task(action: str, details: str) -> str:
    """
    Merge action and details into one readable task string.
    Avoids duplication when details merely restate the action.
    """
    if not details:
        return action
    # If details is a URL or very short, skip it
    if details.startswith("http") or len(details) < 10:
        return action
    # Truncate very long detail strings to keep the task scannable
    snippet = details if len(details) <= 120 else details[:117].rstrip() + "…"
    return f"{action} — {snippet}"


# ---------------------------------------------------------------------------
# Status helper (called by consuming code to update progress)
# ---------------------------------------------------------------------------

def update_status(checklist: dict, step: int, status: str,
                  sub_task: str | None = None) -> dict:
    """
    Return a new checklist dict with the given step's status updated.
    Optionally update a named sub-item instead of the parent step.

    Args:
        checklist:  Output of to_checklist().
        step:       1-based step number to update.
        status:     One of "pending", "in_progress", "completed".
        sub_task:   If set, update the matching sub-item task string instead.

    Returns:
        Updated checklist dict (mutates in place and returns it).
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")

    for item in checklist.get("checklist", []):
        if item["step"] == step:
            if sub_task:
                for sub in item.get("sub_items", []):
                    if sub["task"] == sub_task:
                        sub["status"] = status
                        break
            else:
                item["status"] = status
            break

    return checklist


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def build_checklist(query: str) -> dict:
    """Retrieve guidance and convert to checklist in one call."""
    guidance = guide_from_file(query)
    return to_checklist(guidance)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter your query: ")
    result = build_checklist(query)
    print(json.dumps(result, indent=2))
