"""
CSULB Grad Center – Tracking System
Stores full guidance steps per session, marks items complete, and surfaces pending tasks.

Storage:
    ./sessions/<session_id>.json  (one JSON file per session)

Schema:
    Each session stores the full GuidanceStep objects (id, step, title, action,
    primary_action, details, priority, status, depends_on, prep, how, time,
    outcome, glossary, warnings, resources).

Operations:
    save(session_id, guidance_result)         persist guidance steps
    load(session_id)                          read it back
    mark(session_id, step_ref, status)        update one item's status
                                              step_ref: int (step number) or str (step id)
    pending(session_id)                       only items still pending / in_progress
    progress(session_id)                      completion summary
    list_sessions()                           all stored session ids
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guidance_agent import guide_from_file, validate_steps


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

VALID_STATUSES = {"pending", "in_progress", "completed"}

# Lower number = shown first in the pending list
_PRIORITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------------------
# Storage primitives
# ---------------------------------------------------------------------------

def _path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in session_id)
    return SESSIONS_DIR / f"{safe}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read(session_id: str) -> dict | None:
    path = _path(session_id)
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def _write(session_id: str, data: dict) -> None:
    data["updated_at"] = _now()
    with _path(session_id).open("w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save(session_id: str, guidance_result: dict) -> dict:
    """
    Persist guidance steps under session_id. Overwrites any existing session.

    Accepts the full dict returned by guide_from_file() — expects a 'steps' key
    containing full GuidanceStep dicts (id, step, title, action, primary_action,
    details, priority, status, depends_on, prep, how, time, outcome, glossary,
    warnings, resources).
    """
    steps = guidance_result.get("steps") or []

    # Ensure every step has the required workflow fields (defensive defaults)
    for i, step in enumerate(steps):
        step.setdefault("id", f"step-{step.get('step', i + 1)}")
        step.setdefault("priority", "medium")
        step.setdefault("depends_on", [])
        step.setdefault("status", "pending")

    # Validate dependency graph before persisting
    if steps:
        errors = validate_steps(steps)
        if errors:
            raise ValueError(
                f"Cannot save session '{session_id}' — "
                f"step validation failed ({len(errors)} error(s)):\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    record = {
        "session_id":  session_id,
        "created_at":  _now(),
        "updated_at":  _now(),
        "query":       guidance_result.get("query", ""),
        "intent":      guidance_result.get("intent", ""),
        "source_file": guidance_result.get("source_file", ""),
        "source_url":  guidance_result.get("source_url", ""),
        "steps":       steps,
    }
    _write(session_id, record)
    return record


def load(session_id: str) -> dict | None:
    """Return the stored session record, or None if it doesn't exist."""
    return _read(session_id)


def mark(session_id: str, step_ref: int | str, status: str) -> dict:
    """
    Update a step's status. Returns the updated record.

    step_ref:
        int  → match by step number  (e.g. 3)
        str  → match by step id      (e.g. "apply-3")

    status: "pending" | "in_progress" | "completed"
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")

    record = _read(session_id)
    if record is None:
        raise KeyError(f"No session found for id={session_id!r}")

    steps = record.get("steps", [])
    found = False
    for step in steps:
        if isinstance(step_ref, int):
            matched = step.get("step") == step_ref
        else:
            matched = step.get("id") == step_ref
        if matched:
            step["status"] = status
            found = True
            break

    if not found:
        valid_refs = [(s.get("step"), s.get("id")) for s in steps]
        raise KeyError(
            f"No step matching {step_ref!r} in session {session_id!r}. "
            f"Valid refs: {valid_refs}"
        )

    _write(session_id, record)
    return record


def pending(session_id: str) -> dict:
    """
    Return only the pending (and in_progress) steps for a session, each
    annotated with `is_blocked` and `blocked_by` (list of unmet prereq refs).
    """
    record = _read(session_id)
    if record is None:
        raise KeyError(f"No session found for id={session_id!r}")

    steps         = record.get("steps", [])
    completed_ids = _completed_ids(steps)

    pending_steps: list[dict] = []
    blocked_count = 0
    ready_count   = 0
    for step in steps:
        if step.get("status") in {"pending", "in_progress"}:
            annotated = _annotate_step(step, steps, completed_ids)
            pending_steps.append(annotated)
            if annotated["is_blocked"]:
                blocked_count += 1
            else:
                ready_count += 1

    # Sort: high → medium → low, then by step number within the same priority
    pending_steps.sort(
        key=lambda s: (
            _PRIORITY_ORDER.get(s.get("priority", "medium"), 1),
            s.get("step", 0),
        )
    )

    return {
        "session_id":    session_id,
        "intent":        record.get("intent", ""),
        "pending":       pending_steps,
        "pending_count": len(pending_steps),
        "ready_count":   ready_count,
        "blocked_count": blocked_count,
        "total":         len(steps),
    }


def progress(session_id: str) -> dict:
    """Return completion summary for a session, including blocked / ready counts."""
    record = _read(session_id)
    if record is None:
        raise KeyError(f"No session found for id={session_id!r}")

    steps         = record.get("steps", [])
    completed_ids = _completed_ids(steps)
    counts: dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0}
    blocked_count = 0
    ready_count   = 0
    for step in steps:
        status = step.get("status", "pending")
        counts[status] += 1
        if status in {"pending", "in_progress"}:
            if _blocked_by(step, steps, completed_ids):
                blocked_count += 1
            else:
                ready_count += 1

    total = len(steps)
    pct   = round(100 * counts["completed"] / total, 1) if total else 0.0

    current_raw       = _current_item(record)
    current_annotated = (
        _annotate_step(current_raw, steps, completed_ids) if current_raw else None
    )

    return {
        "session_id":   session_id,
        "intent":       record.get("intent", ""),
        "total":        total,
        "completed":    counts["completed"],
        "in_progress":  counts["in_progress"],
        "pending":      counts["pending"],
        "to_go":        counts["in_progress"] + counts["pending"],
        "ready":        ready_count,
        "blocked":      blocked_count,
        "percent_done": pct,
        "next_action":  _next_action(record),
        "current_item": current_annotated,
        "updated_at":   record.get("updated_at", ""),
    }


def list_sessions() -> list[dict]:
    """List every saved session with a one-line summary."""
    sessions = []
    for path in sorted(SESSIONS_DIR.glob("*.json")):
        with path.open() as f:
            data = json.load(f)
        # Support both new 'steps' key and legacy 'checklist' key
        steps = data.get("steps") or data.get("checklist", [])
        total = len(steps)
        completed = sum(1 for s in steps if s.get("status") == "completed")
        sessions.append({
            "session_id": data.get("session_id", path.stem),
            "intent":     data.get("intent", ""),
            "completed":  completed,
            "total":      total,
            "updated_at": data.get("updated_at", ""),
        })
    return sessions


def delete(session_id: str) -> bool:
    """Delete a saved session. Returns True if it existed."""
    path = _path(session_id)
    if not path.exists():
        return False
    path.unlink()
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed_ids(steps: list[dict]) -> set[str]:
    """Set of ids of steps already marked completed."""
    return {s.get("id", "") for s in steps if s.get("status") == "completed"}


def _blocked_by(step: dict, all_steps: list[dict],
                completed_ids: set[str]) -> list[dict]:
    """
    Return list of unmet prerequisite refs for this step.
    Each ref: {"step": <number>, "id": <id>, "title": <title>}.
    Empty list = step is ready.
    """
    deps = step.get("depends_on", []) or []
    if not deps:
        return []

    by_id = {s.get("id"): s for s in all_steps if s.get("id")}
    unmet: list[dict] = []
    for dep_id in deps:
        if dep_id in completed_ids:
            continue
        dep_step = by_id.get(dep_id)
        if dep_step is None:
            continue
        unmet.append({
            "step":  dep_step.get("step"),
            "id":    dep_id,
            "title": dep_step.get("title") or dep_step.get("action", ""),
        })
    return unmet


def _annotate_step(step: dict, all_steps: list[dict],
                   completed_ids: set[str]) -> dict:
    """Return a copy of `step` with `blocked_by` and `is_blocked` added."""
    blockers = _blocked_by(step, all_steps, completed_ids)
    return {**step, "blocked_by": blockers, "is_blocked": bool(blockers)}


def _next_action(record: dict) -> str | None:
    """First in_progress step, else first pending step, else None."""
    for status in ("in_progress", "pending"):
        for step in record.get("steps", []):
            if step.get("status") == status:
                title = step.get("title") or step.get("action", "")
                step_id = step.get("id", "")
                return f"Step {step.get('step')} [{step_id}]: {title}"
    return None


def _current_item(record: dict) -> dict | None:
    """Return the full dict of the current focus step (in_progress first, else first pending)."""
    for status in ("in_progress", "pending"):
        for step in record.get("steps", []):
            if step.get("status") == status:
                return step
    return None


# ---------------------------------------------------------------------------
# Convenience: build + save in one call
# ---------------------------------------------------------------------------

def start_session(session_id: str, query: str) -> dict:
    """Build guidance steps from a query and store as a new session."""
    guidance_result = guide_from_file(query)
    return save(session_id, guidance_result)


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

_BOX = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
_PRI = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def format_pending(view: dict) -> str:
    ready   = view.get("ready_count", view["pending_count"])
    blocked = view.get("blocked_count", 0)
    line2   = f"Pending: {view['pending_count']} of {view['total']}  (✅ {ready} ready"
    if blocked:
        line2 += f", 🔒 {blocked} blocked)"
    else:
        line2 += ")"

    lines = [
        f"Session: {view['session_id']}  ({view['intent']})",
        line2,
        "",
    ]
    if not view["pending"]:
        lines.append("✓ All tasks completed.")
        return "\n".join(lines)

    for step in view["pending"]:
        box        = _BOX[step.get("status", "pending")]
        title      = step.get("title") or step.get("action", "")
        step_id    = step.get("id", "")
        priority   = step.get("priority", "medium")
        pri_icon   = _PRI.get(priority, "")
        is_blocked = step.get("is_blocked")
        block_icon = "🔒 " if is_blocked else ""

        lines.append(
            f"  {box} {block_icon}{step.get('step')}. {title}  {pri_icon}  [{step_id}]"
        )

        if is_blocked:
            for prereq in step.get("blocked_by", []):
                lines.append(
                    f"        ⛔ Blocked: complete Step {prereq['step']} "
                    f"({prereq['title']}) first  [{prereq['id']}]"
                )
        elif step.get("depends_on"):
            lines.append(f"        ↳ Requires: {', '.join(step['depends_on'])}")

        if step.get("warnings"):
            lines.append(f"        ⚠  {step['warnings'][0]}")
    return "\n".join(lines)


def format_progress(p: dict) -> str:
    bar_len = 24
    done = int(round(bar_len * p["percent_done"] / 100))
    bar = "█" * done + "░" * (bar_len - done)

    breakdown = (
        f"({p['in_progress']} in progress, {p['pending']} pending"
        + (f", 🔒 {p['blocked']} blocked" if p.get("blocked") else "")
        + ")"
    )
    lines = [
        f"Session: {p['session_id']}  ({p['intent']})",
        f"[{bar}]  {p['percent_done']}%   "
        f"{p['completed']}/{p['total']} done  {breakdown}",
    ]

    current = p.get("current_item") or {}
    if current.get("is_blocked"):
        blockers = current.get("blocked_by", [])
        blocker_text = ", ".join(
            f"Step {b['step']} ({b['title']})" for b in blockers
        )
        lines.append(f"⛔ Next focus blocked: {p.get('next_action', '')}")
        lines.append(f"   Complete {blocker_text} first.")
    elif p.get("next_action"):
        lines.append(f"Next: {p['next_action']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_help() -> None:
    print("""
Tracker CLI

Commands:
  start    <session_id> <query>                  Build & save guidance steps for a query
  show     <session_id>                          Show full session JSON
  pending  <session_id>                          Show only pending steps
  progress <session_id>                          Show completion summary
  mark     <session_id> <step_ref> <status>      Mark a step by number (3) or id (apply-3)
                                                 status: pending | in_progress | completed
  list                                           List all saved sessions
  delete   <session_id>                          Delete a session
""".strip())


def _cli(argv: list[str]) -> None:
    if not argv:
        _print_help()
        return

    cmd, *args = argv

    if cmd == "start":
        sid, *qparts = args
        if not qparts:
            print("Usage: start <session_id> <query>")
            return
        record = start_session(sid, " ".join(qparts))
        print(format_progress(progress(sid)))
        print(f"\nSaved {len(record['steps'])} steps to {_path(sid)}")

    elif cmd == "show":
        record = load(args[0])
        print(json.dumps(record, indent=2) if record else f"No session: {args[0]}")

    elif cmd == "pending":
        print(format_pending(pending(args[0])))

    elif cmd == "progress":
        print(format_progress(progress(args[0])))

    elif cmd == "mark":
        sid, step_ref_raw, status = args[0], args[1], args[2]
        # Accept integer step number or string step id (e.g. "apply-3")
        step_ref: int | str = int(step_ref_raw) if step_ref_raw.isdigit() else step_ref_raw
        mark(sid, step_ref, status)
        print(format_progress(progress(sid)))

    elif cmd == "list":
        sessions = list_sessions()
        if not sessions:
            print("No saved sessions.")
            return
        for s in sessions:
            print(f"  {s['session_id']:<20} {s['completed']}/{s['total']}  "
                  f"{s['intent']:<25} updated {s['updated_at']}")

    elif cmd == "delete":
        ok = delete(args[0])
        print(f"Deleted {args[0]}." if ok else f"No session: {args[0]}")

    else:
        _print_help()


if __name__ == "__main__":
    _cli(sys.argv[1:])
