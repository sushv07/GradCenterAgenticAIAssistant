"""
evals/metrics_advisor.py
Phase 8D — deterministic metrics over an advisor-answer evaluation run.

Pure post-processing over per-case results already produced by
run_advisor_evals.py — mirrors metrics_retrieval.py and metrics_llm.py's
role for their respective runners. No LLM, no semantic similarity, no
embedding comparison — every metric here is a count/ratio over facts the
runner already established (did the route match, was the advisor name
correct, were expected suggestions returned).
"""
from __future__ import annotations


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def compute_advisor_metrics(cases: list[dict]) -> dict:
    """
    Compute the Phase 8D metric set from a list of run_advisor_evals.py
    case results.

    Every metric is a deterministic rate computed from explicit pass/fail
    facts already established by the runner — route matches, advisor-name
    matches, email matches, suggestion coverage, etc.
    """
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "PASS")
    failed = sum(1 for c in cases if c["status"] == "FAIL")

    # ── Route correctness ──────────────────────────────────────────────────
    # Cases that assert a specific expected_route.
    route_cases = [c for c in cases if c.get("expected_route_checked")]
    route_correct = sum(1 for c in route_cases if c.get("route_correct"))

    # ── Match presence ─────────────────────────────────────────────────────
    # Cases that require a match to be present.
    should_match_cases = [c for c in cases if c.get("expected_match")]
    match_found = sum(1 for c in should_match_cases if c.get("match_present"))

    # Cases that require NO match (no-match / ambiguous / empty query).
    should_not_match_cases = [c for c in cases if not c.get("expected_match")]
    no_spurious_match = sum(1 for c in should_not_match_cases if not c.get("match_present"))

    # ── Field-level accuracy (only for cases where a match was expected
    #    AND has_null_advisor is False — null-advisor cases cannot
    #    meaningfully assert on name or email) ─────────────────────────────
    named_match_cases = [
        c for c in should_match_cases if not c.get("has_null_advisor")
    ]

    program_cases = [c for c in named_match_cases if c.get("expected_program") is not None]
    program_correct = sum(1 for c in program_cases if c.get("program_correct"))

    advisor_name_cases = [c for c in named_match_cases if c.get("expected_advisor_name") is not None]
    advisor_name_correct = sum(1 for c in advisor_name_cases if c.get("advisor_name_correct"))

    email_cases = [c for c in named_match_cases if c.get("expected_email") is not None]
    email_correct = sum(1 for c in email_cases if c.get("email_correct"))

    source_cases = [c for c in named_match_cases if c.get("expected_source_url") is not None]
    source_correct = sum(1 for c in source_cases if c.get("source_correct"))

    # ── Suggestion coverage ────────────────────────────────────────────────
    # Cases where expected_suggestions_include is non-empty.
    suggestion_cases = [c for c in cases if c.get("expected_suggestions_include")]
    suggestions_covered = sum(1 for c in suggestion_cases if c.get("suggestions_fully_covered"))

    # ── Null-advisor handling ──────────────────────────────────────────────
    # Programs with known null advisor data — match found correctly, system
    # does not invent contact details.
    null_advisor_cases = [c for c in cases if c.get("has_null_advisor")]
    null_handled_correctly = sum(1 for c in null_advisor_cases if c.get("null_advisor_correct"))

    return {
        "overall_counts": {"total_cases": total, "pass": passed, "fail": failed},
        "route_accuracy":            _pct(route_correct, len(route_cases)),
        "advisor_match_rate":        _pct(match_found, len(should_match_cases)),
        "no_spurious_match_rate":    _pct(no_spurious_match, len(should_not_match_cases)),
        "program_accuracy":          _pct(program_correct, len(program_cases)),
        "advisor_name_accuracy":     _pct(advisor_name_correct, len(advisor_name_cases)),
        "email_accuracy":            _pct(email_correct, len(email_cases)),
        "source_accuracy":           _pct(source_correct, len(source_cases)),
        "suggestion_coverage":       _pct(suggestions_covered, len(suggestion_cases)),
        "null_advisor_handling_rate": _pct(null_handled_correctly, len(null_advisor_cases)),
    }


def format_console_summary(metrics: dict, execution_time_ms: float) -> str:
    """Render the Phase 8D metrics as a readable console block."""
    width = 50
    lines: list[str] = []
    lines.append("=" * width)
    lines.append("Advisor Answer Evaluation Summary")
    lines.append("=" * width)
    lines.append("")

    oc = metrics["overall_counts"]
    lines.append("Cases")
    lines.append(f"  Total: {oc['total_cases']}  Pass: {oc['pass']}  Fail: {oc['fail']}")
    lines.append("")

    lines.append("Routing")
    lines.append(f"  Route Accuracy: {metrics['route_accuracy']}%")
    lines.append("")

    lines.append("Match Quality")
    lines.append(f"  Advisor Match Rate: {metrics['advisor_match_rate']}%")
    lines.append(f"  No Spurious Match Rate: {metrics['no_spurious_match_rate']}%")
    lines.append(f"  Suggestion Coverage: {metrics['suggestion_coverage']}%")
    lines.append("")

    lines.append("Field Accuracy (named-advisor programs only)")
    lines.append(f"  Program Accuracy: {metrics['program_accuracy']}%")
    lines.append(f"  Advisor Name Accuracy: {metrics['advisor_name_accuracy']}%")
    lines.append(f"  Email Accuracy: {metrics['email_accuracy']}%")
    lines.append(f"  Source Accuracy: {metrics['source_accuracy']}%")
    lines.append("")

    lines.append("Edge Cases")
    lines.append(f"  Null Advisor Handling Rate: {metrics['null_advisor_handling_rate']}%")
    lines.append("")

    lines.append(f"Execution Time: {execution_time_ms} ms")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)
