"""
evals/error_classification_ingestion.py
Phase 9A — deterministic error-category classification for ingestion eval
case results.

Mirrors error_classification_retrieval.py and error_classification_advisor.py's
style. One error_category per case, assigned from facts the runner already
established. No LLM, no semantic judgment.

── Taxonomy ──────────────────────────────────────────────────────────────

none
    A clean pass.

page_missing
    A page_type_chunk_count case found zero chunks for the expected
    page_type — that page type is entirely absent from the knowledge base.

chunk_missing
    A page_type_chunk_count, program_chunk_count, or url_chunk_count case
    found fewer chunks than expected_min — the page or program was partially
    or barely ingested.

chunk_too_many
    A page_type_chunk_count or url_chunk_count case found more chunks than
    expected_max — unexpected over-ingestion (e.g. a crawler loop).

total_volume_out_of_range
    The total_chunk_count case found the overall chunk count outside the
    [expected_min, expected_max] window.

program_missing
    A program_chunk_count case found zero chunks for the named program —
    that program is entirely absent from the knowledge base.

program_under_ingested
    A program_chunk_count case found some chunks but fewer than expected_min
    for the named program.

distinct_program_count_low
    The distinct_program_count case found fewer distinct named programs than
    expected — some programs were entirely missed.

metadata_missing
    A metadata_completeness case found chunks with an empty or absent value
    for the required field.

empty_chunk
    The no_empty_chunks case found chunks with empty page_content.

chunk_size_violation
    The max_chunk_size case found chunks exceeding the expected_max_chars
    limit — the chunker's size bound was not respected.

duplicate_mismatch
    A chunk_id_count case found the known-duplicate chunk_id a different
    number of times than expected_count — the store structure changed
    unexpectedly (could indicate a fix, a regression, or a re-ingestion
    that added or removed entries).

unexpected_failure
    Catch-all: status is FAIL but none of the specific rules matched.
"""
from __future__ import annotations


def classify_ingestion(case: dict, result: dict) -> tuple[str, str]:
    """
    Return (error_category, error_reason) for one ingestion eval case result.
    Checked in priority order per check_type.
    """
    if result["status"] == "PASS":
        return "none", "all case expectations met"

    check_type = case["check_type"]
    actual = result.get("actual_value")

    # ── total_chunk_count ─────────────────────────────────────────────────
    if check_type == "total_chunk_count":
        expected_min = case.get("expected_min", 0)
        expected_max = case.get("expected_max", float("inf"))
        if actual < expected_min:
            return (
                "total_volume_out_of_range",
                f"total chunks {actual} is below expected minimum {expected_min}",
            )
        if actual > expected_max:
            return (
                "total_volume_out_of_range",
                f"total chunks {actual} exceeds expected maximum {expected_max}",
            )

    # ── page_type_chunk_count ─────────────────────────────────────────────
    if check_type == "page_type_chunk_count":
        page_type = case.get("page_type", "")
        expected_min = case.get("expected_min", 1)
        expected_max = case.get("expected_max", float("inf"))
        if actual == 0:
            return (
                "page_missing",
                f"page_type={page_type!r} has 0 chunks — page entirely absent from store",
            )
        if actual < expected_min:
            return (
                "chunk_missing",
                f"page_type={page_type!r}: {actual} chunks < expected_min {expected_min}",
            )
        if actual > expected_max:
            return (
                "chunk_too_many",
                f"page_type={page_type!r}: {actual} chunks > expected_max {expected_max}",
            )

    # ── program_chunk_count ───────────────────────────────────────────────
    if check_type == "program_chunk_count":
        program_name = case.get("program_name", "")
        expected_min = case.get("expected_min", 1)
        if actual == 0:
            return (
                "program_missing",
                f"program_name={program_name!r} has 0 chunks — program entirely absent from store",
            )
        if actual < expected_min:
            return (
                "program_under_ingested",
                f"program_name={program_name!r}: {actual} chunks < expected_min {expected_min}",
            )

    # ── distinct_program_count ────────────────────────────────────────────
    if check_type == "distinct_program_count":
        expected_min = case.get("expected_min", 1)
        return (
            "distinct_program_count_low",
            f"only {actual} distinct program names found, expected at least {expected_min}",
        )

    # ── metadata_completeness ─────────────────────────────────────────────
    if check_type == "metadata_completeness":
        field = case.get("field", "")
        missing_count = result.get("missing_count", 0)
        return (
            "metadata_missing",
            f"field={field!r}: {missing_count} chunk(s) have empty or absent value",
        )

    # ── no_empty_chunks ───────────────────────────────────────────────────
    if check_type == "no_empty_chunks":
        empty_count = result.get("empty_count", 0)
        return (
            "empty_chunk",
            f"{empty_count} chunk(s) have empty page_content",
        )

    # ── max_chunk_size ────────────────────────────────────────────────────
    if check_type == "max_chunk_size":
        expected_max = case.get("expected_max_chars", 500)
        violation_count = result.get("violation_count", 0)
        return (
            "chunk_size_violation",
            f"{violation_count} chunk(s) exceed max_chars={expected_max}",
        )

    # ── url_chunk_count ───────────────────────────────────────────────────
    if check_type == "url_chunk_count":
        url = case.get("url", "")
        expected_min = case.get("expected_min", 1)
        expected_max = case.get("expected_max", float("inf"))
        if actual == 0:
            return (
                "page_missing",
                f"url={url!r} has 0 chunks — page entirely absent from store",
            )
        if actual < expected_min:
            return (
                "chunk_missing",
                f"url={url!r}: {actual} chunks < expected_min {expected_min}",
            )
        if actual > expected_max:
            return (
                "chunk_too_many",
                f"url={url!r}: {actual} chunks > expected_max {expected_max}",
            )

    # ── chunk_id_count ────────────────────────────────────────────────────
    if check_type == "chunk_id_count":
        chunk_id = case.get("chunk_id", "")
        expected_count = case.get("expected_count")
        return (
            "duplicate_mismatch",
            f"chunk_id={chunk_id!r}: found {actual} occurrences, expected {expected_count}",
        )

    return "unexpected_failure", "case failed but no specific rule matched"


def build_error_summary(results: list[dict]) -> dict:
    """Count occurrences of each error_category across a list of case results."""
    summary: dict[str, int] = {}
    for r in results:
        cat = r.get("error_category", "unknown")
        summary[cat] = summary.get(cat, 0) + 1
    return summary


def format_error_summary_console(summary: dict, title: str = "Ingestion Errors") -> str:
    lines = [title]
    for cat, count in sorted(summary.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {cat}: {count}")
    return "\n".join(lines)
