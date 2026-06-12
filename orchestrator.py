"""
CSULB Grad Center – Orchestrator
Routes user input through the correct agent based on detected intent,
then wraps the agent output with a user-friendly presentation layer.

Flow:
    User → detect_route() → Agent → format_response() → Output

Routes:
    apply    → guidance_agent  (step-by-step guidance)
    who/what → answer_agent    (precise factual answer)
    topics   → deadlines_tool | eligibility_tool | application_steps_tool
    advisor  → advisor_retrieval + email_tool
"""

from __future__ import annotations

import json
import re
import sys
import time
from enum import Enum
from typing import Any

from gradcenter_logging import emit

from query_handler import handle_query
from answer_agent import answer
from guidance_agent import guide_from_file
from advisor_retrieval import find_advisor, format_advisor_result, advisors
from tools.application_steps_tool import _detect_program as _tool_detect_program


# ---------------------------------------------------------------------------
# Route definitions
# ---------------------------------------------------------------------------

class Route(str, Enum):
    GUIDANCE  = "guidance"
    ANSWER    = "answer"


_ROUTE_SIGNALS: list[tuple[Route, set[str]]] = [
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


# ---------------------------------------------------------------------------
# Intent-priority routing signals
# ---------------------------------------------------------------------------
# Used in run() BEFORE find_advisor() so program aliases ("dnp", "nursing")
# cannot hijack deadline / eligibility / application-steps queries.
#
# Priority order inside run():
#   1. Advisor signals  → always show advisor card first
#   2. Deadline signals → deadlines_tool
#   3. Eligibility signals → eligibility_tool
#   4. Process + steps signals (when also is_process_query) → application_steps_tool
#   5. Everything else  → existing advisor → detect_route() flow

# Words that definitively mean "I want advisor/contact info"
_ADVISOR_SIGNALS = frozenset({
    "advisor", "advisors", "adviser", "advisers",
    "contact", "who", "advising",
})

# Words that signal a deadline query
_DEADLINE_SIGNALS = frozenset({
    "deadline", "deadlines", "due", "cutoff",
})

# Words that signal an eligibility query
_ELIGIBILITY_SIGNALS = frozenset({
    "eligibility", "eligible", "gpa", "requirement", "requirements",
    "qualify", "qualification", "minimum", "qualified",
})

# Words that (combined with is_process_query) route to application_steps_tool
# "apply" / "application" alone stay on the GUIDANCE path for generic queries;
# "steps" / "process" / "procedure" signals the user wants an ordered list.
_PROCESS_STEP_SIGNALS = frozenset({
    "steps", "process", "procedure",
})


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOP_WORDS


# ---------------------------------------------------------------------------
# Tracking command parsing  (removed — checklist tracking is no longer a feature)
# ---------------------------------------------------------------------------

_GUIDANCE_DOMAIN = {
    "apply", "applying", "applied", "application",
    "admitted", "accepted", "enrolled", "newly",
    "international", "eligibility", "eligible",
    "orientation", "steps", "process", "procedure",
    "start", "begin", "started", "beginning", "confused", "stuck", "help",
}


def detect_route(query: str) -> Route:
    """
    Routing precedence:
      1. GUIDANCE    — any guidance domain word (apply / steps / admitted / …)
      2. ANSWER      — yes/no question-starter (is / are / does / …)
      3. ANSWER (default) — fallback for everything else
    """
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

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


def _run_answer(query: str, session_id: str) -> dict:
    retrieved = handle_query(query)
    _t0 = time.perf_counter()
    result = answer(query, retrieved)
    _elapsed = round((time.perf_counter() - _t0) * 1000, 1)
    _level = (
        "WARNING"
        if result.get("answer_type") == "unknown"
        or result.get("confidence") == "low"
        else "INFO"
    )
    _kw_fields: dict = dict(
        answer_type=result.get("answer_type", "unknown"),
        confidence=result.get("confidence", "low"),
        source_file=result.get("source_file", ""),
        elapsed_ms=_elapsed,
    )
    if result.get("source_file") and result.get("source_url"):
        _kw_fields["source_url"] = result["source_url"]
    emit("keyword.result", level=_level, **_kw_fields)
    return result


_ROUTE_RUNNERS = {
    Route.GUIDANCE: _run_guidance,
    Route.ANSWER:   _run_answer,
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
        "What should I watch out for?",
        "Who do I contact for my program?",
        "What are the GPA requirements?",
    ]

    return {
        "summary":        summary,
        "primary_action": primary_action,
        "steps":          clean_steps,
        "total_steps":    total,
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
        "What are the GPA requirements?",
        "What funding is available?",
    ]

    return {
        "summary":        summary,
        "primary_action": primary_action,
        "answer":         rendered,
        "confidence":     confidence,
        "next_actions":   next_actions,
    }


_HUMANIZERS = {
    Route.GUIDANCE: _humanize_guidance,
    Route.ANSWER:   _humanize_answer,
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
# Logging helpers
# ---------------------------------------------------------------------------

def _emit_tool_result(tool_name: str, result: dict, elapsed_ms: float) -> None:
    """Emit tool.result for a topic-tool call from _build_topic_response()."""
    found      = result.get("found", False)
    top_score  = round(float(result.get("top_score") or 0.0), 4)
    num_results = len(result.get("results") or [])
    is_degraded = not found or result.get("fallback_used") or result.get("error")
    level = "ERROR" if result.get("error") else ("WARNING" if is_degraded else "INFO")
    _opt: dict = {"num_results": num_results}
    if result.get("fallback_used"):
        _opt["fallback_used"] = True
    if result.get("needs_clarification"):
        _opt["needs_clarification"] = True
    if result.get("program_name"):
        _opt["program_name"] = result["program_name"]
    if result.get("program_specific") is not None:
        _opt["program_specific"] = bool(result["program_specific"])
    if result.get("error"):
        _opt["error"] = str(result["error"])[:200]
    emit("tool.result", level=level,
         tool=tool_name, found=found, top_score=top_score,
         elapsed_ms=elapsed_ms, **_opt)


# ---------------------------------------------------------------------------
# Topic-tool response builder
# ---------------------------------------------------------------------------

def _build_topic_response(topic: str, query: str, session_id: str) -> dict:
    """
    Call the appropriate Phase-2 tool and return a formatted orchestrator response.

    Used when topic-priority routing fires (deadline / eligibility / application)
    BEFORE find_advisor() so program aliases cannot hijack the route.

    Args:
        topic:      "deadlines" | "eligibility" | "application"
        query:      Original user query (passed to the tool for RAG retrieval)
        session_id: Current session identifier

    Returns:
        Full orchestrator response dict, consistent with the schema returned by
        _format_response() so the UI can render it without special casing.
    """
    if topic == "deadlines":
        from tools.deadlines_tool import get_deadlines
        _tt0 = time.perf_counter()
        result = get_deadlines(query)
        _emit_tool_result("deadlines_tool", result, round((time.perf_counter() - _tt0) * 1000, 1))
        heading     = "Deadlines"
        source_base = (
            "https://www.csulb.edu/graduate-studies-csulb/article/"
            "programs-advisors-and-deadlines-doctoral"
        )
        next_actions = [
            "Who is the advisor for my program?",
            "What are the application steps?",
            "What are the eligibility requirements?",
        ]

    elif topic == "eligibility":
        from tools.eligibility_tool import get_eligibility
        _tt0 = time.perf_counter()
        result = get_eligibility(query)
        _emit_tool_result("eligibility_tool", result, round((time.perf_counter() - _tt0) * 1000, 1))
        heading     = "Eligibility Requirements"
        source_base = "https://www.csulb.edu/admissions/doctoral-programs-admission-eligibility"
        next_actions = [
            "Who is the advisor for my program?",
            "What are the application steps?",
            "When is the application deadline?",
        ]

    else:  # "application"
        from tools.application_steps_tool import get_application_steps
        _tt0 = time.perf_counter()
        result = get_application_steps(query)
        _emit_tool_result("application_steps_tool", result, round((time.perf_counter() - _tt0) * 1000, 1))
        heading     = "Application Steps"
        source_base = "https://www.csulb.edu/admissions/doctoral-programs-application-process"
        next_actions = [
            "Who is the advisor for my program?",
            "What are the eligibility requirements?",
            "When is the application deadline?",
        ]

    sources    = result.get("sources", [])
    source_url = sources[0] if sources else source_base
    results    = result.get("results", [])
    disclaimer = result.get("disclaimer", "")

    # Build a readable summary from the top RAG chunk or a generic fallback
    if results:
        raw = results[0].get("text", "").strip()
        # Avoid starting mid-word at the cutoff
        summary = (raw[:280].rsplit(" ", 1)[0] + "…") if len(raw) > 280 else raw
    elif result.get("fallback_data"):
        summary = f"Here is the {heading.lower()} information I found for CSULB doctoral programs."
    else:
        summary = (
            f"I couldn't find specific {heading.lower()} information for that query. "
            "Please check the official CSULB page."
        )

    primary_action = (
        disclaimer
        or f"Verify this information at the official CSULB page: {source_url}"
    )

    return {
        "query":          query,
        "route":          topic,           # "deadlines" | "eligibility" | "application"
        "session_id":     session_id,
        "summary":        summary,
        "primary_action": primary_action,
        "tool_result":    result,          # full tool output — used by _render_topic_panel()
        "source":         {"file": "", "url": source_url},
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
                "What are the GPA requirements for admission?",
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

    # ── Topic-priority routing (BEFORE find_advisor) ──────────────────────────
    # Program aliases like "dnp" / "nursing" fuzzy-match advisors at high
    # confidence, so without this check, "deadlines for dnp" would silently
    # return an advisor card instead of deadline information.
    #
    # Rule: if a topic-specific keyword is present AND no advisor-intent word
    # ("who", "advisor", "contact", …) is present, route straight to the tool.
    _raw_toks = set(re.findall(r"[a-z]+", query.lower()))

    _has_advisor_signal = bool(_raw_toks & _ADVISOR_SIGNALS)

    if not _has_advisor_signal:
        if _raw_toks & _DEADLINE_SIGNALS:
            emit("route.decision", level="INFO",
                 route="deadlines", reason="deadline_signal",
                 is_process_query=is_process_query,
                 has_advisor_signal=_has_advisor_signal,
                 matched_signals=sorted(_raw_toks & _DEADLINE_SIGNALS))
            return _build_topic_response("deadlines", query, session_id)
        if _raw_toks & _ELIGIBILITY_SIGNALS:
            emit("route.decision", level="INFO",
                 route="eligibility", reason="eligibility_signal",
                 is_process_query=is_process_query,
                 has_advisor_signal=_has_advisor_signal,
                 matched_signals=sorted(_raw_toks & _ELIGIBILITY_SIGNALS))
            return _build_topic_response("eligibility", query, session_id)
        # Application-steps: trigger when either:
        #   (a) explicit step/process/procedure signals present, OR
        #   (b) a specific program is named (e.g. "edd", "dpt", "dnp") — these
        #       always want program-specific RAG, not the generic 8-step guidance.
        # Generic "how do I apply?" without a named program keeps GUIDANCE path.
        _detected_program = _tool_detect_program(query)   # capture name for logging
        _has_program_signal = bool(_detected_program)
        if is_process_query and ((_raw_toks & _PROCESS_STEP_SIGNALS) or _has_program_signal):
            emit("route.decision", level="INFO",
                 route="application", reason="application_process",
                 is_process_query=is_process_query,
                 has_advisor_signal=_has_advisor_signal,
                 program_detected=_detected_program or "")
            return _build_topic_response("application", query, session_id)

    # ── Advisor retrieval ──────────────────────────────────────────────────────
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

        advisor_response = {
            "query":          query,
            "route":          "advisor",
            "session_id":     session_id,
            "summary":        (
                f"I found a {'Strong' if advisor_result['confidence'] >= 90 else 'Good'} "
                "match for your query."
            ) if match else "I couldn't find an exact match.",
            "primary_action": primary,
            "advisor_data":   advisor_result,
            "source":         {"file": "", "url": source_url},
            "next_actions": [
                "Show me the application steps",
                "What are the GPA requirements?",
                "When is the application deadline?",
            ],
        }

        # Auto-generate email draft when a specific advisor was matched.
        # The draft is included in the payload; the UI renders a preview and
        # an "Open in Outlook" button — Outlook is NEVER opened automatically.
        if match and match.get("advisor_name") and match.get("email"):
            from tools.email_tool import (
                draft_email      as _draft_email,
                build_outlook_url as _build_outlook_url,
            )
            _draft = _draft_email(
                advisor_name  = match["advisor_name"],
                advisor_email = match["email"],
                program       = match.get("program", ""),
                context       = "",   # user fills in "[Your Name]" placeholders
            )
            _outlook = (
                _build_outlook_url(
                    to_email = _draft.get("to", ""),
                    subject  = _draft.get("subject", ""),
                    body     = _draft.get("body", ""),
                )
                if _draft["found"]
                else {"found": False, "outlook_url": ""}
            )
            advisor_response["email_draft"] = {
                "found":       _draft["found"] and _outlook["found"],
                "subject":     _draft.get("subject", ""),
                "body":        _draft.get("body", ""),
                "to":          _draft.get("to", ""),
                "outlook_url": _outlook.get("outlook_url", ""),
            }

        _adv_reason = "advisor_fuzzy_match" if advisor_result["match"] else "advisor_suggestions"
        emit("route.decision", level="INFO",
             route="advisor", reason=_adv_reason,
             is_process_query=is_process_query,
             has_advisor_signal=_has_advisor_signal,
             advisor_score=advisor_result["confidence"])
        return advisor_response

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
        emit("route.decision", level="INFO",
             route="advisor", reason="doctoral_no_match",
             is_process_query=is_process_query,
             has_advisor_signal=_has_advisor_signal,
             advisor_score=advisor_result["confidence"])
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
        emit("route.decision", level="INFO",
             route="advisor", reason="advisor_intent_no_program",
             is_process_query=is_process_query,
             has_advisor_signal=_has_advisor_signal,
             advisor_score=0)
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

    # ── START-intent intercept ────────────────────────────────────────────────
    # Queries like "I don't know where to start" / "I'm confused" / "help me begin"
    # carry NO specific program or application keyword.  detect_route() maps them
    # to GUIDANCE, which calls guide_from_file() → detect_intent() matches "start"
    # to application_process and dumps the full general 7-step flow — wrong.
    #
    # Instead, detect START intent here (before detect_route) and route through
    # get_next_steps(), which returns the FAQ-enriched orientation response.
    # Token-based matching (not substring) so typos like "don;t" still match.
    # Only triggers when NO apply/doctoral keyword is also present, so
    # "I want to apply and don't know where to start" still goes to GUIDANCE.
    _START_TOKENS   = {"confused", "stuck", "lost", "overwhelmed",
                       "start", "begin", "beginning", "started"}
    _APPLY_SPECIFIC = {"apply", "application", "steps", "process",
                       "phd", "doctorate", "doctoral", "dnp", "dpt", "edd"}
    raw_tokens      = set(re.findall(r"[a-z]+", query.lower()))

    is_start_only = (
        bool(raw_tokens & _START_TOKENS)
        and not bool(raw_tokens & _APPLY_SPECIFIC)
    )

    if is_start_only:
        from next_steps import get_next_steps
        next_steps_result = get_next_steps(query)
        if next_steps_result:
            extra     = next_steps_result.get("extra_guidance") or ""
            resources = []
            summary   = (
                "Not sure where to begin? Here are some ways to get started with graduate admissions at CSULB."
            )
            primary = extra or "Request a free appointment with a Graduate Center Coordinator."
            emit("route.decision", level="INFO",
                 route="next_steps", reason="start_intent",
                 is_process_query=is_process_query,
                 has_advisor_signal=_has_advisor_signal)
            return {
                "query":          query,
                "route":          "next_steps",
                "session_id":     session_id,
                "summary":        summary,
                "primary_action": primary,
                "steps":          [
                    {"number": i + 1, "do": s}
                    for i, s in enumerate(next_steps_result.get("steps", []))
                ],
                "resources":      resources,
                "source":         {"file": "", "url": "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"},
                "next_actions": [
                    "Show me the application steps",
                    "Find my program advisor",
                    "What are the GPA requirements?",
                ],
            }

    route = detect_route(query)

    # Derive reason code from detect_route() outcome (mirrors detect_route()'s logic)
    _dr_first = next(iter(re.findall(r"[a-z]+", query.lower())), "")
    if route == Route.GUIDANCE:
        _dr_reason = "detect_route_guidance"
    elif _dr_first in {"is", "are", "does", "do", "can", "will", "should"}:
        _dr_reason = "detect_route_answer_starter"
    else:
        _dr_reason = "detect_route_answer_default"
    emit("route.decision", level="INFO",
         route=route.value, reason=_dr_reason,
         is_process_query=is_process_query,
         has_advisor_signal=_has_advisor_signal)

    raw      = _ROUTE_RUNNERS[route](query, session_id)
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
    if primary:
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
