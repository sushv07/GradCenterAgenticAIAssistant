"""
test_router.py
Unit tests for router.decide_route().

All three external callsites are mocked so these tests run with no Chroma,
no filesystem access, and no RapidFuzz scoring — pure routing logic only.

Mocked callsites:
  routing.router.find_advisor         — RapidFuzz in-memory (cheap but side-effectful)
  routing.router._tool_detect_program — in-memory alias map
  router.get_next_steps       — Chroma / faq_rag (real retrieval)

Run from the project root:
    python test_router.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent.parent))


import sys
from unittest.mock import patch

from routing.router import decide_route, RouteDecision

# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------

_NO_MATCH = {"match": None, "confidence": 0, "suggestions": []}

def _advisor_match(name: str, email: str, program: str, score: int = 95) -> dict:
    return {
        "match": {
            "advisor_name": name,
            "email":        email,
            "program":      program,
            "source":       "https://www.csulb.edu/graduate-center",
        },
        "confidence": score,
        "suggestions": [],
    }

def _advisor_suggestions(suggs: list[str]) -> dict:
    return {"match": None, "confidence": 50, "suggestions": suggs}

_NEXT_STEPS_RESULT = {
    "type":           "next_steps",
    "steps":          ["Visit the Grad Center website", "Schedule a meeting"],
    "extra_guidance": "Request a free appointment with a Graduate Center Coordinator.",
}


# ---------------------------------------------------------------------------
# Helper: patch all three external callsites uniformly
# ---------------------------------------------------------------------------

def _route(
    query: str,
    session_id: str = "test",
    advisor=_NO_MATCH,
    program=None,
    next_steps=None,
) -> RouteDecision:
    with (
        patch("routing.router.find_advisor", return_value=advisor),
        patch("routing.router._tool_detect_program", return_value=program),
        patch("agents.next_steps.get_next_steps", return_value=next_steps),
    ):
        return decide_route(query, session_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

TEST_CASES: list[tuple[str, dict, str, str]] = []  # populated below


def _test(desc: str, query: str, expected_route: str, expected_reason: str,
          advisor=_NO_MATCH, program=None, next_steps=None) -> bool:
    d = _route(query, advisor=advisor, program=program, next_steps=next_steps)
    ok = d.route == expected_route and d.reason == expected_reason
    status = "✓" if ok else "✗"
    print(f"  {status}  {desc}")
    if not ok:
        print(f"       query:    {query!r}")
        print(f"       expected: route={expected_route!r} reason={expected_reason!r}")
        print(f"       got:      route={d.route!r}         reason={d.reason!r}")
    return ok


def run_tests(verbose: bool = True) -> bool:
    if verbose:
        print("=" * 64)
        print("test_router.py — router.decide_route() unit tests")
        print("=" * 64)

    results: list[bool] = []

    # ── Branch 1: welcome (empty query) ──────────────────────────────────────
    results.append(_test(
        "empty string → welcome",
        "", "welcome", "empty_query",
    ))

    # ── Branch 1.5: discovery signals ────────────────────────────────────────
    results.append(_test(
        "interest phrase → discovery",
        "I am interested in becoming a nurse practitioner",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "want to become → discovery",
        "I want to become a physical therapist",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "which program → discovery",
        "which program should I choose for public health",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "career in phrase → discovery",
        "I want a career in education leadership",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "recommend a program → discovery",
        "can you recommend a program for me",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "discovery blocked by deadline signal → deadlines (not discovery)",
        "what are the deadlines for programs I'm interested in",
        "deadlines", "deadline_signal",
    ))
    results.append(_test(
        "discovery blocked by advisor signal → advisor_fuzzy_match (not discovery)",
        "who is the advisor for the program I'm interested in",
        "advisor", "advisor_fuzzy_match",
        advisor=_advisor_match("Dr. X", "x@csulb.edu", "DNP"),
    ))
    results.append(_test(
        "discovery blocked by eligibility signal → eligibility (not discovery)",
        "what are the gpa requirements for programs I'm interested in",
        "eligibility", "eligibility_signal",
    ))
    # Broad doctoral-intent phrases — must reach discovery before doctoral_no_match (Branch 6)
    results.append(_test(
        "doctoral degree in healthcare → discovery (not doctoral_no_match)",
        "I want a clinical doctoral degree in healthcare.",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "looking for a doctoral program in healthcare → discovery",
        "I am looking for a doctoral program in healthcare.",
        "discovery", "discovery_signal",
    ))
    results.append(_test(
        "doctorate in healthcare → discovery (not doctoral_no_match)",
        "I want a doctorate in healthcare.",
        "discovery", "discovery_signal",
    ))
    # Guards: deadline and advisor signals must still block discovery for doctoral queries
    results.append(_test(
        "doctoral deadline query → deadlines (not discovery)",
        "What are the application deadlines for DNP?",
        "deadlines", "deadline_signal",
    ))
    results.append(_test(
        "doctoral advisor query → advisor (not discovery)",
        "Who is the advisor for DNP?",
        "advisor", "advisor_fuzzy_match",
        advisor=_advisor_match("Dr. Arellano", "cleddhy.arellano@csulb.edu", "Nursing (D.N.P.)"),
    ))

    # ── Branch 2: deadlines ───────────────────────────────────────────────────
    results.append(_test(
        "deadline keyword → deadlines",
        "when is the deadline", "deadlines", "deadline_signal",
    ))
    results.append(_test(
        "deadline + program alias → deadlines (advisor not hijacking)",
        "deadlines for dnp", "deadlines", "deadline_signal",
    ))
    results.append(_test(
        "advisor signal blocks deadline route",
        "who is the advisor for deadline programs",
        "advisor", "advisor_fuzzy_match",
        advisor=_advisor_match("Dr. X", "x@csulb.edu", "DNP"),
    ))

    # ── Branch 3: eligibility ─────────────────────────────────────────────────
    results.append(_test(
        "eligibility keyword → eligibility",
        "what are the gpa requirements", "eligibility", "eligibility_signal",
    ))
    results.append(_test(
        "eligibility + program alias → eligibility (not advisor)",
        "eligibility for dnp", "eligibility", "eligibility_signal",
    ))

    # ── Branch 4: application steps ───────────────────────────────────────────
    results.append(_test(
        "process keyword + named program → application",
        "application steps for dnp",
        "application", "application_process",
        program="dnp",
    ))
    results.append(_test(
        "process keyword + process-step signal → application",
        "what are the steps to apply",
        "application", "application_process",
    ))
    results.append(_test(
        "generic apply without step signal or program → guidance (not application)",
        "how do I apply", "guidance", "detect_route_guidance",
    ))

    # ── Branch 5: advisor fuzzy match ─────────────────────────────────────────
    results.append(_test(
        "advisor fuzzy match → advisor (fuzzy_match)",
        "nursing dnp advisor",
        "advisor", "advisor_fuzzy_match",
        advisor=_advisor_match("Dr. Smith", "smith@csulb.edu", "DNP"),
    ))
    results.append(_test(
        "advisor suggestions → advisor (suggestions)",
        "nursing phd help",
        "advisor", "advisor_suggestions",
        advisor=_advisor_suggestions(["DNP Program"]),
    ))
    results.append(_test(
        "advisor match blocked by process query",
        "application steps for nursing",
        "application", "application_process",
        advisor=_advisor_match("Dr. Smith", "smith@csulb.edu", "Nursing"),
        program="nursing",
    ))

    # ── Branch 6: doctoral no-match ───────────────────────────────────────────
    results.append(_test(
        "doctoral token, no match → doctoral_no_match",
        "business phd csulb",
        "advisor", "doctoral_no_match",
    ))
    results.append(_test(
        "edd token, no match → doctoral_no_match",
        "edd program csulb",
        "advisor", "doctoral_no_match",
    ))

    # ── Branch 7: advisor intent, no program ─────────────────────────────────
    results.append(_test(
        "advisor intent keyword, confidence 0 → advisor_intent_no_program",
        "who should I contact",
        "advisor", "advisor_intent_no_program",
    ))
    results.append(_test(
        "contact keyword, confidence 0 → advisor_intent_no_program",
        "how do I reach an advisor",
        "advisor", "advisor_intent_no_program",
    ))

    # ── Branch 8: start-only intent → next_steps ─────────────────────────────
    results.append(_test(
        "confused start intent → next_steps",
        "I am confused and don't know where to begin",
        "next_steps", "start_intent",
        next_steps=_NEXT_STEPS_RESULT,
    ))
    results.append(_test(
        "start token + apply-specific keyword → guidance (not next_steps)",
        "I want to apply and don't know where to start",
        "guidance", "detect_route_guidance",
        next_steps=_NEXT_STEPS_RESULT,
    ))
    results.append(_test(
        "start intent but get_next_steps returns None → falls through to guidance",
        "where do I start",
        "guidance", "detect_route_guidance",
        next_steps=None,
    ))

    # ── Branches 9 + 10: detect_route fallback ────────────────────────────────
    results.append(_test(
        "yes/no starter → answer (detect_route_answer_starter)",
        "is the program accredited",
        "answer", "detect_route_answer_starter",
    ))
    results.append(_test(
        "guidance domain word → guidance (detect_route_guidance)",
        "I was recently accepted what do I do",
        "guidance", "detect_route_guidance",
    ))
    results.append(_test(
        "no domain word, no starter → answer (detect_route_answer_default)",
        "tell me about tuition",
        "answer", "detect_route_answer_default",
    ))

    # ── RouteDecision payload checks ──────────────────────────────────────────
    d_adv = _route(
        "dnp advisor", session_id="s1",
        advisor=_advisor_match("Dr. Lee", "lee@csulb.edu", "DNP", score=96),
    )
    ok_payload = (
        d_adv.route == "advisor"
        and d_adv.advisor_result is not None
        and d_adv.advisor_result["confidence"] == 96
        and d_adv.advisor_score == 96
        and d_adv.session_id == "s1"
    )
    print(f"  {'✓' if ok_payload else '✗'}  advisor RouteDecision carries advisor_result + score")
    results.append(ok_payload)

    d_ns = _route(
        "I am lost and overwhelmed", next_steps=_NEXT_STEPS_RESULT,
    )
    ok_ns = (
        d_ns.route == "next_steps"
        and d_ns.next_steps_result is not None
        and len(d_ns.next_steps_result["steps"]) == 2
    )
    print(f"  {'✓' if ok_ns else '✗'}  next_steps RouteDecision carries next_steps_result")
    results.append(ok_ns)

    d_app = _route(
        "how do I apply for dpt", program="dpt",
    )
    ok_app = d_app.route == "application" and d_app.detected_program == "dpt"
    print(f"  {'✓' if ok_app else '✗'}  application RouteDecision carries detected_program")
    results.append(ok_app)

    d_dl = _route("what is the application deadline")
    ok_dl = d_dl.route == "deadlines" and "deadline" in d_dl.matched_signals
    print(f"  {'✓' if ok_dl else '✗'}  deadlines RouteDecision carries matched_signals")
    results.append(ok_dl)

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(results)
    total  = len(results)
    print(f"\n{'=' * 64}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print(f"\n  ✗ {total - passed} test(s) FAILED — see details above.")
    else:
        print("\n  All router unit tests passed.")
    return passed == total


if __name__ == "__main__":
    ok = run_tests(verbose=True)
    sys.exit(0 if ok else 1)
