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

from gradcenter_logging import emit

from retrieval.query_handler import handle_query
from agents.answer_agent import answer
from agents.guidance_agent import guide_from_file
from agents.journey_agent import handle_discovery
from routing.router import Route, RouteDecision, decide_route, detect_route
from contracts.response_types import OrchestratorResponse, TopicResponse



# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------

def _run_guidance(query: str, session_id: str) -> dict:
    return guide_from_file(query)


def _run_answer(query: str, session_id: str) -> dict:
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

def _build_topic_response(topic: str, query: str, session_id: str) -> TopicResponse:
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
# Response builders for advisor and next_steps routes
# (these were inline in run(); extracted here now that routing is separate)
# ---------------------------------------------------------------------------

def _build_advisor_response(decision: RouteDecision) -> dict:
    """Build the advisor response from a pre-routed RouteDecision."""
    advisor_result = decision.advisor_result or {}

    if decision.reason == "doctoral_no_match":
        return {
            "query":          decision.query,
            "route":          "advisor",
            "session_id":     decision.session_id,
            "summary":        "There's no doctoral program matching that at CSULB — but here are the doctoral and professional programs we do have advisor information for.",
            "primary_action": "Pick the closest program below and I can show you the advisor contact and application steps.",
            "advisor_data":   {
                "match":          None,
                "confidence":     advisor_result.get("confidence", 0),
                "suggestions":    [],
                "known_programs": decision.known_programs,
            },
            "source":         {"file": "", "url": "https://www.csulb.edu/graduate-center"},
            "next_actions": [
                "Engineering PhD advisor",
                "Nursing DNP advisor",
                "Physical therapy advisor",
            ],
        }

    if decision.reason == "advisor_intent_no_program":
        return {
            "query":          decision.query,
            "route":          "advisor",
            "session_id":     decision.session_id,
            "summary":        "It looks like you're looking for an advisor — I just need the program name.",
            "primary_action": "Try something like: \"nursing advisor\", \"dnp advisor\", or \"engineering phd advisor\".",
            "advisor_data":   {
                "match":          None,
                "confidence":     0,
                "suggestions":    [],
                "known_programs": decision.known_programs,
            },
            "source":         {"file": "", "url": "https://www.csulb.edu/graduate-center"},
            "next_actions": [
                "Nursing advisor",
                "Engineering phd advisor",
                "Physical therapy advisor",
            ],
        }

    # reason is "advisor_fuzzy_match" or "advisor_suggestions"
    match      = advisor_result.get("match")
    source_url = (match or {}).get("source", "https://www.csulb.edu/graduate-center")
    primary    = (
        f"Email {match['email']} to schedule an advising appointment."
        if match and match.get("email")
        else "Contact GraduateCenter@csulb.edu for advisor information."
    )

    advisor_response: dict = {
        "query":          decision.query,
        "route":          "advisor",
        "session_id":     decision.session_id,
        "summary":        (
            f"I found a {'Strong' if advisor_result.get('confidence', 0) >= 90 else 'Good'} "
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
    return {
        "query":          decision.query,
        "route":          "next_steps",
        "session_id":     decision.session_id,
        "summary":        "Not sure where to begin? Here are some ways to get started with graduate admissions at CSULB.",
        "primary_action": primary,
        "steps":          [
            {"number": i + 1, "do": s}
            for i, s in enumerate(nsr.get("steps", []))
        ],
        "resources":      [],
        "source":         {"file": "", "url": "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"},
        "next_actions": [
            "Show me the application steps",
            "Find my program advisor",
            "What are the GPA requirements?",
        ],
    }


def _dispatch(decision: RouteDecision) -> OrchestratorResponse:
    """Map a RouteDecision to the appropriate response builder."""
    if decision.route == "welcome":
        return {
            "route":          None,
            "session_id":     decision.session_id,
            "summary":        "Welcome to the Grad Center. What can I help you with today?",
            "primary_action": "Ask me about admissions, your program, or any step in the process — or pick a starting point below.",
            "next_actions": [
                "How do I apply to a graduate program?",
                "What are the GPA requirements for admission?",
                "Who do I contact about thesis submission?",
            ],
        }

    if decision.route in ("deadlines", "eligibility", "application"):
        return _build_topic_response(decision.route, decision.query, decision.session_id)

    if decision.route == "advisor":
        return _build_advisor_response(decision)

    if decision.route == "next_steps":
        return _build_next_steps_response(decision)

    if decision.route == "discovery":
        response, _ = handle_discovery(decision.query, decision.session_id)
        return response

    # "guidance" | "answer"
    route_enum = Route(decision.route)
    raw        = _ROUTE_RUNNERS[route_enum](decision.query, decision.session_id)
    response   = _format_response(decision.query, route_enum, raw)
    response["session_id"] = decision.session_id
    return response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(query: str, session_id: str = "default") -> OrchestratorResponse:
    """Route the query, run the agent, and return a user-friendly response."""
    query    = (query or "").strip()
    decision = decide_route(query, session_id)
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
