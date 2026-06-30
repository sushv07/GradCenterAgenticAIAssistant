"""
evals/error_classification_retrieval.py
Phase 8A — deterministic error-category classification for retrieval eval
case results.

Mirrors evals/error_classification.py and evals/error_classification_llm.py's
role and style. Every case is assigned exactly one error_category and a
short, deterministic error_reason, using only facts run_retrieval_evals.py
already established (which expected sources were found/missing, whether a
forbidden source appeared, whether duplicates were detected, the top
score). No LLM, no semantic judgment.

── Taxonomy ──────────────────────────────────────────────────────────────

none
    A clean pass.

no_retrieval
    expect_empty is False (or unset) and expected_min_chunks > 0, but the
    actual result set was empty — retrieval found nothing when it should
    have found something.

empty_context
    expect_empty is True, but the actual result set was NOT empty —
    retrieval found something for a query that should be correctly
    rejected as out-of-scope (the inverse of no_retrieval).

unexpected_source
    A forbidden_sources entry was found among the actual results.

missing_expected_source
    expected_sources was non-empty, but none of them were found anywhere
    in the actual top-k results (topk_match is False).

ranking_error
    An expected source WAS found somewhere in the top-k results, but not
    at position 1 (topk_match True, top1_match False) — the right content
    exists in the index and was retrieved, just ranked below where a
    top-1 case expected it.

partial_match
    More than one expected_sources entry was specified, and at least one
    was found but at least one was not — neither a clean pass nor a
    total miss.

duplicate_chunks
    The same chunk_id appeared more than once in one result set, and the
    case did not set allow_duplicate_chunks=true.

low_score
    Results were non-empty and every expectation was otherwise satisfied,
    but the top score fell below the case's own historical/verified
    baseline by a wide margin — reserved for future use once baselines
    are tracked across runs (see ARCHITECTURE_ANALYSIS.md's Phase 8A
    "Future Roadmap"); not triggered by any case in the current dataset.

unexpected_failure
    Catch-all: status is FAIL but none of the more specific rules above
    explain why.
"""
from __future__ import annotations


def classify_retrieval(case: dict, result: dict) -> tuple[str, str]:
    """
    Return (error_category, error_reason) for one retrieval eval case
    result. Checked in priority order: empty/non-empty mismatches first
    (most fundamental), then forbidden sources, then expected-source
    presence/ranking, then duplicates.
    """
    actual = result["actual"]

    if case.get("expect_empty") and not actual["is_empty"]:
        return (
            "empty_context",
            f"expected no results (out-of-scope query) but got {actual['num_results']} result(s)",
        )

    if not case.get("expect_empty") and case.get("expected_min_chunks", 0) > 0 and actual["is_empty"]:
        return (
            "no_retrieval",
            f"expected at least {case['expected_min_chunks']} result(s) but got none",
        )

    if result.get("forbidden_found"):
        return (
            "unexpected_source",
            f"forbidden source(s) present in results: {result['forbidden_found']}",
        )

    expected_sources = case.get("expected_sources", [])
    if expected_sources:
        found_flags = [s["found"] for s in result.get("expected_source_results", [])]
        n_found = sum(found_flags)

        if n_found == 0:
            return (
                "missing_expected_source",
                f"none of the {len(expected_sources)} expected source(s) appeared in top-{case.get('k', 3)} results",
            )

        if n_found < len(expected_sources):
            return (
                "partial_match",
                f"{n_found}/{len(expected_sources)} expected source(s) found",
            )

        if not result.get("top1_match") and result.get("topk_match"):
            return (
                "ranking_error",
                "expected source present in results but not ranked first",
            )

    if actual["has_duplicates"] and not case.get("allow_duplicate_chunks", False):
        return (
            "duplicate_chunks",
            "the same chunk_id appeared more than once in this result set",
        )

    if result["status"] == "FAIL":
        return "unexpected_failure", "case failed but no specific rule matched"

    return "none", "retrieval matched all case expectations"


def build_error_summary(results: list[dict]) -> dict:
    """Count occurrences of each error_category across a list of case results."""
    summary: dict[str, int] = {}
    for r in results:
        cat = r.get("error_category", "unknown")
        summary[cat] = summary.get(cat, 0) + 1
    return summary


def format_error_summary_console(summary: dict, title: str = "Retrieval Errors") -> str:
    lines = [title]
    for cat, count in sorted(summary.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {cat}: {count}")
    return "\n".join(lines)
