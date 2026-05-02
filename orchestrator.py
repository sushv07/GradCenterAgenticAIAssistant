"""
CSULB Grad Center – Orchestrator
Routes user input through the correct agent based on detected intent,
then wraps the agent output with a user-friendly presentation layer.

Flow:
    User → detect_route() → Agent → format_response() → Output

Routes:
    apply     → guidance_agent   (step-by-step guidance)
    checklist → checklist_agent  (actionable checklist with status)
    who/what  → answer_agent     (precise factual answer)
"""

from __future__ import annotations

import json
import re
import sys
from enum import Enum
from typing import Any

from query_handler import handle_query
from answer_agent import answer
from guidance_agent import guide_from_file
import tracker
from advisor_retrieval import find_advisor, format_advisor_result, advisors


# ---------------------------------------------------------------------------
# Route definitions
# ---------------------------------------------------------------------------

class Route(str, Enum):
    GUIDANCE  = "guidance"
    CHECKLIST = "checklist"
    ANSWER    = "answer"
    TRACKING  = "tracking"


_ROUTE_SIGNALS: list[tuple[Route, set[str]]] = [
    (
        Route.CHECKLIST,
        {"checklist", "check", "list", "track", "tasks", "todo", "mark", "progress"},
    ),
    (
        Route.GUIDANCE,
        {
            "apply", "applying", "applied", "application", "steps", "process",
            "admitted", "accepted", "enrolled", "international", "eligibility",
            "eligible", "orientation", "newly", "procedure",
            "start", "begin", "started", "beginning", "confused", "stuck", "help",
        },
    ),
    (
        Route.ANSWER,
        {
            "who", "what", "when", "where", "which", "why", "how",
            "is", "are", "does", "do", "can", "will",
            "much", "many", "long", "tell", "explain", "describe", "show",
        },
    ),
]

_STOP_WORDS = {
    "a", "an", "the", "i", "me", "my", "we", "you", "your",
    "it", "its", "to", "of", "in", "on", "at", "for", "by",
    "with", "from", "and", "or", "but", "so", "as",
}

_CHECKLIST_SIGNALS = next(s for route, s in _ROUTE_SIGNALS if route == Route.CHECKLIST)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOP_WORDS


_GUIDANCE_DOMAIN = {
    "apply", "applying", "applied", "application",
    "admitted", "accepted", "enrolled", "newly",
    "international", "eligibility", "eligible",
    "orientation", "steps", "process", "procedure",
    "start", "begin", "started", "beginning", "confused", "stuck", "help",
}


# ---------------------------------------------------------------------------
# Tracking command parsing
# ---------------------------------------------------------------------------

_STATUS_ALIASES = {
    "done":        "completed",
    "complete":    "completed",
    "completed":   "completed",
    "finished":    "completed",
    "finish":      "completed",
    "in_progress": "in_progress",
    "progress":    "in_progress",
    "started":     "in_progress",
    "starting":    "in_progress",
    "working":     "in_progress",
    "pending":     "pending",
    "reset":       "pending",
    "todo":        "pending",
    "undo":        "pending",
}

# Action verbs → infer "completed" status when no explicit status given
_COMPLETION_VERBS = {"complete", "completed", "finish", "finished", "did", "done"}


def _parse_tracking_command(query: str) -> dict | None:
    """
    Recognize a tracking subcommand.

    Returns a dict with keys {action, ...args} or None if not a tracking query.
    """
    q = query.lower().strip()

    # mark step N (as)? <status>   |   complete step N   |   step N done
    m = re.search(r"\b(?:mark\s+)?step\s+(\d+)\b(?:\s+(?:as\s+)?(\w+(?:\s+\w+)?))?", q)
    if m:
        step: int | str = int(m.group(1))
        status_word = (m.group(2) or "").strip().replace(" ", "_")
        status = _STATUS_ALIASES.get(status_word)

        if not status:
            # Look for any completion verb anywhere in the query
            verbs = set(re.findall(r"[a-z]+", q))
            if verbs & _COMPLETION_VERBS:
                status = "completed"
            elif "progress" in q or "started" in q or "starting" in q:
                status = "in_progress"
            elif "pending" in q or "reset" in q or "undo" in q:
                status = "pending"

        if status:
            return {"action": "mark", "step": step, "status": status}

    # mark <step-id> (as)? <status>   |   apply-3 done   (step id like "apply-3")
    m2 = re.search(
        r"\bmark\s+([a-z][a-z0-9]*-\d+)\b(?:\s+(?:as\s+)?(\w+(?:\s+\w+)?))?", q
    )
    if not m2:
        # Also catch bare "<id> done / completed / …" patterns
        m2 = re.search(
            r"\b([a-z][a-z0-9]*-\d+)\b(?:\s+(?:as\s+)?(\w+(?:\s+\w+)?))?", q
        )
    if m2:
        step_id = m2.group(1)
        status_word = (m2.group(2) or "").strip().replace(" ", "_")
        status = _STATUS_ALIASES.get(status_word)

        if not status:
            verbs = set(re.findall(r"[a-z]+", q))
            if verbs & _COMPLETION_VERBS:
                status = "completed"
            elif "progress" in q or "started" in q or "starting" in q:
                status = "in_progress"
            elif "pending" in q or "reset" in q or "undo" in q:
                status = "pending"

        if status:
            return {"action": "mark", "step": step_id, "status": status}

    if re.search(r"\b(pending|what'?s\s+left|what\s+is\s+left|todo|to\s+do|remaining)\b", q):
        return {"action": "pending"}

    if re.search(r"\b(progress|status|how\s+(much|far)|completion)\b", q):
        return {"action": "progress"}

    if re.search(r"\b(list|all)\s+(my\s+)?sessions?\b", q) or q.strip() == "sessions":
        return {"action": "list_sessions"}

    return None


def detect_route(query: str) -> Route:
    """
    Routing precedence:
      1. CHECKLIST   — any checklist signal token
      2. GUIDANCE    — any guidance domain word (apply / steps / admitted / …)
      3. ANSWER      — yes/no question-starter (is / are / does / …)
      4. ANSWER (default) — fallback for everything else
    """
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

    # Tracking commands win before checklist — "mark step 1 done" must not
    # be intercepted by the "mark" checklist signal.
    if _parse_tracking_command(query):
        return Route.TRACKING

    if _CHECKLIST_SIGNALS & tokens:
        return Route.CHECKLIST

    # Yes/no question-starters → ANSWER (factual lookup) even if domain words appear
    first_word = next(iter(re.findall(r"[a-z]+", query.lower())), "")
    if first_word in {"is", "are", "does", "do", "can", "will", "should"}:
        return Route.ANSWER

    if _GUIDANCE_DOMAIN & tokens:
        return Route.GUIDANCE

    return Route.ANSWER


# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------

def _run_guidance(query: str, session_id: str) -> dict:
    return guide_from_file(query)


def _run_checklist(query: str, session_id: str) -> dict:
    guidance = guide_from_file(query)
    # Auto-save full guidance steps so subsequent tracking commands can update them
    tracker.save(session_id, guidance)
    guidance["_saved_to_session"] = session_id
    return guidance


def _run_answer(query: str, session_id: str) -> dict:
    return answer(query, handle_query(query))


def _run_tracking(query: str, session_id: str) -> dict:
    cmd = _parse_tracking_command(query) or {}
    action = cmd.get("action")

    try:
        # Pull the session's original source_url so tracking responses cite the right page
        record = tracker.load(session_id) if action != "list_sessions" else None
        source_url = (record or {}).get("source_url", "")

        if action == "mark":
            tracker.mark(session_id, cmd["step"], cmd["status"])
            view = tracker.progress(session_id)
            return {"action": "mark", "step": cmd["step"], "new_status": cmd["status"],
                    "progress": view, "session_id": session_id, "source_url": source_url}

        if action == "pending":
            return {"action": "pending", "source_url": source_url, **tracker.pending(session_id)}

        if action == "progress":
            return {"action": "progress", "source_url": source_url, **tracker.progress(session_id)}

        if action == "list_sessions":
            return {"action": "list_sessions", "sessions": tracker.list_sessions()}

    except KeyError as e:
        return {"action": action, "error": str(e),
                "hint": "Build a checklist first: 'Give me a checklist for newly admitted students'."}

    return {"action": "unknown", "error": "Could not interpret tracking command."}


_ROUTE_RUNNERS = {
    Route.GUIDANCE:  _run_guidance,
    Route.CHECKLIST: _run_checklist,
    Route.ANSWER:    _run_answer,
    Route.TRACKING:  _run_tracking,
}


# ---------------------------------------------------------------------------
# Presentation layer
# ---------------------------------------------------------------------------

_INTENT_LABELS = {
    "application_process": "applying to a graduate program",
    "newly_admitted":      "next steps after acceptance",
    "eligibility":         "graduate admission eligibility",
    "international":       "international student admission",
    "orientation":         "graduate student orientation",
}


def _bar(percent: float, length: int = 20) -> str:
    """Return a textual progress bar."""
    done = int(round(length * percent / 100))
    return "█" * done + "░" * (length - done)


def _motivation(percent_done: float, completed: int, total: int) -> str:
    """A short, advisor-style nudge based on where the user is in the list."""
    if total == 0:
        return ""
    if completed == total:
        return "🎉 You've completed everything on this list. Well done."
    to_go = total - completed
    if to_go == 1:
        return "🏁 One step left — let's finish it."
    if percent_done >= 75:
        return "🔥 You're in the home stretch."
    if percent_done >= 50:
        return "💪 You've passed the halfway point."
    if percent_done >= 25:
        return "🚀 You're building good momentum."
    if percent_done > 0:
        return "✨ A solid start — keep going."
    return "👋 Let's begin with Step 1."


def _dedupe_suggestions(items: list[str]) -> list[str]:
    """Case-insensitive dedup, preserving first occurrence and original casing."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _format_current_focus(current: dict | None) -> dict | None:
    """Render the current/next item as a clean focus block."""
    if not current:
        return None
    status  = current.get("status", "pending")
    is_blocked = bool(current.get("is_blocked"))
    if is_blocked:
        label = "🔒 Blocked"
    elif status == "in_progress":
        label = "🚧 In progress"
    else:
        label = "⏳ Up next"
    title   = current.get("title") or current.get("action", "")
    detail  = current.get("primary_action") or current.get("details", "") or current.get("action", "")
    warning = (current.get("warnings") or [None])[0] or current.get("warning")
    link    = (current.get("resources") or [{}])[0].get("url") or current.get("resource")
    return {
        "label":          label,
        "step":           current.get("step"),
        "id":             current.get("id", ""),
        "title":          title,
        "details":        detail,
        "warning":        warning,
        "link":           link,
        "primary_action": current.get("primary_action", ""),
        "is_blocked":     is_blocked,
        "blocked_by":     current.get("blocked_by", []),
    }


def _next_step_instruction(current: dict | None, in_progress_count: int) -> tuple[str, str]:
    """
    Return (instruction, suggested_command) — an advisor-style line on what to do next.
    Redirects to the blocker if the focus step has unmet prerequisites.
    """
    if not current:
        return ("You're done with this list — nothing else to do here.", "")

    step    = current.get("step")
    title   = current.get("title") or current.get("action", "")
    details = current.get("primary_action") or current.get("details", "") or current.get("action", "")

    blocked_by = current.get("blocked_by") or []
    if blocked_by:
        if len(blocked_by) == 1:
            b = blocked_by[0]
            instruction = (
                f"Step {step} ({title}) is waiting on Step {b['step']} ({b['title']}). "
                f"Take care of that one first."
            )
        else:
            blockers_str = " and ".join(
                f"Step {b['step']} ({b['title']})" for b in blocked_by
            )
            instruction = (
                f"Step {step} ({title}) depends on {blockers_str}. "
                f"Clear those, then return to this one."
            )
        first_blocker = blocked_by[0]
        command = f"mark step {first_blocker['step']} as in progress"
        return instruction, command

    if current.get("status") == "in_progress":
        instruction = (
            f"You're working on Step {step} — {title}. "
            f"When it's complete, say \"mark step {step} done\" and I'll update your progress."
        )
        command = f"mark step {step} as completed"
    else:
        instruction = f"Next on your list: Step {step} — {title}. {details}".rstrip()
        command = f"mark step {step} as in progress"

    return instruction, command


def _truncate(text: str, n: int = 90) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _strip_dash_tail(text: str) -> str:
    """'Step 2: Activate Account — long details…' → 'Step 2: Activate Account'."""
    return (text or "").split(" — ", 1)[0]


def _humanize_guidance(query: str, result: dict) -> dict:
    intent       = result.get("intent", "")
    intent_label = _INTENT_LABELS.get(intent, intent.replace("_", " "))
    steps        = result.get("steps", [])
    total        = len(steps)

    if not steps:
        return {
            "summary":        "I don't have specific guidance for that yet. Tell me a bit more about what you're working through and I'll point you in the right direction.",
            "primary_action": "Try asking about applying, eligibility, or a specific stage of the process.",
            "steps":          [],
            "total_steps":    0,
            "next_actions":   [
                "How do I apply to a graduate program?",
                "What are the eligibility requirements?",
                "Email GraduateCenter@csulb.edu for direct help",
            ],
        }

    first       = steps[0]
    first_title = first.get("title") or first.get("action", "")
    warning     = (first.get("warnings") or [None])[0]
    primary     = first.get("primary_action", "")

    summary = (
        f"Here's how to approach {intent_label} — {total} steps in all. "
        f"Start with **{_strip_dash_tail(first_title)}**; everything that follows builds on it."
    )
    primary_action = primary or f"Begin with Step 1 — {first_title}."
    if warning:
        primary_action += f"  ⚠ {warning}"

    clean_steps = [
        {
            "number":    s.get("step"),
            "do":        s.get("action") or s.get("title", ""),
            "why":       s.get("outcome", ""),
            "details":   s.get("details", ""),
            "prep":      s.get("prep", []),
            "how":       s.get("how", []),
            "time":      s.get("time", ""),
            "glossary":  s.get("glossary", {}),
            "watch_out": (s.get("warnings") or [None])[0],
            "link":      (s.get("resources") or [{}])[0].get("url"),
        }
        for s in steps
    ]

    next_actions = [
        "Turn this into a checklist I can track",
        "What should I watch out for?",
        "Who do I contact for my program?",
    ]

    return {
        "summary":        summary,
        "primary_action": primary_action,
        "steps":          clean_steps,
        "total_steps":    total,
        "next_actions":   next_actions,
    }


def _humanize_checklist(query: str, result: dict) -> dict:
    intent       = result.get("intent", "")
    intent_label = _INTENT_LABELS.get(intent, intent.replace("_", " "))
    steps        = result.get("steps", [])
    total        = len(steps)

    if not steps:
        return {
            "summary":        "I'd like to build you a checklist, but I need a bit more context. What stage are you at — applying, recently admitted, or working through your program?",
            "primary_action": "Try: 'give me a checklist for newly admitted students'",
            "steps":          [],
            "total_items":    0,
            "next_actions":   [
                "Give me a checklist for applying",
                "Give me a checklist for newly admitted students",
                "Show eligibility requirements",
            ],
        }

    first       = steps[0]
    first_title = first.get("title") or first.get("action", "")
    primary     = first.get("primary_action", "")

    summary = (
        f"Here's your checklist for {intent_label} — {total} steps. "
        f"Work through them at your pace; I'll keep track of where you are."
    )
    primary_action = primary or f"Begin with Step 1 — {_truncate(first_title, 100)}"

    next_actions = [
        "Mark step 1 as in progress",
        "Show my pending tasks",
        "What's my progress?",
    ]

    return {
        "summary":        summary,
        "primary_action": primary_action,
        "steps":          steps,
        "total_items":    total,
        "next_actions":   next_actions,
    }


def _humanize_answer(query: str, result: dict) -> dict:
    raw_answer  = result.get("answer", "")
    answer_type = result.get("answer_type", "unknown")
    confidence  = result.get("confidence", "low")

    if answer_type == "faq" and isinstance(raw_answer, dict):
        answer_text, rendered = raw_answer.get("answer", ""), raw_answer
    elif isinstance(raw_answer, str):
        answer_text, rendered = raw_answer, raw_answer
    else:
        answer_text, rendered = "See details below.", raw_answer

    if answer_type == "unknown" or "don't know" in str(answer_text).lower():
        return {
            "summary":        "That's not something I can confirm from the Grad Center pages. Rather than guess, let me point you to the right person.",
            "primary_action": "Reach out to GraduateCenter@csulb.edu — they typically respond within a business day.",
            "answer":         rendered,
            "confidence":     "low",
            "next_actions": [
                "Show me the application steps",
                "What are the GPA requirements?",
                "Who is the contact for my program?",
            ],
        }

    if isinstance(answer_text, str) and len(answer_text) < 240:
        summary = answer_text
    else:
        summary = "Here's what the Grad Center pages say:"

    if confidence == "high":
        primary_action = "This is directly from the Grad Center pages — you can rely on it."
    elif confidence == "medium":
        primary_action = "This should be accurate — worth confirming with the source linked below."
    else:
        primary_action = "Treat this as a starting point and verify with the source below before acting on it."

    next_actions = [
        "Show me the application steps",
        "Give me a checklist for next steps",
        "What funding is available?",
    ]

    return {
        "summary":        summary,
        "primary_action": primary_action,
        "answer":         rendered,
        "confidence":     confidence,
        "next_actions":   next_actions,
    }


def _tracking_next_actions(progress: dict) -> list[str]:
    """Build state-aware suggestions from a progress summary."""
    completed = progress.get("completed", 0)
    total     = progress.get("total", 0)
    pending   = progress.get("pending", 0)
    in_prog   = progress.get("in_progress", 0)

    if total == 0:
        return ["Build a checklist first: 'Give me a checklist for applying'"]
    if completed == total:
        return ["List my sessions", "Start a new checklist for newly admitted students"]

    next_step = completed + in_prog + 1  # next pending
    suggestions: list[str] = []

    if in_prog > 0:
        current      = progress.get("current_item") or {}
        in_prog_step = current.get("step")
        suggestions.append(f"Mark step {in_prog_step or next_step - in_prog} as completed")
    else:
        suggestions.append(f"Mark step {next_step} as in progress")

    if pending + in_prog > 1:
        suggestions.append("Show my pending tasks")
    suggestions.append("What's my progress?")
    return suggestions[:3]


def _humanize_tracking(query: str, result: dict) -> dict:
    action = result.get("action", "")

    if "error" in result:
        return {
            "summary":        f"Something didn't line up there: {result['error']}",
            "primary_action": result.get("hint", "Let's start fresh — tell me which checklist you'd like to work on."),
            "details":        result,
            "next_actions":   [
                "Give me a checklist for newly admitted students",
                "Give me a checklist for applying",
                "List my sessions",
            ],
        }

    if action == "mark":
        p          = result["progress"]
        new_status = result["new_status"]
        step       = result["step"]
        current    = p.get("current_item")
        instruction, suggested = _next_step_instruction(current, p["in_progress"])

        if p["completed"] == p["total"]:
            return {
                "summary":         f"🎉 That's all {p['total']} steps complete. Well done.",
                "primary_action":  "You're finished with this checklist. Would you like to start another, or review your saved sessions?",
                "progress_bar":    f"[{_bar(100)}] 100%",
                "breakdown":       f"✓ Done · {p['total']}",
                "motivation":      _motivation(100, p['total'], p['total']),
                "current_focus":   None,
                "next_step":       "Nothing further to do here — you can list your sessions or start a new checklist whenever you're ready.",
                "progress":        p,
                "next_actions":    _tracking_next_actions(p),
            }

        # Tone varies with the status the user just set
        if new_status == "completed":
            summary_lead = f"Step {step} marked complete."
        elif new_status == "in_progress":
            summary_lead = f"Step {step} is now in progress."
        elif new_status == "pending":
            summary_lead = f"Step {step} moved back to your pending list."
        else:
            summary_lead = f"Step {step} updated."

        progress_tail = (
            f" You're at {p['percent_done']}% — {p['completed']} of {p['total']} done."
        )

        blocked = p.get("blocked", 0)
        breakdown = (
            f"✓ Done · {p['completed']}    🚧 In progress · {p['in_progress']}    "
            f"⏳ To go · {p['pending']}"
        )
        if blocked:
            breakdown += f"    🔒 Blocked · {blocked}"

        return {
            "summary":        summary_lead + progress_tail,
            "primary_action": instruction,
            "progress_bar":   f"[{_bar(p['percent_done'])}] {p['percent_done']}%",
            "breakdown":      breakdown,
            "motivation":     _motivation(p['percent_done'], p['completed'], p['total']),
            "current_focus":  _format_current_focus(current),
            "next_step":      instruction,
            "progress":       p,
            "next_actions":   _dedupe_suggestions(([suggested] if suggested else []) + _tracking_next_actions(p))[:3],  # mark
        }

    if action == "pending":
        count   = result["pending_count"]
        total   = result["total"]
        ready   = result.get("ready_count", count)
        blocked = result.get("blocked_count", 0)

        if count == 0:
            summary        = f"🎉 Everything on this list is complete — all {total} steps."
            primary_action = "You're fully caught up. Would you like to start a new checklist?"
        else:
            done = total - count
            block_msg = f", and {blocked} 🔒 waiting on prerequisites" if blocked else ""
            task_word = "task" if count == 1 else "tasks"
            summary = (
                f"You've completed {done} of {total}. "
                f"{count} {task_word} remaining — {ready} ready to start now{block_msg}."
            )
            # Prefer the first non-blocked pending step as the action target
            first_actionable = next(
                (s for s in result["pending"] if not s.get("is_blocked")),
                result["pending"][0],
            )
            task_title = first_actionable.get("title") or first_actionable.get("action", "")
            primary    = first_actionable.get("primary_action", "")
            if first_actionable.get("is_blocked"):
                # Every pending step is blocked — point to the unblocker
                blockers = first_actionable.get("blocked_by", [])
                if blockers:
                    b = blockers[0]
                    primary_action = (
                        f"Each remaining step is waiting on something earlier. "
                        f"Begin by completing Step {b['step']} ({b['title']})."
                    )
                else:
                    primary_action = f"Take on **{_truncate(task_title, 90)}** next."
            else:
                primary_action = primary or f"Take on **{_truncate(task_title, 90)}** next."

        return {
            "summary":        summary,
            "primary_action": primary_action,
            "pending":        result["pending"],
            "pending_count":  count,
            "ready_count":    ready,
            "blocked_count":  blocked,
            "total":          total,
            "next_actions":   _tracking_next_actions({
                "completed": total - count, "total": total,
                "pending": count, "in_progress": 0,
                "current_item": next(
                    (s for s in result["pending"] if not s.get("is_blocked")),
                    result["pending"][0] if result["pending"] else None,
                ),
            }),
        }

    if action == "progress":
        completed = result["completed"]
        total     = result["total"]
        pct       = result["percent_done"]
        current   = result.get("current_item")
        instruction, suggested = _next_step_instruction(current, result["in_progress"])

        if completed == total and total > 0:
            return {
                "summary":        f"🎉 All {total} steps complete. Well done.",
                "primary_action": "You can start a new checklist, or return to another saved session.",
                "progress_bar":   f"[{_bar(100)}] 100%",
                "breakdown":      f"✓ Done · {total}",
                "motivation":     _motivation(100, total, total),
                "current_focus":  None,
                "next_step":      "Nothing further on this list — choose a new checklist or review your sessions.",
                "progress":       result,
                "next_actions":   _tracking_next_actions(result),
            }

        to_go = total - completed
        to_go_text = "1 step" if to_go == 1 else f"{to_go} steps"

        blocked = result.get("blocked", 0)
        breakdown = (
            f"✓ Done · {completed}    🚧 In progress · {result['in_progress']}    "
            f"⏳ To go · {result['pending']}"
        )
        if blocked:
            breakdown += f"    🔒 Blocked · {blocked}"

        return {
            "summary":        f"You're {pct}% through — {completed} of {total} done, {to_go_text} remaining.",
            "primary_action": instruction,
            "progress_bar":   f"[{_bar(pct)}] {pct}%",
            "breakdown":      breakdown,
            "motivation":     _motivation(pct, completed, total),
            "current_focus":  _format_current_focus(current),
            "next_step":      instruction,
            "progress":       result,
            "next_actions":   _dedupe_suggestions(([suggested] if suggested else []) + _tracking_next_actions(result))[:3],
        }

    if action == "list_sessions":
        sessions = result["sessions"]
        if not sessions:
            return {
                "summary":        "You don't have any saved checklists yet. Let's set one up.",
                "primary_action": "Try: 'give me a checklist for newly admitted students'",
                "sessions":       [],
                "next_actions": [
                    "Give me a checklist for newly admitted students",
                    "Give me a checklist for applying",
                    "What are the eligibility requirements?",
                ],
            }
        # Suggest picking up the least-complete session
        focus    = min(sessions, key=lambda s: s.get("completed", 0) / max(s.get("total", 1), 1))
        plural   = "checklist" if len(sessions) == 1 else "checklists"
        focus_pct = round(100 * focus['completed'] / max(focus['total'], 1))
        return {
            "summary":        f"You have {len(sessions)} saved {plural}.",
            "primary_action": (
                f"I'd suggest picking up '{focus['session_id']}' next — "
                f"you're {focus['completed']}/{focus['total']} ({focus_pct}%) in."
            ),
            "sessions":       sessions,
            "next_actions": [
                "What's my progress?",
                "Show my pending tasks",
                "Give me a new checklist",
            ],
        }

    return {
        "summary":        "Updated. Is there anything else you'd like to review?",
        "primary_action": "",
        "details":        result,
        "next_actions":   ["What's my progress?", "Show my pending tasks", "List my sessions"],
    }


_HUMANIZERS = {
    Route.GUIDANCE:  _humanize_guidance,
    Route.CHECKLIST: _humanize_checklist,
    Route.ANSWER:    _humanize_answer,
    Route.TRACKING:  _humanize_tracking,
}


def _format_response(query: str, route: Route, raw: dict) -> dict:
    """Wrap raw agent output with a user-friendly presentation."""
    body = _HUMANIZERS[route](query, raw)

    next_actions = body.pop("next_actions", []) or []

    return {
        "query":          query,
        "route":          route.value,
        "summary":        body.pop("summary"),
        "primary_action": body.pop("primary_action"),
        **body,
        "source": {
            "file": raw.get("source_file", ""),
            "url":  raw.get("source_url", "https://www.csulb.edu/graduate-center"),
        },
        "next_actions":   next_actions,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(query: str, session_id: str = "default") -> dict[str, Any]:
    """Route the query, run the agent, and return a user-friendly response."""
    query = (query or "").strip()

    if not query:
        return {
            "route":          None,
            "session_id":     session_id,
            "summary":        "Welcome to the Grad Center. What can I help you with today?",
            "primary_action": "Ask me about admissions, your program, or any step in the process — or pick a starting point below.",
            "next_actions": [
                "How do I apply to a graduate program?",
                "Give me a checklist for newly admitted students",
                "Who do I contact about thesis submission?",
            ],
        }

    # ── Detect process intent — these queries bypass the advisor card ────────
    # "apply", "application", "steps", "process", "start" signal that the user
    # wants guidance on HOW to apply, not WHO to contact.  Skip the advisor card
    # so "I want to apply for a PhD" routes to next-steps, not a program card.
    _q = query.lower()
    _PROCESS_KEYWORDS = {
        "apply", "application", "steps", "process", "start",
        "begin", "beginning", "confused", "stuck", "where to start",
        "where to begin", "don't know",
    }
    is_process_query = any(k in _q for k in _PROCESS_KEYWORDS)

    # ── Advisor retrieval runs FIRST — before intent routing ─────────────────
    # find_advisor() uses fuzzy matching + stop-word normalisation so it handles
    # abbreviations ("dnp"), aliases ("applied anthro"), and conversational
    # phrasing ("who do I contact for nursing") reliably.  Returning early here
    # means words like "applied" or "advisor" can never hijack the route.
    advisor_result = find_advisor(query)
    if not is_process_query and (advisor_result["match"] or advisor_result["suggestions"]):
        match      = advisor_result["match"]
        source_url = (match or {}).get("source", "https://www.csulb.edu/graduate-center")
        primary    = (
            f"Email {match['email']} to schedule an advising appointment."
            if match and match.get("email")
            else "Contact GraduateCenter@csulb.edu for advisor information."
        )
        return {
            "query":          query,
            "route":          "advisor",
            "session_id":     session_id,
            "summary":        f"I found a {'Strong' if advisor_result['confidence'] >= 90 else 'Good'} match for your query." if match else "I couldn't find an exact match.",
            "primary_action": primary,
            "advisor_data":   advisor_result,   # raw result for the UI to render
            "source":         {"file": "", "url": source_url},
            "next_actions": [
                "Show me the application steps",
                "What are the GPA requirements?",
                "Who is the contact for my program?",
            ],
        }

    # ── PhD / doctoral query with no match → list available doctoral programs ─
    # e.g. "business phd csulb" — the user is looking for a doctoral program that
    # doesn't exist in the dataset.  Give a natural "not found" answer with the
    # full list of doctoral/professional programs we do have.
    _DOCTORAL_TOKENS = {"phd", "ph", "doctorate", "doctoral", "doctor", "edd", "dpt", "dnp"}
    raw_tokens = set(re.findall(r"[a-z]+", query.lower()))
    if raw_tokens & _DOCTORAL_TOKENS and not (advisor_result["match"] or advisor_result["suggestions"]):
        doctoral_programs = [
            a for a in advisors
            if any(
                kw in (a.get("program") or "").lower()
                for kw in ["ph.d", "phd", "ed.d", "dpt", "d.n.p", "dr.p.h", "dnp"]
            )
        ]
        prog_names = [a["program"] for a in doctoral_programs if a.get("program")]
        return {
            "query":          query,
            "route":          "advisor",
            "session_id":     session_id,
            "summary":        "There's no doctoral program matching that at CSULB — but here are the doctoral and professional programs we do have advisor information for.",
            "primary_action": "Pick the closest program below and I can show you the advisor contact and application steps.",
            "advisor_data":   {
                "match": None,
                "confidence": advisor_result["confidence"],
                "suggestions": [],
                "known_programs": prog_names,
            },
            "source":         {"file": "", "url": "https://www.csulb.edu/graduate-center"},
            "next_actions": [
                "Engineering PhD advisor",
                "Nursing DNP advisor",
                "Physical therapy advisor",
            ],
        }

    # ── Advisor-intent with no program name ──────────────────────────────────
    # e.g. "who should I contact" — stop-word normalisation stripped the whole
    # query, but the raw tokens signal the user is looking for an advisor.
    # Return a prompt asking for the program name instead of a generic answer.
    _ADVISOR_INTENT = {"contact", "advisor", "adviser", "advising", "talk", "speak", "email", "reach"}
    if advisor_result["confidence"] == 0 and raw_tokens & _ADVISOR_INTENT:
        known = [a["program"] for a in advisors if a.get("program")]
        return {
            "query":          query,
            "route":          "advisor",
            "session_id":     session_id,
            "summary":        "It looks like you're looking for an advisor — I just need the program name.",
            "primary_action": "Try something like: \"nursing advisor\", \"dnp advisor\", or \"engineering phd advisor\".",
            "advisor_data":   {"match": None, "confidence": 0, "suggestions": [], "known_programs": known},
            "source":         {"file": "", "url": "https://www.csulb.edu/graduate-center"},
            "next_actions": [
                "Nursing advisor",
                "Engineering phd advisor",
                "Physical therapy advisor",
            ],
        }

    route = detect_route(query)
    raw   = _ROUTE_RUNNERS[route](query, session_id)
    response = _format_response(query, route, raw)
    response["session_id"] = session_id
    return response


# ---------------------------------------------------------------------------
# Pretty-print formatter (for terminal display)
# ---------------------------------------------------------------------------

def format_for_display(response: dict) -> str:
    """Render the structured response as readable terminal text."""
    lines: list[str] = []
    sep = "─" * 72

    lines.append(sep)
    lines.append(f"❯ {response.get('query', '')}")
    lines.append(sep)

    summary = response.get("summary", "")
    if summary:
        lines.append(f"\n{summary}\n")

    primary = response.get("primary_action")
    # For tracking, the next-step block below renders the actionable instruction
    # in a clearer form — don't double up.
    if primary and response.get("route") != "tracking":
        lines.append(f"➤ Do this first: {primary}\n")

    route = response.get("route")

    if route == "guidance":
        for s in response.get("steps", []):
            lines.append(f"  Step {s['number']} — {s['do']}")
            if s.get("time"):
                lines.append(f"     ⏱  {s['time']}")
            if s.get("why"):
                lines.append(f"     🎯 Goal: {s['why']}")
            if s.get("prep"):
                lines.append(f"     ✓ Before you start:")
                for p in s["prep"]:
                    lines.append(f"        • {p}")
            if s.get("how"):
                lines.append(f"     → How to do it:")
                for i, h in enumerate(s["how"], 1):
                    lines.append(f"        {i}. {h}")
            if s.get("glossary"):
                lines.append(f"     📖 Terms:")
                for term, defn in s["glossary"].items():
                    lines.append(f"        • {term} = {defn}")
            if s.get("watch_out"):
                lines.append(f"     ⚠  Watch out: {s['watch_out']}")
            if s.get("link"):
                lines.append(f"     🔗 {s['link']}")
            lines.append("")

    elif route == "checklist":
        _pri_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for step in response.get("steps", []):
            status   = step.get("status", "pending")
            box      = "[ ]" if status == "pending" else "[~]" if status == "in_progress" else "[x]"
            title    = step.get("title") or step.get("action", "")
            step_id  = step.get("id", "")
            pri_icon = _pri_icon.get(step.get("priority", "medium"), "")
            lines.append(f"  {box} {step.get('step')}. {title}  {pri_icon}  [{step_id}]")
            if step.get("depends_on"):
                lines.append(f"        ↳ Requires: {', '.join(step['depends_on'])}")
            if step.get("warnings"):
                lines.append(f"        ⚠  {step['warnings'][0]}")
            if step.get("resources"):
                lines.append(f"        🔗 {step['resources'][0].get('url', '')}")
            lines.append("")

    elif route == "tracking":
        # Progress bar + breakdown (only present for mark / progress)
        bar = response.get("progress_bar")
        breakdown = response.get("breakdown")
        motivation = response.get("motivation")
        if bar or breakdown or motivation:
            if bar:
                lines.append(f"  {bar}")
            if breakdown:
                lines.append(f"  {breakdown}")
            if motivation:
                lines.append(f"  {motivation}")
            lines.append("")

        # Current focus block
        focus = response.get("current_focus")
        if focus:
            lines.append(f"  {focus['label']} — Step {focus['step']}: {focus['title']}")
            if focus.get("is_blocked"):
                for b in focus.get("blocked_by", []):
                    lines.append(
                        f"     ⛔ Blocked by Step {b['step']} ({b['title']}) — "
                        f"complete it first"
                    )
            if focus.get("details") and not focus.get("is_blocked"):
                lines.append(f"     {focus['details']}")
            if focus.get("warning"):
                lines.append(f"     ⚠  {focus['warning']}")
            if focus.get("link"):
                lines.append(f"     🔗 {focus['link']}")
            lines.append("")

        # Explicit next step — single, clear actionable instruction
        next_step = response.get("next_step")
        if next_step:
            lines.append(f"  ➡  Next step:")
            lines.append(f"     {next_step}\n")

        # Pending list
        for item in response.get("pending", []) or []:
            box        = "[ ]" if item.get("status") == "pending" else "[~]"
            title      = item.get("title") or item.get("action", "")
            step_id    = item.get("id", "")
            is_blocked = item.get("is_blocked")
            block_icon = "🔒 " if is_blocked else ""
            lines.append(f"  {box} {block_icon}{item.get('step')}. {title}  [{step_id}]")
            if is_blocked:
                for b in item.get("blocked_by", []):
                    lines.append(
                        f"        ⛔ Step {item.get('step')} is blocked until "
                        f"Step {b['step']} ({b['title']}) is completed"
                    )

        # Sessions list
        for s in response.get("sessions", []) or []:
            pct = round(100 * s.get("completed", 0) / max(s.get("total", 1), 1))
            lines.append(f"  • {s['session_id']:<20} {s['completed']}/{s['total']} "
                         f"({pct}%)  {s.get('intent', '')}")
        if response.get("pending") or response.get("sessions"):
            lines.append("")

    elif route == "answer":
        ans = response.get("answer")
        if isinstance(ans, dict) and "question" in ans:
            lines.append(f"Q: {ans['question']}")
            lines.append(f"A: {ans['answer']}\n")
        elif isinstance(ans, (list, dict)):
            lines.append(json.dumps(ans, indent=2))
            lines.append("")
        elif isinstance(ans, str):
            lines.append(f"{ans}\n")
        confidence = response.get("confidence", "")
        if confidence:
            lines.append(f"Confidence: {confidence}")

    src = response.get("source", {})
    if src.get("url"):
        lines.append(f"\nSource: {src['url']}")

    next_actions = response.get("next_actions", [])
    if next_actions:
        lines.append("\n💡 What you can say next:")
        for n in next_actions:
            lines.append(f"  → {n}")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _repl(pretty: bool, session_id: str) -> None:
    print(f"CSULB Grad Center Assistant  |  session: {session_id}  |  type 'exit' to quit\n")
    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            print("Goodbye.")
            break

        response = run(query, session_id=session_id)
        if pretty:
            print(format_for_display(response))
        else:
            print(json.dumps(response, indent=2))
        print()


def _extract_flag(args: list[str], flag: str, default: str) -> tuple[str, list[str]]:
    """Pop --flag value from args, returning (value, remaining_args)."""
    if flag in args:
        i = args.index(flag)
        try:
            value = args[i + 1]
            return value, args[:i] + args[i + 2:]
        except IndexError:
            return default, args[:i]
    return default, args


if __name__ == "__main__":
    args   = sys.argv[1:]
    pretty = "--pretty" in args
    args   = [a for a in args if a != "--pretty"]
    session_id, args = _extract_flag(args, "--session", "default")

    if args:
        response = run(" ".join(args), session_id=session_id)
        if pretty:
            print(format_for_display(response))
        else:
            print(json.dumps(response, indent=2))
    else:
        _repl(pretty=pretty, session_id=session_id)
