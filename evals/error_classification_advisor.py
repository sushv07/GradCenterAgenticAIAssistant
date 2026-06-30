"""
evals/error_classification_advisor.py
Phase 8D — deterministic error-category classification for advisor-answer
eval case results.

Mirrors error_classification_retrieval.py and error_classification_llm.py's
role and style. Every case is assigned exactly one error_category and a
short, deterministic error_reason, using only facts run_advisor_evals.py
already established. No LLM, no semantic judgment.

── Taxonomy ──────────────────────────────────────────────────────────────

none
    A clean pass.

incorrect_route
    The actual route did not match the expected_route (or matched a route
    the case explicitly required NOT to be the actual route via
    expected_route_is_not). The highest-priority failure category: if
    routing is wrong, all downstream advisor data is meaningless.

advisor_not_found
    A match was expected (expected_match=true) but find_advisor() returned
    no match for this query — the program either lacks an alias that
    matches this input, or the fuzzy score fell below FUZZY_THRESHOLD (90).

spurious_match
    No match was expected (expected_match=false) but the system returned a
    match — a false positive from the fuzzy matcher.

wrong_program
    A match was found but the matched program name differs from
    expected_program. The advisor lookup reached the right path but landed
    on the wrong program record.

wrong_advisor
    The program matched correctly but advisor_name differs from
    expected_advisor_name. Could indicate a data quality issue in
    advisors_extracted.json.

wrong_email
    The program and advisor matched correctly but email differs from
    expected_email. The most directly harmful field error — users might
    email the wrong person.

missing_information
    A match was expected and found, the program is correct, but either
    advisor_name or email is None/empty when the case does NOT have
    has_null_advisor=true (the evaluator expected real contact data).

suggestion_failure
    No match was expected and no spurious match fired, but expected
    suggestions_include listed programs that did not appear in actual
    suggestions — the ambiguity-resolution path surfaced the wrong set.

null_advisor_incorrect
    A has_null_advisor=true case matched the right program but the
    advisor_name or email was unexpectedly non-None — the system started
    returning contact data for a record that previously had none (a data
    update, potentially good but needs human review).

unexpected_failure
    Catch-all: status is FAIL but none of the more specific rules above
    explain why.
"""
from __future__ import annotations


def classify_advisor(case: dict, result: dict) -> tuple[str, str]:
    """
    Return (error_category, error_reason) for one advisor-answer eval case
    result. Checked in priority order: routing first, then match presence,
    then field-level accuracy.
    """
    if result["status"] == "PASS":
        return "none", "all case expectations met"

    # ── Routing ────────────────────────────────────────────────────────────
    if not result.get("route_correct") and result.get("expected_route_checked"):
        expected = result.get("expected_route_value", "")
        actual   = result.get("actual_route", "")
        return (
            "incorrect_route",
            f"expected route={expected!r} but got route={actual!r}",
        )

    # ── Match presence ─────────────────────────────────────────────────────
    if case.get("expected_match") and not result.get("match_present"):
        return (
            "advisor_not_found",
            "expected a match but find_advisor() returned no match "
            f"(confidence={result.get('actual_confidence', 0):.0f})",
        )

    if not case.get("expected_match") and result.get("match_present"):
        matched_program = result.get("actual_program", "")
        return (
            "spurious_match",
            f"expected no match but got match on program={matched_program!r}",
        )

    # ── Null advisor handling ──────────────────────────────────────────────
    if case.get("has_null_advisor") and not result.get("null_advisor_correct"):
        return (
            "null_advisor_incorrect",
            "has_null_advisor=true but system returned non-null advisor contact data",
        )

    # ── Field-level accuracy ───────────────────────────────────────────────
    if case.get("expected_program") and not result.get("program_correct"):
        return (
            "wrong_program",
            f"expected program={case['expected_program']!r} "
            f"but got {result.get('actual_program', '')!r}",
        )

    if case.get("expected_advisor_name") and not result.get("advisor_name_correct"):
        return (
            "wrong_advisor",
            f"expected advisor_name={case['expected_advisor_name']!r} "
            f"but got {result.get('actual_advisor_name', '')!r}",
        )

    if case.get("expected_email") and not result.get("email_correct"):
        return (
            "wrong_email",
            f"expected email={case['expected_email']!r} "
            f"but got {result.get('actual_email', '')!r}",
        )

    if result.get("match_present") and not case.get("has_null_advisor"):
        if not result.get("advisor_name") and case.get("expected_advisor_name"):
            return (
                "missing_information",
                "match found but advisor_name is empty when contact data was expected",
            )
        if not result.get("email") and case.get("expected_email"):
            return (
                "missing_information",
                "match found but email is empty when contact data was expected",
            )

    # ── Suggestions ────────────────────────────────────────────────────────
    if case.get("expected_suggestions_include") and not result.get("suggestions_fully_covered"):
        missing = result.get("missing_suggestions", [])
        return (
            "suggestion_failure",
            f"expected suggestions not surfaced: {missing}",
        )

    return "unexpected_failure", "case failed but no specific rule matched"


def build_error_summary(results: list[dict]) -> dict:
    """Count occurrences of each error_category across a list of case results."""
    summary: dict[str, int] = {}
    for r in results:
        cat = r.get("error_category", "unknown")
        summary[cat] = summary.get(cat, 0) + 1
    return summary


def format_error_summary_console(summary: dict, title: str = "Advisor Answer Errors") -> str:
    lines = [title]
    for cat, count in sorted(summary.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {cat}: {count}")
    return "\n".join(lines)
