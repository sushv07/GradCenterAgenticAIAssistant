"""
test_deadline_card.py
Tests for deadline_card parsing and structured deadline response.

Two layers of tests:
  1. Unit tests — _parse_chunk_to_card() directly, no network.
     Uses real text samples matching the format produced by
     rag/ingestion._extract_program_entry().
  2. Integration tests — get_deadlines() end-to-end against the live
     vector store.  Requires a built ChromaDB at ./chroma_db/.

Run from the project root:
    python test_deadline_card.py
"""

from __future__ import annotations

from tools.deadlines_tool import _parse_chunk_to_card, get_deadlines


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — real-format text blocks from the ingestion specialist extractor
# ─────────────────────────────────────────────────────────────────────────────

_DNP_TEXT = (
    "Nursing (D.N.P.) — Application Deadlines\n"
    "Email: cleddhy.arellano@csulb.edu | Phone: 562-985-2335\n"
    "Application:    Spring: Not Accepting | Fall: January 15\n"
    "Accept/Decline: Spring: Not Applicable | Fall: April 20"
)

_DPT_TEXT = (
    "Physical Therapy (DPT) — Application Deadlines\n"
    "Email: CHHS-PT@csulb.edu\n"
    "Application:    Spring: Not Accepting | Fall: January 15\n"
    "Accept/Decline: Spring: Not Applicable | Fall: April 30"
)

_PH_TEXT = (
    "Public Health (DR.P.H.) — Application Deadlines\n"
    "Email: Lucy.Huckabay@csulb.edu | Phone: 562-985-4057\n"
    "Application:    Spring: Not Accepting | Fall: February 15\n"
    "Accept/Decline: Spring: Not Applicable | Fall: March 01"
)

_ENG_TEXT = (
    "Engineering & Computational Mathematics (Ph.D.) — Application Deadlines\n"
    "Email: kerop.janoyan@csulb.edu | Phone: 562-985-8032\n"
    "Application:    Spring: October 01 | Fall: April 01\n"
    "Accept/Decline: Spring: December 13 | Fall: July 15"
)

_INTRO_TEXT = (
    "Programs, Advisors, and Deadlines (Doctoral) To view detailed information "
    "about a graduate program, please visit the University Catalog."
)

_ADVISOR_TEXT = (
    "Educational Leadership - P-12 Specialization (Ed.D.) — Application Deadlines\n"
    "Advisor: Kimberly Word | Email: eddinfo@csulb.edu | Phone: 562-985-4998\n"
    "Application:    Spring: Not Accepting | Fall: February 15\n"
    "Accept/Decline: Spring: Not Applicable | Fall: April 20"
)


def _make_chunk(text: str, score: float = 0.55, url: str = "") -> dict:
    return {
        "text":  text,
        "score": score,
        "url":   url or "https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral",
        "title": text.split("\n")[0],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — _parse_chunk_to_card()
# ─────────────────────────────────────────────────────────────────────────────

UNIT_CASES: list[tuple[str, dict | None, str]] = [
    # (fixture_text, expected_partial_card_or_None, description)
    (
        _DNP_TEXT,
        {
            "program":   "Nursing (D.N.P.)",
            "application": {"spring": "Not Accepting", "fall": "January 15"},
            "accept_decline": {"spring": "Not Applicable", "fall": "April 20"},
            "advisor_contact": {"email": "cleddhy.arellano@csulb.edu", "phone": "562-985-2335"},
        },
        "DNP chunk → correct program, deadlines, contact",
    ),
    (
        _DPT_TEXT,
        {
            "program":   "Physical Therapy (DPT)",
            "application": {"spring": "Not Accepting", "fall": "January 15"},
            "accept_decline": {"fall": "April 30"},
            "advisor_contact": {"email": "CHHS-PT@csulb.edu", "phone": ""},
        },
        "DPT chunk (no phone) → email parsed, phone empty",
    ),
    (
        _PH_TEXT,
        {
            "program":   "Public Health (DR.P.H.)",
            "application": {"fall": "February 15"},
            "accept_decline": {"fall": "March 01"},
            "advisor_contact": {"email": "Lucy.Huckabay@csulb.edu"},
        },
        "Public Health chunk → correct fall deadlines",
    ),
    (
        _ENG_TEXT,
        {
            "program":   "Engineering & Computational Mathematics (Ph.D.)",
            "application": {"spring": "October 01", "fall": "April 01"},
            "accept_decline": {"spring": "December 13", "fall": "July 15"},
        },
        "Engineering chunk → open spring/fall deadlines",
    ),
    (
        _ADVISOR_TEXT,
        {
            "program":   "Educational Leadership - P-12 Specialization (Ed.D.)",
            "advisor_contact": {"email": "eddinfo@csulb.edu", "phone": "562-985-4998", "name": "Kimberly Word"},
        },
        "Chunk with Advisor: field → advisor_name extracted",
    ),
    (
        _INTRO_TEXT,
        None,
        "Intro chunk (no '— Application Deadlines' marker) → None",
    ),
    (
        "",
        None,
        "Empty string → None",
    ),
]


def run_unit_tests(verbose: bool = True) -> int:
    """Run unit tests for _parse_chunk_to_card(). Returns failure count."""
    failures = 0
    if verbose:
        print("\n" + "=" * 64)
        print("Unit tests — _parse_chunk_to_card()")
        print("=" * 64)

    for text, expected, description in UNIT_CASES:
        chunk = _make_chunk(text)
        card  = _parse_chunk_to_card(chunk)

        if expected is None:
            ok = card is None
        else:
            ok = card is not None
            if ok:
                # Verify expected fields are all present and match
                for key, exp_val in expected.items():
                    actual_val = card.get(key)
                    if isinstance(exp_val, dict):
                        for sub_k, sub_v in exp_val.items():
                            if actual_val.get(sub_k) != sub_v:
                                ok = False
                                if verbose:
                                    print(
                                        f"     ✗ [{key}][{sub_k}]: "
                                        f"expected {sub_v!r}, got {actual_val.get(sub_k)!r}"
                                    )
                    else:
                        if actual_val != exp_val:
                            ok = False
                            if verbose:
                                print(f"     ✗ [{key}]: expected {exp_val!r}, got {actual_val!r}")

        symbol = "✓" if ok else "✗"
        if verbose:
            print(f"\n  {symbol}  {description}")
            if not ok and card is not None:
                print(f"     card={card}")

        if not ok:
            failures += 1

    if verbose:
        total = len(UNIT_CASES)
        passed = total - failures
        print(f"\n  Unit: {passed}/{total} passed")

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests — get_deadlines()
# ─────────────────────────────────────────────────────────────────────────────

INTEGRATION_CASES: list[tuple[str, str | None, bool, str]] = [
    # (query, expected_program_substring, expect_clarification, description)
    (
        "deadlines for dnp",
        "Nursing",
        False,
        "DNP query → deadline_card for Nursing program",
    ),
    (
        "nursing dnp application deadline",
        "Nursing",
        False,
        "Explicit 'nursing dnp' → deadline_card for Nursing",
    ),
    (
        "physical therapy deadline",
        "Physical Therapy",
        False,
        "Physical Therapy query → deadline_card for DPT",
    ),
    (
        "when is the deadline for physical therapy dpt",
        "Physical Therapy",
        False,
        "Full DPT query → deadline_card for Physical Therapy",
    ),
    (
        "public health doctoral deadline",
        "Public Health",
        False,
        "Public Health query → deadline_card for DR.P.H.",
    ),
    (
        "public health fall application deadline",
        "Public Health",
        False,
        "Public Health fall query → deadline_card for DR.P.H.",
    ),
    (
        "what are the doctoral deadlines",
        None,
        True,
        "Vague query → needs_clarification=True, no dominant card",
    ),
    (
        "show me all program deadlines",
        None,
        True,
        "Vague 'all programs' query → needs_clarification=True",
    ),
]


def run_integration_tests(verbose: bool = True) -> int:
    """
    Run integration tests for get_deadlines().
    Requires a built ChromaDB vector store at ./chroma_db/.
    Returns failure count.
    """
    failures = 0
    if verbose:
        print("\n" + "=" * 64)
        print("Integration tests — get_deadlines()")
        print("=" * 64)

    for query, expected_program, expect_clarify, description in INTEGRATION_CASES:
        result  = get_deadlines(query)
        card    = result.get("deadline_card")
        clarify = result.get("needs_clarification", False)

        # Check clarification flag
        clarify_ok = (clarify == expect_clarify)

        # Check program match (only when a card is expected)
        program_ok = True
        if expected_program is not None:
            if card is None:
                program_ok = False
            else:
                program_ok = expected_program.lower() in card["program"].lower()

        ok = clarify_ok and program_ok

        if not ok:
            failures += 1

        if verbose:
            sym = "✓" if ok else "✗"
            print(f"\n  {sym}  {description}")
            print(f"     query:    {query!r}")
            if card:
                print(f"     card:     {card['program']}  (score={card['score']:.4f})")
            else:
                print(f"     card:     None")
            print(f"     clarify:  {clarify}  (expected={expect_clarify})  {'✓' if clarify_ok else '✗'}")
            if expected_program is not None:
                print(f"     program:  {card['program'] if card else '—'}  "
                      f"(expected ⊇ {expected_program!r})  {'✓' if program_ok else '✗'}")
            if not ok and result.get("error"):
                print(f"     error:    {result['error']}")

    if verbose:
        total  = len(INTEGRATION_CASES)
        passed = total - failures
        print(f"\n  Integration: {passed}/{total} passed")

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all(verbose: bool = True) -> bool:
    """Run all tests. Returns True if all passed."""
    unit_failures  = run_unit_tests(verbose=verbose)
    integ_failures = run_integration_tests(verbose=verbose)
    total_failures = unit_failures + integ_failures

    if verbose:
        print("\n" + "=" * 64)
        u_total = len(UNIT_CASES)
        i_total = len(INTEGRATION_CASES)
        print(
            f"Results: {u_total - unit_failures}/{u_total} unit  ·  "
            f"{i_total - integ_failures}/{i_total} integration  ·  "
            f"{'ALL PASSED 🎉' if total_failures == 0 else f'{total_failures} FAILED ✗'}"
        )

    return total_failures == 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    ok = run_all(verbose=True)
    sys.exit(0 if ok else 1)
