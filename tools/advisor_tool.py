"""
tools/advisor_tool.py
Thin wrapper around advisor_retrieval.find_advisor() for the tools layer.

What this module does:
  - Delegates all matching logic to advisor_retrieval.find_advisor() unchanged.
  - Reshapes the result into the standard tool output schema.
  - Attaches a list of known program names for downstream "did you mean?" use.
  - Provides a CLI test function (run_cli_test) for quick smoke-testing.

What this module does NOT do:
  - No fuzzy matching logic here — that all lives in advisor_retrieval.py.
  - No email drafting — that is in email_tool.py.
  - No changes to matching thresholds or stop-word lists.

Output schema:
    {
        "found":          bool,            # True when a single advisor was matched
        "tool":           "advisor_tool",
        "sources":        list[str],       # always [] — no URL source for advisor data
        "error":          str | None,
        # when found=True:
        "match":          dict,            # full advisor record from the dataset
        "confidence":     int,             # partial_ratio score (0–100)
        "suggestions":    list[str],       # [] when matched; up to 3 when ambiguous
        "known_programs": list[str],       # all program names in the loaded dataset
    }
"""

from __future__ import annotations

from retrieval.advisor_retrieval import advisors, find_advisor


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_advisor(query: str) -> dict:
    """
    Look up the CSULB doctoral program advisor whose program best matches query.

    Delegates entirely to advisor_retrieval.find_advisor() — no matching logic
    lives here.  The result is normalised into the standard tool output schema.

    Args:
        query: Free-text query string, e.g. "nursing", "who advises the DNP?",
               "I'm interested in the Ed.D. in P-12 Leadership".

    Returns:
        Standard tool dict:
        {
            "found":          bool,
            "tool":           "advisor_tool",
            "sources":        [],            # advisor data has no URL source
            "error":          None | str,
            "match":          dict | None,   # full advisor record when found=True
            "confidence":     int,           # best partial_ratio score (0–100)
            "suggestions":    list[str],     # program name options when ambiguous
            "known_programs": list[str],     # all program names in the dataset
        }

    Example (match found):
        get_advisor("nursing DNP")
        → {
            "found": True,
            "match": {"program": "...", "advisor_name": "...", "email": "...", ...},
            "confidence": 95,
            "suggestions": [],
            ...
          }

    Example (ambiguous):
        get_advisor("education leadership")
        → {
            "found": False,
            "match": None,
            "confidence": 100,
            "suggestions": ["Ed.D. in P-12 Educational Leadership", "Ed.D. in ..."],
            ...
          }
    """
    known_programs = [a.get("program", "") for a in advisors if a.get("program")]

    if not query or not query.strip():
        return {
            "found":          False,
            "tool":           "advisor_tool",
            "sources":        [],
            "error":          "Query is empty.",
            "match":          None,
            "confidence":     0,
            "suggestions":    [],
            "known_programs": known_programs,
        }

    try:
        result = find_advisor(query)
    except Exception as exc:
        return {
            "found":          False,
            "tool":           "advisor_tool",
            "sources":        [],
            "error":          f"Advisor lookup failed: {exc}",
            "match":          None,
            "confidence":     0,
            "suggestions":    [],
            "known_programs": known_programs,
        }

    match       = result.get("match")
    confidence  = result.get("confidence", 0)
    suggestions = result.get("suggestions", [])

    return {
        "found":          match is not None,
        "tool":           "advisor_tool",
        "sources":        [],
        "error":          None,
        "match":          match,
        "confidence":     confidence,
        "suggestions":    suggestions,
        "known_programs": known_programs,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test get_advisor() against a handful of representative queries.

    Run from the project root:
        python -m tools.advisor_tool
    """
    import textwrap

    TEST_CASES = [
        # (query, expect_match: bool, description)
        ("nursing DNP",                   True,  "Exact abbrev match"),
        ("DPT physical therapy program",    True,  "DPT program via stop-word removal"),
        ("education leadership",          False, "Ambiguous — P-12 vs CC Ed.D."),
        ("p-12 education leadership",     True,  "Unique-token disambiguation"),
        ("",                              False, "Empty query"),
        ("xyznonexistentprogram123",      False, "No match, no suggestions"),
    ]

    print("=" * 60)
    print("advisor_tool — CLI smoke test")
    print("=" * 60)
    print(f"  Loaded {len(advisors)} advisor records\n")

    pass_count = fail_count = 0

    for query, expect_match, description in TEST_CASES:
        result = get_advisor(query)

        got_match = result["found"]
        status    = "✓" if got_match == expect_match else "✗"

        if got_match == expect_match:
            pass_count += 1
        else:
            fail_count += 1

        label = f"[{'MATCH' if got_match else 'NO MATCH'}]"
        print(f"  {status}  {label}  conf={result['confidence']}  — {description}")
        print(f"       query: {query!r}")

        if result["match"]:
            prog = result["match"].get("program", "?")
            name = result["match"].get("advisor_name", "?")
            print(f"       → {prog}  /  {name}")
        elif result["suggestions"]:
            print(f"       → suggestions: {result['suggestions']}")
        elif result["error"]:
            print(f"       → error: {result['error']}")
        print()

    total = pass_count + fail_count
    print(f"{'='*60}")
    print(f"Results: {pass_count}/{total} passed")


if __name__ == "__main__":
    run_cli_test()
