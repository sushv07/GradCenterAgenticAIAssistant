"""
test_golden_routes.py
Data-driven golden route test suite.

Reads evals/golden_routes.json and asserts that router.decide_route()
returns the expected route and reason for each case.

All three external callsites are mocked — no Chroma, no RapidFuzz
scoring against real data, no FAQ retrieval:
  router.find_advisor           — controlled via mock_overrides.advisor
  router._tool_detect_program   — controlled via mock_overrides.program
  next_steps.get_next_steps     — controlled via mock_overrides.next_steps

Run from the project root:
    python test_golden_routes.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from router import decide_route, RouteDecision

# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------

_NO_MATCH: dict = {"match": None, "confidence": 0, "suggestions": []}
_MATCH: dict = {
    "match": {
        "advisor_name": "Dr. Test",
        "email":        "test@csulb.edu",
        "program":      "Test Program",
        "source":       "https://www.csulb.edu/graduate-center",
    },
    "confidence": 95,
    "suggestions": [],
}
_SUGGESTIONS: dict = {
    "match":        None,
    "confidence":   50,
    "suggestions":  ["Some Program"],
}
_NS_FOUND: dict = {
    "type":           "next_steps",
    "steps":          ["Visit the Grad Center website", "Schedule an appointment"],
    "extra_guidance": None,
}

_ADVISOR_MOCKS: dict[str, dict] = {
    "no_match":   _NO_MATCH,
    "match":      _MATCH,
    "suggestions": _SUGGESTIONS,
}

_NS_MOCKS: dict[str, dict | None] = {
    "found": _NS_FOUND,
    "none":  None,
}


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

def _run_case(case: dict) -> tuple[bool, str]:
    """Run a single golden-route case. Returns (passed, detail_string)."""
    overrides = case.get("mock_overrides", {})
    adv_key  = overrides.get("advisor", "no_match")
    prog_val = overrides.get("program")       # None or a string
    ns_key   = overrides.get("next_steps", "none")

    advisor_rv   = _ADVISOR_MOCKS.get(adv_key, _NO_MATCH)
    next_steps_rv = _NS_MOCKS.get(ns_key)

    # run() strips the query before calling decide_route(); mirror that here.
    query = (case.get("query") or "").strip()

    with (
        patch("router.find_advisor",        return_value=advisor_rv),
        patch("router._tool_detect_program", return_value=prog_val),
        patch("next_steps.get_next_steps",   return_value=next_steps_rv),
    ):
        decision: RouteDecision = decide_route(query, session_id="golden_route_test")

    exp = case.get("expected", {})
    exp_route  = exp.get("route")
    exp_reason = exp.get("route_reason")

    ok = decision.route == exp_route and decision.reason == exp_reason
    if ok:
        detail = ""
    else:
        detail = (
            f"\n    query:    {query!r}"
            f"\n    expected: route={exp_route!r}  reason={exp_reason!r}"
            f"\n    got:      route={decision.route!r}  reason={decision.reason!r}"
        )
    return ok, detail


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_golden_routes(verbose: bool = True) -> bool:
    dataset_path = Path(__file__).parent / "evals" / "golden_routes.json"
    with dataset_path.open() as fh:
        dataset = json.load(fh)

    cases = dataset["cases"]

    if verbose:
        print("=" * 64)
        print(f"test_golden_routes.py — {len(cases)} golden route assertions")
        print("=" * 64)

    passed_ids:  list[str] = []
    failed_ids:  list[str] = []
    skipped_ids: list[str] = []

    for case in cases:
        cid   = case["id"]
        notes = case.get("notes", "")

        if case.get("known_failure"):
            skipped_ids.append(cid)
            if verbose:
                print(f"  -  {cid}  [known_failure — skipped]")
            continue

        ok, detail = _run_case(case)

        if ok:
            passed_ids.append(cid)
            if verbose:
                print(f"  ✓  {cid}")
        else:
            failed_ids.append(cid)
            print(f"  ✗  {cid}{detail}")
            if notes:
                print(f"    notes:    {notes}")

    print(f"\n{'=' * 64}")
    print(f"Results: {len(passed_ids)}/{len(cases)} passed"
          + (f"  ({len(skipped_ids)} skipped)" if skipped_ids else ""))

    if failed_ids:
        print(f"\n  ✗ {len(failed_ids)} case(s) FAILED: {', '.join(failed_ids)}")
    else:
        print("\n  All golden route cases passed.")

    return len(failed_ids) == 0


if __name__ == "__main__":
    ok = run_golden_routes(verbose=True)
    sys.exit(0 if ok else 1)
