"""
test_routing_fix.py
Intent-priority routing regression tests for orchestrator.py.

Verifies that:
  1. Topic queries containing a program alias (e.g. "dnp") route to the
     correct topic tool instead of the advisor card.
  2. Advisor-intent queries still route to the advisor card.
  3. The advisor card response now includes an auto-generated email_draft
     payload (subject, body, outlook_url) when a specific advisor is matched.

Run from the project root:
    python test_routing_fix.py
"""

from __future__ import annotations

from orchestrator import run


# ---------------------------------------------------------------------------
# Test table
# ---------------------------------------------------------------------------

TEST_CASES: list[tuple[str, str, bool, str]] = [
    # (query,  expected_route,  check_email_draft,  description)
    (
        "deadlines for dnp",
        "deadlines",
        False,
        "deadline keyword + program alias → deadline route, not advisor",
    ),
    (
        "application steps for dnp",
        "application",
        False,
        "application steps keyword → application route, not advisor",
    ),
    (
        "eligibility for dnp",
        "eligibility",
        False,
        "eligibility keyword + program alias → eligibility route, not advisor",
    ),
    (
        "advisor for dnp",
        "advisor",
        True,
        "explicit advisor keyword → advisor route + email_draft payload",
    ),
    (
        "who do I contact for nursing",
        "advisor",
        True,
        "'who' + 'contact' → advisor route + email_draft payload",
    ),
    # ── Existing behavior must not regress ──────────────────────────────────
    (
        "nursing DNP",
        "advisor",
        True,
        "bare program query → advisor route (existing behavior preserved)",
    ),
    (
        "what are the GPA requirements",
        "eligibility",
        False,
        "gpa/requirements keywords → eligibility route (no alias)",
    ),
    (
        "when is the fall application deadline",
        "deadlines",
        False,
        "deadline + application → deadline wins (deadline signal is explicit)",
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(verbose: bool = True) -> bool:
    """Run all routing tests.  Returns True if all passed."""
    pass_count = fail_count = 0

    if verbose:
        print("=" * 64)
        print("test_routing_fix.py — intent routing regression tests")
        print("=" * 64)

    for query, expected_route, check_draft, description in TEST_CASES:
        response      = run(query)
        actual_route  = response.get("route")
        route_ok      = actual_route == expected_route

        # When check_draft is True, verify the email_draft payload is present
        draft_ok = True
        if check_draft and route_ok:
            ed        = response.get("email_draft", {})
            draft_ok  = bool(
                ed.get("found")
                and ed.get("subject")
                and ed.get("body")
                and ed.get("outlook_url")
            )

        passed = route_ok and draft_ok

        if passed:
            pass_count += 1
        else:
            fail_count += 1

        if verbose:
            status = "✓" if passed else "✗"
            print(f"\n  {status}  {description}")
            print(f"     query:    {query!r}")
            print(f"     expected: {expected_route}   got: {actual_route}  {'✓' if route_ok else '✗'}")
            if check_draft:
                ed = response.get("email_draft", {})
                print(
                    f"     draft:    found={ed.get('found')}  "
                    f"subject={bool(ed.get('subject'))}  "
                    f"body={bool(ed.get('body'))}  "
                    f"url={bool(ed.get('outlook_url'))}  "
                    f"{'✓' if draft_ok else '✗'}"
                )

    total = pass_count + fail_count
    if verbose:
        print(f"\n{'=' * 64}")
        print(f"Results: {pass_count}/{total} passed")
        if fail_count:
            print(f"\n  ✗ {fail_count} test(s) FAILED — see details above.")
        else:
            print("\n  All routing tests passed. 🎉")

    return fail_count == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    ok = run_tests(verbose=True)
    sys.exit(0 if ok else 1)
