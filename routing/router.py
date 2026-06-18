"""
router.py
Routing decision layer for the Grad Center orchestrator.

Implements the 10-branch routing priority chain and returns a RouteDecision
dataclass carrying the route name, reason code, and all pre-fetched payloads
the dispatcher needs.  The orchestrator reads RouteDecision and builds
responses without re-calling any external service.

Branch priority order (identical to the original orchestrator.run() chain):
  1  empty query               → route="welcome"
  2  deadline signals          → route="deadlines"
  3  eligibility signals       → route="eligibility"
  4  application-step signals  → route="application"
  5  advisor fuzzy match       → route="advisor"  reason="advisor_fuzzy_match|advisor_suggestions"
  6  doctoral tokens, no match → route="advisor"  reason="doctoral_no_match"
  7  advisor intent, 0 conf    → route="advisor"  reason="advisor_intent_no_program"
  8  start-only intent         → route="next_steps"
  9  detect_route → GUIDANCE   → route="guidance"
 10  detect_route → ANSWER     → route="answer"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from gradcenter_logging import emit
from retrieval.advisor_retrieval import find_advisor, advisors
from tools.application_steps_tool import _detect_program as _tool_detect_program


# ---------------------------------------------------------------------------
# Route enum  (moved here from orchestrator so detect_route() can live here
# without creating a circular import)
# ---------------------------------------------------------------------------

class Route(str, Enum):
    GUIDANCE = "guidance"
    ANSWER   = "answer"


# ---------------------------------------------------------------------------
# Routing signal constants
# (module-level so they are not recreated on every decide_route() call)
# ---------------------------------------------------------------------------

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

# Words that (combined with is_process_query) route to application_steps_tool.
# "apply" / "application" alone stay on the GUIDANCE path for generic queries;
# "steps" / "process" / "procedure" signals the user wants an ordered list.
_PROCESS_STEP_SIGNALS = frozenset({
    "steps", "process", "procedure",
})

_PROCESS_KEYWORDS = {
    "apply", "application", "steps", "process", "start",
    "begin", "beginning", "confused", "stuck", "where to start",
    "where to begin", "don't know",
}

_DOCTORAL_TOKENS = frozenset({
    "phd", "ph", "doctorate", "doctoral", "doctor", "edd", "dpt", "dnp",
})

_ADVISOR_INTENT = frozenset({
    "contact", "advisor", "adviser", "advising", "talk", "speak", "email", "reach",
})

_START_TOKENS = frozenset({
    "confused", "stuck", "lost", "overwhelmed",
    "start", "begin", "beginning", "started",
})

_APPLY_SPECIFIC = frozenset({
    "apply", "application", "steps", "process",
    "phd", "doctorate", "doctoral", "dnp", "dpt", "edd",
})

_GUIDANCE_DOMAIN = {
    "apply", "applying", "applied", "application",
    "admitted", "accepted", "enrolled", "newly",
    "international", "eligibility", "eligible",
    "orientation", "steps", "process", "procedure",
    "start", "begin", "started", "beginning", "confused", "stuck", "help",
}

# Multi-word phrases that signal a student exploring which program to pursue.
# Checked via substring match on the lowercased query (not token intersection)
# because the meaningful signal is the full phrase, not individual tokens.
# Branch 1.5 — fires after advisor-signal check, before topic routing (branches 2–4).
_DISCOVERY_SIGNALS = frozenset({
    "interested in",
    "which program",
    "help me choose",
    "want to become",
    "looking for a doctoral",
    "what programs",
    "recommend a program",
    "career in",
    "i want to study",
})


# ---------------------------------------------------------------------------
# RouteDecision dataclass
# ---------------------------------------------------------------------------

@dataclass
class RouteDecision:
    route:      str     # "welcome"|"deadlines"|"eligibility"|"application"|
                        #  "advisor"|"next_steps"|"guidance"|"answer"
    reason:     str     # log reason code — mirrors emit("route.decision", reason=...)
    query:      str
    session_id: str

    is_process_query:   bool = False
    has_advisor_signal: bool = False

    # Pre-fetched payloads — only the relevant one is non-None per decision.
    # The dispatcher reads these; it never calls the external service again.
    advisor_result:    dict | None = None   # from find_advisor()
    detected_program:  str  | None = None   # from _tool_detect_program()
    next_steps_result: dict | None = None   # from get_next_steps()
    known_programs:    list        = field(default_factory=list)

    # Logging extras
    matched_signals: list = field(default_factory=list)
    advisor_score:   int  = 0


# ---------------------------------------------------------------------------
# detect_route()  (public — kept in this module; re-exported via orchestrator)
# ---------------------------------------------------------------------------

def detect_route(query: str) -> Route:
    """
    Routing precedence:
      1. GUIDANCE    — any guidance domain word (apply / steps / admitted / …)
      2. ANSWER      — yes/no question-starter (is / are / does / …)
      3. ANSWER (default) — fallback for everything else
    """
    tokens     = set(re.findall(r"[a-z0-9]+", query.lower()))
    first_word = next(iter(re.findall(r"[a-z]+", query.lower())), "")
    if first_word in {"is", "are", "does", "do", "can", "will", "should"}:
        return Route.ANSWER
    if _GUIDANCE_DOMAIN & tokens:
        return Route.GUIDANCE
    return Route.ANSWER


# ---------------------------------------------------------------------------
# Public routing API
# ---------------------------------------------------------------------------

def decide_route(query: str, session_id: str) -> RouteDecision:
    """
    Evaluate the full 10-branch routing priority chain and return a RouteDecision.

    All emit("route.decision") calls happen here — the orchestrator dispatcher
    builds responses without re-calling any external service.
    """
    # ── Branch 1: empty query → welcome ──────────────────────────────────────
    if not query:
        return RouteDecision(
            route="welcome", reason="empty_query",
            query=query, session_id=session_id,
        )

    # ── Shared pre-computation (token set computed once for all branches) ─────
    _q               = query.lower()
    is_process_query = any(k in _q for k in _PROCESS_KEYWORDS)
    raw_toks         = set(re.findall(r"[a-z]+", query.lower()))
    has_advisor_signal = bool(raw_toks & _ADVISOR_SIGNALS)

    # ── Branch 1.5: discovery intent signals ─────────────────────────────────
    # Fires when the student is exploring which program to pursue.
    # Guarded by has_advisor_signal and explicit topic signals (deadlines,
    # eligibility) so "deadlines for the program I'm interested in" still
    # routes to deadlines rather than discovery.
    if not has_advisor_signal and not (
        (raw_toks & _DEADLINE_SIGNALS) or (raw_toks & _ELIGIBILITY_SIGNALS)
    ):
        matched_disc = sorted(p for p in _DISCOVERY_SIGNALS if p in _q)
        if matched_disc:
            emit("route.decision", level="INFO",
                 route="discovery", reason="discovery_signal",
                 is_process_query=is_process_query,
                 has_advisor_signal=has_advisor_signal,
                 matched_signals=matched_disc)
            return RouteDecision(
                route="discovery", reason="discovery_signal",
                query=query, session_id=session_id,
                is_process_query=is_process_query,
                has_advisor_signal=has_advisor_signal,
                matched_signals=matched_disc,
            )

    # ── Branches 2–4: topic-priority routing (BEFORE find_advisor) ───────────
    # Program aliases like "dnp" / "nursing" fuzzy-match advisors at high
    # confidence — without this block, "deadlines for dnp" would return an
    # advisor card instead of deadline information.
    if not has_advisor_signal:

        # Branch 2: deadlines
        if raw_toks & _DEADLINE_SIGNALS:
            matched = sorted(raw_toks & _DEADLINE_SIGNALS)
            emit("route.decision", level="INFO",
                 route="deadlines", reason="deadline_signal",
                 is_process_query=is_process_query,
                 has_advisor_signal=has_advisor_signal,
                 matched_signals=matched)
            return RouteDecision(
                route="deadlines", reason="deadline_signal",
                query=query, session_id=session_id,
                is_process_query=is_process_query,
                has_advisor_signal=has_advisor_signal,
                matched_signals=matched,
            )

        # Branch 3: eligibility
        if raw_toks & _ELIGIBILITY_SIGNALS:
            matched = sorted(raw_toks & _ELIGIBILITY_SIGNALS)
            emit("route.decision", level="INFO",
                 route="eligibility", reason="eligibility_signal",
                 is_process_query=is_process_query,
                 has_advisor_signal=has_advisor_signal,
                 matched_signals=matched)
            return RouteDecision(
                route="eligibility", reason="eligibility_signal",
                query=query, session_id=session_id,
                is_process_query=is_process_query,
                has_advisor_signal=has_advisor_signal,
                matched_signals=matched,
            )

        # Branch 4: application steps.
        # _tool_detect_program is called here (even when process_step signals
        # alone would suffice) to preserve the original call-site behavior.
        detected_program = _tool_detect_program(query)
        if is_process_query and (
            (raw_toks & _PROCESS_STEP_SIGNALS) or bool(detected_program)
        ):
            emit("route.decision", level="INFO",
                 route="application", reason="application_process",
                 is_process_query=is_process_query,
                 has_advisor_signal=has_advisor_signal,
                 program_detected=detected_program or "")
            return RouteDecision(
                route="application", reason="application_process",
                query=query, session_id=session_id,
                is_process_query=is_process_query,
                has_advisor_signal=has_advisor_signal,
                detected_program=detected_program,
            )

    # ── Advisor retrieval (called once; result shared by branches 5, 6, 7) ───
    advisor_result = find_advisor(query)

    # ── Branch 5: advisor fuzzy match or suggestions ──────────────────────────
    if not is_process_query and (
        advisor_result["match"] or advisor_result["suggestions"]
    ):
        adv_reason = (
            "advisor_fuzzy_match" if advisor_result["match"] else "advisor_suggestions"
        )
        emit("route.decision", level="INFO",
             route="advisor", reason=adv_reason,
             is_process_query=is_process_query,
             has_advisor_signal=has_advisor_signal,
             advisor_score=advisor_result["confidence"])
        return RouteDecision(
            route="advisor", reason=adv_reason,
            query=query, session_id=session_id,
            is_process_query=is_process_query,
            has_advisor_signal=has_advisor_signal,
            advisor_result=advisor_result,
            advisor_score=advisor_result["confidence"],
        )

    # ── Branch 6: doctoral tokens, no match ──────────────────────────────────
    if raw_toks & _DOCTORAL_TOKENS and not (
        advisor_result["match"] or advisor_result["suggestions"]
    ):
        doctoral = [
            a for a in advisors
            if any(
                kw in (a.get("program") or "").lower()
                for kw in ["ph.d", "phd", "ed.d", "dpt", "d.n.p", "dr.p.h", "dnp"]
            )
        ]
        prog_names = [a["program"] for a in doctoral if a.get("program")]
        emit("route.decision", level="INFO",
             route="advisor", reason="doctoral_no_match",
             is_process_query=is_process_query,
             has_advisor_signal=has_advisor_signal,
             advisor_score=advisor_result["confidence"])
        return RouteDecision(
            route="advisor", reason="doctoral_no_match",
            query=query, session_id=session_id,
            is_process_query=is_process_query,
            has_advisor_signal=has_advisor_signal,
            advisor_result=advisor_result,
            known_programs=prog_names,
            advisor_score=advisor_result["confidence"],
        )

    # ── Branch 7: advisor intent with no program ──────────────────────────────
    if advisor_result["confidence"] == 0 and raw_toks & _ADVISOR_INTENT:
        known = [a["program"] for a in advisors if a.get("program")]
        emit("route.decision", level="INFO",
             route="advisor", reason="advisor_intent_no_program",
             is_process_query=is_process_query,
             has_advisor_signal=has_advisor_signal,
             advisor_score=0)
        return RouteDecision(
            route="advisor", reason="advisor_intent_no_program",
            query=query, session_id=session_id,
            is_process_query=is_process_query,
            has_advisor_signal=has_advisor_signal,
            advisor_result=advisor_result,
            known_programs=known,
            advisor_score=0,
        )

    # ── Branch 8: start-only intent → next_steps ─────────────────────────────
    is_start_only = (
        bool(raw_toks & _START_TOKENS)
        and not bool(raw_toks & _APPLY_SPECIFIC)
    )
    if is_start_only:
        from agents.next_steps import get_next_steps
        next_steps_result = get_next_steps(query)
        if next_steps_result:
            emit("route.decision", level="INFO",
                 route="next_steps", reason="start_intent",
                 is_process_query=is_process_query,
                 has_advisor_signal=has_advisor_signal)
            return RouteDecision(
                route="next_steps", reason="start_intent",
                query=query, session_id=session_id,
                is_process_query=is_process_query,
                has_advisor_signal=has_advisor_signal,
                next_steps_result=next_steps_result,
            )

    # ── Branches 9 + 10: detect_route() fallback (guidance or answer) ─────────
    fallback_route = detect_route(query)
    first_word     = next(iter(re.findall(r"[a-z]+", query.lower())), "")
    if fallback_route == Route.GUIDANCE:
        dr_reason = "detect_route_guidance"
    elif first_word in {"is", "are", "does", "do", "can", "will", "should"}:
        dr_reason = "detect_route_answer_starter"
    else:
        dr_reason = "detect_route_answer_default"
    emit("route.decision", level="INFO",
         route=fallback_route.value, reason=dr_reason,
         is_process_query=is_process_query,
         has_advisor_signal=has_advisor_signal)
    return RouteDecision(
        route=fallback_route.value, reason=dr_reason,
        query=query, session_id=session_id,
        is_process_query=is_process_query,
        has_advisor_signal=has_advisor_signal,
    )
