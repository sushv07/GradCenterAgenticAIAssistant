#!/usr/bin/env python3
"""
evals/run_advisor_evals.py
Phase 8D evaluation runner for advisor and program-information answers.

Loads evals/advisor_answer_eval_cases.json and runs each case through the
REAL pipeline — backend.entrypoint.handle_user_query() — exercising routing,
advisor fuzzy matching (retrieval/advisor_retrieval.find_advisor()), and
response assembly (orchestrator._build_advisor_response()). No mocking, no
LLM, no semantic similarity used by this runner itself.

Why handle_user_query() rather than find_advisor() directly:
    Calling find_advisor() directly would miss routing failures: a case
    where the query SHOULD route to "advisor" but instead routes to
    "answer" or "guidance" would pass the lower-level check but fail in
    production. handle_user_query() exercises the FULL advisor path
    (routing → advisor retrieval → response building), matching exactly
    what a real user receives — the same philosophy run_recommendation_
    evals.py applies (exercising handle_discovery() via the real
    handle_user_query(), not select_recommendation() in isolation).

What this runner evaluates:
  - Route correctness (did the query land on the "advisor" route?)
  - Advisor match presence (was a match found when one was expected?)
  - No-spurious-match correctness (no match when none was expected?)
  - Program name accuracy
  - Advisor name accuracy
  - Email accuracy
  - Source URL accuracy
  - Suggestion coverage for ambiguous queries
  - Graceful handling of programs with null contact data

What this runner does NOT do:
  - Does NOT modify advisor_retrieval.py, advisors_extracted.json, or
    any routing/retrieval/recommendation logic
  - Does NOT use semantic similarity or LLM-as-judge
  - Does NOT improve advisor matching quality

Usage (from project root):
    python evals/run_advisor_evals.py
    python -m evals.run_advisor_evals [--no-archive] [--verbose] [--ci]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Project root on sys.path ────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.entrypoint import handle_user_query  # noqa: E402
from state.context_manager import clear_context   # noqa: E402
from evals.metrics_advisor import compute_advisor_metrics, format_console_summary  # noqa: E402
from evals.error_classification_advisor import (  # noqa: E402
    classify_advisor, build_error_summary, format_error_summary_console,
)

# ── Paths ────────────────────────────────────────────────────────────────────
_EVALS_DIR       = Path(__file__).parent
_REPORTS_DIR     = _EVALS_DIR / "reports"
_DEFAULT_DATASET = _EVALS_DIR / "advisor_answer_eval_cases.json"

_REQUIRED_TOP_KEYS = ("_schema_version", "_scope", "_source", "cases")

_EVAL_SESSION_ID = "advisor_eval_runner"


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------

def _run_case(case: dict) -> dict:
    """
    Execute one advisor eval case through the real handle_user_query()
    and compare the response against the case's expectations.

    The session is cleared before each case so discovery state from a
    previous case cannot bleed into subsequent ones.
    """
    clear_context(_EVAL_SESSION_ID)
    response = handle_user_query(case["query"], session_id=_EVAL_SESSION_ID)

    actual_route = response.get("route")
    adv          = response.get("advisor_data") or {}
    match        = adv.get("match") or {}
    actual_conf  = adv.get("confidence")
    suggestions  = adv.get("suggestions") or []

    match_present       = match.get("program") is not None
    actual_program      = match.get("program") or ""
    actual_advisor_name = match.get("advisor_name") or ""
    actual_email        = match.get("email") or ""
    actual_source_url   = match.get("source") or ""

    # ── Route correctness ──────────────────────────────────────────────────
    expected_route     = case.get("expected_route")       # may be None (welcome)
    expected_route_not = case.get("expected_route_is_not")

    if expected_route is not None or expected_route_not is not None:
        expected_route_checked = True
        if expected_route is not None:
            route_correct = (actual_route == expected_route)
            expected_route_value = expected_route
        else:
            # expected_route_is_not — the route must be anything BUT this value
            route_correct = (actual_route != expected_route_not)
            expected_route_value = f"not:{expected_route_not}"
    else:
        expected_route_checked = False
        route_correct          = True
        expected_route_value   = None

    # ── Match presence ─────────────────────────────────────────────────────
    expected_match_flag = case.get("expected_match", False)
    match_correct = (match_present == expected_match_flag)

    # ── Field-level accuracy ───────────────────────────────────────────────
    expected_program      = case.get("expected_program")
    expected_advisor_name = case.get("expected_advisor_name")
    expected_email        = case.get("expected_email")
    expected_source_url   = case.get("expected_source_url")
    has_null_advisor       = case.get("has_null_advisor", False)

    program_correct      = (actual_program == expected_program) if expected_program else True
    advisor_name_correct = (actual_advisor_name == expected_advisor_name) if expected_advisor_name else True
    email_correct        = (actual_email == expected_email) if expected_email else True
    source_correct       = (actual_source_url == expected_source_url) if expected_source_url else True

    # ── Null-advisor handling ──────────────────────────────────────────────
    null_advisor_correct = True
    if has_null_advisor and match_present:
        null_advisor_correct = (
            match.get("advisor_name") is None and match.get("email") is None
        )

    # ── Suggestion coverage ────────────────────────────────────────────────
    expected_suggestions_include = case.get("expected_suggestions_include", [])
    missing_suggestions: list[str] = []
    if expected_suggestions_include:
        missing_suggestions = [s for s in expected_suggestions_include if s not in suggestions]
    suggestions_fully_covered = not missing_suggestions

    # ── Pass / Fail ────────────────────────────────────────────────────────
    failures: list[str] = []
    if expected_route_checked and not route_correct:
        failures.append("route_mismatch")
    if not match_correct:
        if expected_match_flag:
            failures.append("match_not_found")
        else:
            failures.append("spurious_match")
    if match_present and expected_match_flag:
        if has_null_advisor and not null_advisor_correct:
            failures.append("null_advisor_unexpected_data")
        elif not has_null_advisor:
            if expected_program and not program_correct:
                failures.append("wrong_program")
            if expected_advisor_name and not advisor_name_correct:
                failures.append("wrong_advisor")
            if expected_email and not email_correct:
                failures.append("wrong_email")
            if expected_source_url and not source_correct:
                failures.append("wrong_source")
    if expected_suggestions_include and not suggestions_fully_covered:
        failures.append("suggestion_failure")

    status = "FAIL" if failures else "PASS"

    result: dict = {
        "case_id":             case["case_id"],
        "description":         case.get("description", ""),
        "query":                case["query"],
        "status":               status,
        "failures":             failures,
        # Route
        "expected_route_checked": expected_route_checked,
        "expected_route_value":   expected_route_value,
        "actual_route":           actual_route,
        "route_correct":          route_correct,
        # Match
        "expected_match":         expected_match_flag,
        "match_present":          match_present,
        # Field-level
        "expected_program":       expected_program,
        "actual_program":         actual_program,
        "program_correct":        program_correct,
        "expected_advisor_name":  expected_advisor_name,
        "actual_advisor_name":    actual_advisor_name,
        "advisor_name_correct":   advisor_name_correct,
        "expected_email":         expected_email,
        "actual_email":           actual_email,
        "email_correct":          email_correct,
        "expected_source_url":    expected_source_url,
        "actual_source_url":      actual_source_url,
        "source_correct":         source_correct,
        # Null advisor
        "has_null_advisor":       has_null_advisor,
        "null_advisor_correct":   null_advisor_correct,
        # Suggestions
        "expected_suggestions_include": expected_suggestions_include,
        "actual_suggestions":     suggestions,
        "suggestions_fully_covered": suggestions_fully_covered,
        "missing_suggestions":    missing_suggestions,
        # Confidence
        "actual_confidence":      actual_conf,
    }

    error_category, error_reason = classify_advisor(case, result)
    result["error_category"] = error_category
    result["error_reason"]   = error_reason

    return result


# ---------------------------------------------------------------------------
# Dataset loading / validation
# ---------------------------------------------------------------------------

def _load_dataset(path: Path) -> dict:
    if not path.exists():
        print(f"[run_advisor_evals] ERROR: dataset not found: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in dataset]
    if missing:
        print(f"[run_advisor_evals] ERROR: dataset missing top-level keys: {missing}", file=sys.stderr)
        sys.exit(1)
    if not dataset.get("cases"):
        print(f"[run_advisor_evals] ERROR: no cases found in {path}", file=sys.stderr)
        sys.exit(1)
    return dataset


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(results: list[dict], dataset_path: Path, dataset: dict, execution_time_ms: float) -> dict:
    return {
        "schema_version":   "1.0",
        "run_id":           str(uuid.uuid4()),
        "timestamp":        (datetime.now(timezone.utc)
                             .isoformat(timespec="seconds")
                             .replace("+00:00", "Z")),
        "dataset_path":     str(dataset_path),
        "dataset_schema_version": dataset.get("_schema_version"),
        "summary": {
            "total_cases":      len(results),
            "passed":           sum(1 for r in results if r["status"] == "PASS"),
            "failed":           sum(1 for r in results if r["status"] == "FAIL"),
            "skipped":          0,
            "execution_time_ms": execution_time_ms,
        },
        "cases":            results,
        "metrics":          compute_advisor_metrics(results),
        "error_summary":    build_error_summary(results),
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_advisor_eval_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"advisor_eval_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def _print_header(n: int) -> None:
    print("=" * 50)
    print("Advisor Answer Evaluation")
    print("=" * 50)
    print()
    print(f"Running {n} cases against the real advisor pipeline...")
    print()


def _print_case_live(result: dict, verbose: bool) -> None:
    label = result["status"]
    route_str = result.get("actual_route") or "None"
    prog_str  = (result.get("actual_program") or "<no match>")[:35]
    print(f"{label:<6} {result['case_id']:<12} route={route_str:<10} {prog_str}")
    if result["status"] == "FAIL" or verbose:
        print(f"       [{result['error_category']}] {result['error_reason']}")


def _print_footer(report: dict, latest: Path, archive: Optional[Path]) -> None:
    s = report["summary"]
    print()
    print("Summary")
    print()
    print(f"Total Cases: {s['total_cases']}")
    print(f"Passed: {s['passed']}")
    print(f"Failed: {s['failed']}")
    print(f"Skipped: {s['skipped']}")
    print(f"Execution Time: {s['execution_time_ms']} ms")
    print()
    print(f"Report: {latest}")
    if archive:
        print(f"        {archive}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_advisor_evals",
        description="Phase 8D advisor-answer evaluation runner — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--dataset", default=str(_DEFAULT_DATASET),
        help="Path to the advisor eval dataset",
    )
    p.add_argument(
        "--no-archive", action="store_true",
        help="Write only latest_advisor_eval_report.json, skip timestamped archive",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Print classification details for every case, not just FAIL",
    )
    p.add_argument(
        "--ci", action="store_true",
        help="Exit 1 if any case has status FAIL",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    dataset_path = Path(args.dataset)
    dataset      = _load_dataset(dataset_path)
    cases        = dataset["cases"]

    _print_header(len(cases))

    t0 = time.perf_counter()
    results: list[dict] = []
    for case in cases:
        result = _run_case(case)
        results.append(result)
        _print_case_live(result, verbose=args.verbose)
    execution_time_ms = round((time.perf_counter() - t0) * 1000, 1)

    report          = _build_report(results, dataset_path, dataset, execution_time_ms)
    latest, archive = _write_report(report, args.no_archive)
    _print_footer(report, latest, archive)

    print()
    print(format_error_summary_console(report["error_summary"]))

    print()
    print(format_console_summary(report["metrics"], execution_time_ms))

    if args.ci and report["summary"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
