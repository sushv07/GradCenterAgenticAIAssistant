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
import sys
import time
from dataclasses import replace
from typing import Any, Optional

from gradcenter_logging import emit
from telemetry import metrics
from telemetry.tracing import set_attributes, span

from retrieval.query_handler import handle_query
from agents.answer_agent import answer
from agents.guidance_agent import guide_from_file
from agents.journey_agent import handle_discovery
from routing.router import Route, RouteDecision, decide_route, detect_route
from contracts.response_types import OrchestratorResponse, TopicResponse
from responses.builder import build_response
from config.settings import DEFAULT_SESSION_ID, ADVISOR_STRONG_MATCH_THRESHOLD



# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------

def _run_guidance(query: str, session_id: str) -> dict:
    return guide_from_file(query)


def _build_faq_context(chunks: list[dict], max_chars: int) -> tuple[dict, str]:
    """Deterministic structured evidence for grounded FAQ synthesis.

    Splits retrieved chunks into FAQ entries and supporting-page passages,
    de-duplicates by source_url to avoid redundant evidence, and respects a
    character budget (chunks arrive score-sorted, so truncation keeps the most
    relevant). Returns (context_dict, top_source_url). Every passage carries its
    source_url so the synthesizer's existing URL-citation validation can key off
    it. The prompt is source-agnostic, so this structure needs no prompt change."""
    faqs: list[dict] = []
    supporting: list[dict] = []
    seen: set[str] = set()
    budget = max_chars
    top_url = ""

    for c in chunks:
        text = (c.get("text") or "").strip()
        src  = c.get("source_url") or c.get("url") or ""
        if not text or src in seen:
            continue
        if budget - len(text) < 0 and (faqs or supporting):
            break  # keep at least one passage; stop once the budget is spent
        budget -= len(text)
        seen.add(src)
        if c.get("is_supporting_page"):
            supporting.append({"title": c.get("title", ""), "text": text, "source_url": src})
        else:
            faqs.append({"question": c.get("faq_question", "") or c.get("title", ""),
                         "category": c.get("category", ""), "answer": text, "source_url": src})
            if not top_url:
                top_url = src

    if not top_url and supporting:
        top_url = supporting[0]["source_url"]
    return {"faqs": faqs, "supporting_evidence": supporting}, top_url


def _faq_synthesized_result(query: str, session_id: str) -> Optional[dict]:
    """Phase 4.3 — grounded FAQ synthesis. Retrieves FAQ + supporting evidence
    and synthesizes a grounded answer via the EXISTING synthesizer (reusing its
    prompt, URL/citation validation, and deterministic-None fallback). Returns a
    result dict for the answer route, or None to fall back to the existing
    keyword path. No new synthesizer, no prompt change."""
    from config.settings import (
        FAQ_SYNTHESIS_ENABLED, FAQ_TOP_K, FAQ_MIN_SCORE, FAQ_CONTEXT_MAX_CHARS,
    )
    if not FAQ_SYNTHESIS_ENABLED:
        return None

    from rag.retriever import retrieve
    chunks = retrieve(query, k=FAQ_TOP_K, min_score=FAQ_MIN_SCORE,
                      page_type=["faq", "faq_supporting"])
    if not chunks:
        return None  # case 4: no sufficient evidence → existing fallback

    context, top_url = _build_faq_context(chunks, FAQ_CONTEXT_MAX_CHARS)
    if not context["faqs"] and not context["supporting_evidence"]:
        return None

    from agents.llm_synthesizer import synthesize_answer
    llm = synthesize_answer(query, context, source_file="", source_url=top_url or None)
    if llm is None:
        return None  # LLM disabled / failed / fabricated-citation → existing fallback

    return {
        "answer":      llm["answer"],
        "confidence":  llm["confidence"],
        "answer_type": "faq_synthesized",
        "source_file": "",
        "source_url":  top_url,
    }


def _run_answer(query: str, session_id: str) -> dict:
    # Phase 4.3 — attempt grounded FAQ synthesis first (flag-gated). On success,
    # use it; otherwise fall through to the existing keyword answer path
    # unchanged (cases 2/3 synthesize from whatever evidence was retrieved;
    # case 4 / disabled / LLM-failure → deterministic existing behavior).
    _faq = _faq_synthesized_result(query, session_id)
    if _faq is not None:
        return _faq
    retrieved = handle_query(query)
    _t0 = time.perf_counter()
    result = answer(query, retrieved)
    from agents.llm_synthesizer import synthesize_answer as _synth
    _llm = _synth(
        query,
        retrieved,
        source_file=result.get("source_file", ""),
        source_url=result.get("source_url"),
    )
    if _llm is not None:
        result = {
            **result,
            "answer":      _llm["answer"],
            "confidence":  _llm["confidence"],
            "answer_type": "llm_synthesized",
        }
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

    # AI observability (Phase 3): answer metrics + enrich the root pipeline span
    # with why-this-answer attributes (current span here is pipeline.request,
    # route.decide having already closed). No behavior change.
    _atype = result.get("answer_type", "unknown")
    _conf  = result.get("confidence", "low")
    metrics.record_answer(_atype, _conf, _elapsed / 1000.0)
    set_attributes(**{
        "answer_type":       _atype,
        "confidence":        _conf,
        "source_file":       result.get("source_file", ""),
        "answer.synthesized": _atype == "llm_synthesized",
    })
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


def _format_response(query: str, route: Route, raw: dict, session_id: str) -> dict:
    """Wrap raw agent output with a user-friendly presentation."""
    body = _HUMANIZERS[route](query, raw)

    next_actions   = body.pop("next_actions", []) or []
    summary        = body.pop("summary")
    primary_action = body.pop("primary_action")

    return build_response(
        query=query,
        route=route.value,
        session_id=session_id,
        summary=summary,
        primary_action=primary_action,
        source={
            "file": raw.get("source_file", ""),
            "url":  raw.get("source_url", "https://www.csulb.edu/graduate-center"),
        },
        next_actions=next_actions,
        extra=body,
    )


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
# Program-context continuity (shared by all program-aware routes)
# ---------------------------------------------------------------------------

def _resolve_and_augment(query: str, session_id: str) -> tuple[str, Optional[dict]]:
    """Resolve the turn's program context; return (tool_query, active_program).

    - Explicit program in the query becomes the session's active program and is
      persisted (so later pronoun follow-ups resolve to it); tool_query is the
      original query (the program is already in it).
    - A contextual reference ("this program", "it", …) with an existing active
      program yields an augmented tool_query (active program appended) for the
      route/tool only.
    - Otherwise tool_query is the original query (normal clarification behavior).

    The user-facing query and displayed text are never modified — only the
    returned tool_query (internal) may be augmented.
    """
    from agents.journey_agent import init_journey_state
    from state.context_manager import get_context, save_context
    from state.program_context import resolve_program_context

    journey_state = get_context(session_id, init_journey_state).journey_state
    res = resolve_program_context(query, journey_state)
    if res["changed"] and res["active"]:
        journey_state["active_program"] = res["active"]
        save_context(session_id, journey_state)
    return res["tool_query"], res["active"]


# ---------------------------------------------------------------------------
# Application route — applicant-type gate + international guidance
# ---------------------------------------------------------------------------
# Generic across all programs: driven by the shared active_program + the one
# canonical applicant_type field. When a program is resolved but the applicant
# type is unknown, a typed PendingClarification is stored and the reply resumes
# via the shared clarification framework (state/clarification.py) — no parallel
# resume path, no per-program branch.

_APPLICATION_NEXT_ACTIONS = [
    "Who is the advisor for my program?",
    "What are the eligibility requirements?",
    "When is the application deadline?",
]
_APPLICATION_SOURCE_BASE = "https://www.csulb.edu/admissions/doctoral-programs-application-process"


def _load_state(session_id: str):
    from agents.journey_agent import init_journey_state
    from state.context_manager import get_context
    return get_context(session_id, init_journey_state).journey_state


def _application_workflow_response(session_id: str, tool_query: str, query: str,
                                   applicant_type: str) -> dict:
    """The program-specific application workflow response, with international
    guidance prepended (as a supplement, never a replacement) when the applicant
    is international. Program-specific selection/fallback is unchanged."""
    from tools.application_steps_tool import get_application_steps

    _tt0 = time.perf_counter()
    result = get_application_steps(tool_query)
    _emit_tool_result("application_steps_tool", result,
                      round((time.perf_counter() - _tt0) * 1000, 1))

    sources    = result.get("sources", [])
    source_url = sources[0] if sources else _APPLICATION_SOURCE_BASE
    results    = result.get("results", [])
    disclaimer = result.get("disclaimer", "")

    if results:
        raw = results[0].get("text", "").strip()
        summary = (raw[:280].rsplit(" ", 1)[0] + "…") if len(raw) > 280 else raw
    elif result.get("fallback_data"):
        summary = "Here is the application steps information I found for CSULB doctoral programs."
    else:
        summary = ("I couldn't find specific application steps for that query. "
                   "Please check the official CSULB page.")

    extra: dict = {"tool_result": result, "applicant_type": applicant_type}
    if applicant_type == "international":
        from config.international import INTERNATIONAL_INFO
        extra["international_info"] = INTERNATIONAL_INFO  # supplement, shown BEFORE the workflow

    return build_response(
        query=query, route="application", session_id=session_id,
        summary=summary,
        primary_action=disclaimer or f"Verify this information at the official CSULB page: {source_url}",
        source={"file": "", "url": source_url},
        next_actions=_APPLICATION_NEXT_ACTIONS,
        extra=extra,
    )


def _build_application_response(session_id: str, tool_query: str, query: str) -> dict:
    """Application route entry: ask applicant type first (once) when a program is
    resolved but the type is unknown; otherwise render the workflow."""
    from state.clarification import set_pending
    from state.context_manager import save_context

    js = _load_state(session_id)
    active = js.get("active_program")
    applicant_type = js.get("applicant_type", "")

    # Gate — only when a specific program is resolved AND the type is unknown.
    if active and not applicant_type:
        question = ("Before I show the application steps, are you applying as a "
                    "domestic or international student?")
        set_pending(js, "applicant_type", route="application",
                    question=question, original_query=query)
        save_context(session_id, js)
        # Return the clarification metadata INSIDE tool_result so the response
        # is a valid TopicResponseModel (route="application" requires
        # tool_result) — FastAPI response validation stays intact.
        return build_response(
            query=query, route="application", session_id=session_id,
            summary=question,
            primary_action="Choose Domestic student or International student to continue.",
            source={"file": "", "url": "https://www.csulb.edu/graduate-center"},
            next_actions=[],
            extra={"tool_result": {
                "needs_applicant_type":  True,
                "applicant_type_choices": ["domestic", "international"],
            }},
        )

    return _application_workflow_response(session_id, tool_query, query, applicant_type)


def resume_applicant_type_clarification(query: str, session_id: str, pending) -> Optional[dict]:
    """Resumer (registered for kind="applicant_type"): consume the domestic/
    international reply, persist it, and resume the pending application request
    for the active program. Returns None if the reply isn't an applicant type
    (the pending clarification is abandoned and the message routes normally)."""
    from state.clarification import clear_pending, parse_applicant_type
    from state.context_manager import save_context
    from state.program_context import augment_query_with_active_program

    at = parse_applicant_type(query)
    js = _load_state(session_id)
    if at is None:
        clear_pending(js)
        save_context(session_id, js)
        return None

    js["applicant_type"] = at
    clear_pending(js)
    save_context(session_id, js)

    original = (pending or {}).get("original_query") or "what are the application steps"
    tool_query = augment_query_with_active_program(original, js.get("active_program"))
    return _application_workflow_response(session_id, tool_query, original, at)


def _applicant_type_ack(query: str, session_id: str, applicant_type: str) -> dict:
    """Brief acknowledgment when the user only states their applicant type.

    Shaped as a valid AnswerResponseModel (route="answer" + answer/confidence +
    source) so it passes FastAPI response validation like any other answer."""
    text = f"Got it — I'll tailor application guidance for {applicant_type} applicants."
    return build_response(
        query=query, route="answer", session_id=session_id,
        summary=text,
        primary_action="Ask for your program's application steps and I'll include the right guidance.",
        source={"file": "", "url": "https://www.csulb.edu/graduate-center"},
        next_actions=[],
        extra={"answer": text, "confidence": "high", "applicant_type": applicant_type},
    )


# Register the applicant-type resumer with the shared clarification framework
# (state/clarification.py). backend.entrypoint dispatches replies to pending
# clarifications through that single registry — no parallel resume path.
from state.clarification import register_resumer as _register_resumer  # noqa: E402
_register_resumer("applicant_type", resume_applicant_type_clarification)


def _set_applicant_type(session_id: str, applicant_type: str) -> None:
    """Persist an explicitly-stated applicant type (Examples D/E)."""
    from state.context_manager import save_context
    js = _load_state(session_id)
    if js.get("applicant_type") != applicant_type:
        js["applicant_type"] = applicant_type
        save_context(session_id, js)


# ---------------------------------------------------------------------------
# Topic-tool response builder
# ---------------------------------------------------------------------------

def _build_topic_response(topic: str, query: str, session_id: str,
                          tool_query: Optional[str] = None) -> TopicResponse:
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
    # Program-context continuity: the route/tools use tool_query (may be the
    # active program-augmented query, resolved at the orchestrator boundary);
    # the response is built with the ORIGINAL query for display.
    tool_query = tool_query or query

    if topic == "deadlines":
        from tools.deadlines_tool import get_deadlines
        _tt0 = time.perf_counter()
        result = get_deadlines(tool_query)
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
        result = get_eligibility(tool_query)
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
        result = get_application_steps(tool_query)
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

    return build_response(
        query=query,
        route=topic,           # "deadlines" | "eligibility" | "application"
        session_id=session_id,
        summary=summary,
        primary_action=primary_action,
        source={"file": "", "url": source_url},
        next_actions=next_actions,
        extra={"tool_result": result},  # full tool output — used by _render_topic_panel()
    )


# ---------------------------------------------------------------------------
# Response builders for advisor and next_steps routes
# (these were inline in run(); extracted here now that routing is separate)
# ---------------------------------------------------------------------------

def _build_advisor_response(decision: RouteDecision) -> dict:
    """Build the advisor response from a pre-routed RouteDecision.

    Program-context continuity is handled at the orchestrator boundary
    (orchestrator.run augments the query before decide_route), so the router's
    find_advisor() already ran against the active program for contextual
    follow-ups — this builder needs no program-context logic of its own.
    """
    advisor_result = decision.advisor_result or {}

    if decision.reason == "doctoral_no_match":
        return build_response(
            query=decision.query,
            route="advisor",
            session_id=decision.session_id,
            summary="There's no doctoral program matching that at CSULB — but here are the doctoral and professional programs we do have advisor information for.",
            primary_action="Pick the closest program below and I can show you the advisor contact and application steps.",
            source={"file": "", "url": "https://www.csulb.edu/graduate-center"},
            next_actions=[
                "Engineering PhD advisor",
                "Nursing DNP advisor",
                "Physical therapy advisor",
            ],
            extra={"advisor_data": {
                "match":          None,
                "confidence":     advisor_result.get("confidence", 0),
                "suggestions":    [],
                "known_programs": decision.known_programs,
            }},
        )

    if decision.reason == "advisor_intent_no_program":
        return build_response(
            query=decision.query,
            route="advisor",
            session_id=decision.session_id,
            summary="It looks like you're looking for an advisor — I just need the program name.",
            primary_action="Try something like: \"nursing advisor\", \"dnp advisor\", or \"engineering phd advisor\".",
            source={"file": "", "url": "https://www.csulb.edu/graduate-center"},
            next_actions=[
                "Nursing advisor",
                "Engineering phd advisor",
                "Physical therapy advisor",
            ],
            extra={"advisor_data": {
                "match":          None,
                "confidence":     0,
                "suggestions":    [],
                "known_programs": decision.known_programs,
            }},
        )

    # reason is "advisor_fuzzy_match" or "advisor_suggestions"
    match      = advisor_result.get("match")
    source_url = (match or {}).get("source", "https://www.csulb.edu/graduate-center")
    primary    = (
        f"Email {match['email']} to schedule an advising appointment."
        if match and match.get("email")
        else "Contact GraduateCenter@csulb.edu for advisor information."
    )

    advisor_response: dict = build_response(
        query=decision.query,
        route="advisor",
        session_id=decision.session_id,
        summary=(
            f"I found a {'Strong' if advisor_result.get('confidence', 0) >= ADVISOR_STRONG_MATCH_THRESHOLD else 'Good'} "
            "match for your query."
        ) if match else "I couldn't find an exact match.",
        primary_action=primary,
        source={"file": "", "url": source_url},
        next_actions=[
            "Show me the application steps",
            "What are the GPA requirements?",
            "When is the application deadline?",
        ],
        extra={"advisor_data": advisor_result},
    )

    if match and match.get("advisor_name") and match.get("email"):
        from tools.email_tool import (
            draft_email       as _draft_email,
            build_outlook_url as _build_outlook_url,
        )
        _draft = _draft_email(
            advisor_name  = match["advisor_name"],
            advisor_email = match["email"],
            program       = match.get("program", ""),
            context       = "",
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

    return advisor_response


def _build_next_steps_response(decision: RouteDecision) -> dict:
    """Build the next_steps response from a pre-routed RouteDecision."""
    nsr     = decision.next_steps_result or {}
    extra   = nsr.get("extra_guidance") or ""
    primary = extra or "Request a free appointment with a Graduate Center Coordinator."
    return build_response(
        query=decision.query,
        route="next_steps",
        session_id=decision.session_id,
        summary="Not sure where to begin? Here are some ways to get started with graduate admissions at CSULB.",
        primary_action=primary,
        source={"file": "", "url": "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"},
        next_actions=[
            "Show me the application steps",
            "Find my program advisor",
            "What are the GPA requirements?",
        ],
        extra={
            "steps": [
                {"number": i + 1, "do": s}
                for i, s in enumerate(nsr.get("steps", []))
            ],
            "resources": [],
        },
    )


def _dispatch(decision: RouteDecision) -> OrchestratorResponse:
    """Map a RouteDecision to the appropriate response builder."""
    if decision.route == "welcome":
        return build_response(
            route=None,
            session_id=decision.session_id,
            summary="Welcome to the Grad Center. What can I help you with today?",
            primary_action="Ask me about admissions, your program, or any step in the process — or pick a starting point below.",
            next_actions=[
                "How do I apply to a graduate program?",
                "What are the GPA requirements for admission?",
                "Who do I contact about thesis submission?",
            ],
        )

    if decision.route == "application":
        return _build_application_response(
            decision.session_id, decision.tool_query or decision.query, decision.query)

    if decision.route in ("deadlines", "eligibility"):
        return _build_topic_response(
            decision.route, decision.query, decision.session_id,
            decision.tool_query or decision.query)

    if decision.route == "advisor":
        return _build_advisor_response(decision)

    if decision.route == "next_steps":
        return _build_next_steps_response(decision)

    if decision.route == "discovery":
        response, _ = handle_discovery(decision.query, decision.session_id)
        return response

    # "guidance" | "answer" — the answer route is program-aware, so it consumes
    # the resolved tool_query; display still uses the original query.
    route_enum = Route(decision.route)
    raw        = _ROUTE_RUNNERS[route_enum](
        decision.tool_query or decision.query, decision.session_id)
    return _format_response(decision.query, route_enum, raw, decision.session_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(query: str, session_id: str = DEFAULT_SESSION_ID) -> OrchestratorResponse:
    """Route the query, run the agent, and return a user-friendly response."""
    query = (query or "").strip()
    # Program-context continuity: resolve "this program"/"it" against the active
    # program and persist an explicitly-named one. Route + tools see the
    # (possibly augmented) tool_query so ROUTING itself resolves the program;
    # the user-facing query stays original.
    tool_query, _active = _resolve_and_augment(query, session_id)

    # Applicant type: an explicit statement ("I'm an international student")
    # updates the one canonical field; a bare statement is acknowledged, while
    # a statement carrying an actionable request falls through to normal routing
    # (which will read the now-known type on the application route).
    from state.clarification import is_bare_applicant_statement, parse_applicant_type
    _at = parse_applicant_type(query)
    if _at:
        _set_applicant_type(session_id, _at)

    with span("route.decide"):
        _t_route = time.perf_counter()
        decision = decide_route(tool_query, session_id)
        metrics.observe_routing(time.perf_counter() - _t_route)
        decision = replace(decision, query=query, tool_query=tool_query)
        set_attributes(**{"route.selected": decision.route,
                          "route.reason": getattr(decision, "reason", None)})

    if _at and is_bare_applicant_statement(query) and decision.route in ("answer", "guidance"):
        return _applicant_type_ack(query, session_id, _at)

    return _dispatch(decision)


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
    session_id, args = _extract_flag(args, "--session", DEFAULT_SESSION_ID)

    if args:
        response = run(" ".join(args), session_id=session_id)
        if pretty:
            print(format_for_display(response))
        else:
            print(json.dumps(response, indent=2))
    else:
        _repl(pretty=pretty, session_id=session_id)
