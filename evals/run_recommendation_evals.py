#!/usr/bin/env python3
"""
evals/run_recommendation_evals.py
Phase 2B evaluation runner for the doctoral recommendation engine.

Loads evals/recommendation_eval_cases.json, replays each case's turns through
agents.journey_agent.handle_discovery on a fresh session, and compares the
final turn's behavior / confidence / recommended_programs against the gold
expectations recorded in the dataset.

known_gap=true cases are NOT treated as regressions. The dataset already
encodes the *current* (documented-limitation) behavior as the expected
values for those cases, so a match is reported as KNOWN_GAP rather than
PASS. A mismatch on a known_gap case is still reported as FAIL, since it
means current behavior has drifted even from the previously-documented
limitation and is worth investigating.

This script is evaluation infrastructure only:
  - does NOT modify recommendation engine, journey agent, or router logic
  - does NOT tune scoring weights or confidence rules
  - does NOT compute aggregate metrics (T1A/TNR/P@K/CES/etc — Phase 2C)
  - does NOT emit gradcenter_logging events
  - does NOT use an LLM, embeddings, or LangGraph

Usage (from project root):
    python evals/run_recommendation_evals.py
    python -m evals.run_recommendation_evals [--dataset PATH] [--no-archive] [--verbose] [--ci]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Project root on sys.path ────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.journey_agent import handle_discovery, _SESSION_STORE  # noqa: E402
from evals.metrics_recommendation import compute_metrics, format_console_summary  # noqa: E402
from evals.error_classification import (  # noqa: E402
    classify, build_error_summary, format_error_summary_console,
)

# ── Paths ────────────────────────────────────────────────────────────────────
_EVALS_DIR       = Path(__file__).parent
_REPORTS_DIR     = _EVALS_DIR / "reports"
_DEFAULT_DATASET = _EVALS_DIR / "recommendation_eval_cases.json"

_REQUIRED_TOP_KEYS = ("_schema_version", "_scope", "_source", "_taxonomy_version", "cases")


# ── Case execution ──────────────────────────────────────────────────────────

def _run_case_turns(case: dict) -> dict:
    """Replay all turns for a case through handle_discovery on a fresh session.

    Returns the final turn's DiscoveryResponse (or an error string on exception).
    """
    sid = f"recoeval_{case['case_id']}"
    _SESSION_STORE.pop(sid, None)

    response: dict = {}
    error: Optional[str] = None
    try:
        for turn in case["turns"]:
            response, _state = handle_discovery(turn, sid)
    except Exception as exc:  # noqa: BLE001 — capture and report, don't crash the run
        error = repr(exc)
    finally:
        _SESSION_STORE.pop(sid, None)

    return {"response": response, "error": error}


def _actual_snapshot(response: dict) -> dict:
    return {
        "behavior":               response.get("behavior"),
        "confidence":              response.get("confidence"),
        "recommended_programs":    response.get("recommended_programs", []),
        "program_matches":         response.get("program_matches", []),
        "clarification_question":  response.get("clarification_question"),
    }


def _compare(case: dict, actual: dict) -> list[dict]:
    """Return {field, expected, actual} entries for every mismatched gated field.

    Gated fields: expected_behavior, expected_confidence, expected_programs.
    (clarification_question / program_matches are captured for visibility only.)
    """
    diffs: list[dict] = []

    exp_behavior = case["expected_behavior"]
    if actual["behavior"] != exp_behavior:
        diffs.append({"field": "behavior", "expected": exp_behavior, "actual": actual["behavior"]})

    exp_confidence = case["expected_confidence"]
    if actual["confidence"] != exp_confidence:
        diffs.append({"field": "confidence", "expected": exp_confidence, "actual": actual["confidence"]})

    exp_programs = sorted(case["expected_programs"])
    act_programs = sorted(actual["recommended_programs"] or [])
    if exp_programs != act_programs:
        diffs.append({
            "field": "recommended_programs",
            "expected": exp_programs,
            "actual": act_programs,
        })

    return diffs


def _run_case(case: dict) -> dict:
    expected = {
        "expected_behavior":   case["expected_behavior"],
        "expected_confidence": case["expected_confidence"],
        "expected_programs":   case["expected_programs"],
    }

    run_result = _run_case_turns(case)

    if run_result["error"]:
        diffs = [{
            "field": "execution", "expected": "no exception", "actual": run_result["error"],
        }]
        error_category, error_reason = classify(
            case["known_gap"], expected, None, diffs, run_result["error"],
        )
        return {
            "case_id":        case["case_id"],
            "category":       case.get("category"),
            "sub_category":   case.get("sub_category"),
            "status":         "FAIL",
            "error_category": error_category,
            "error_reason":   error_reason,
            "known_gap":      case["known_gap"],
            "expected":       expected,
            "actual":         None,
            "differences":    diffs,
            "error":          run_result["error"],
        }

    actual = _actual_snapshot(run_result["response"])
    diffs  = _compare(case, actual)

    if diffs:
        status = "FAIL"
    elif case["known_gap"]:
        status = "KNOWN_GAP"
    else:
        status = "PASS"

    error_category, error_reason = classify(case["known_gap"], expected, actual, diffs, None)

    return {
        "case_id":        case["case_id"],
        "category":       case.get("category"),
        "sub_category":   case.get("sub_category"),
        "status":         status,
        "error_category": error_category,
        "error_reason":   error_reason,
        "known_gap":      case["known_gap"],
        "expected":       expected,
        "actual":         actual,
        "differences":    diffs,
        "error":          None,
    }


# ── Report ───────────────────────────────────────────────────────────────────

def _build_summary(results: list[dict]) -> dict:
    total                = len(results)
    passes               = sum(1 for r in results if r["status"] == "PASS")
    known_gap_passes     = sum(1 for r in results if r["status"] == "KNOWN_GAP")
    unexpected_failures  = sum(1 for r in results if r["status"] == "FAIL")
    return {
        "total_cases":          total,
        "passes":               passes,
        "known_gap_passes":     known_gap_passes,
        "unexpected_failures":  unexpected_failures,
    }


def _build_report(results: list[dict], dataset_path: Path, dataset: dict) -> dict:
    return {
        "schema_version":         "1.0",
        "run_id":                 str(uuid.uuid4()),
        "timestamp":              (datetime.now(timezone.utc)
                                   .isoformat(timespec="seconds")
                                   .replace("+00:00", "Z")),
        "dataset_path":           str(dataset_path),
        "dataset_schema_version": dataset.get("_schema_version"),
        "dataset_scope":          dataset.get("_scope"),
        "dataset_taxonomy_version": dataset.get("_taxonomy_version"),
        "summary":                _build_summary(results),
        "cases":                  results,
        "metrics":                compute_metrics(results),
        "error_summary":          build_error_summary(results),
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_recommendation_eval_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"recommendation_eval_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ── Terminal output ──────────────────────────────────────────────────────────

_LABEL = {"PASS": "PASS", "KNOWN_GAP": "KNOWN GAP", "FAIL": "FAIL"}


def _print_case_live(result: dict, verbose: bool) -> None:
    label = _LABEL.get(result["status"], result["status"])
    print(f"{label:<12} {result['case_id']}")
    if result["status"] == "FAIL" or verbose:
        print(f"             [{result['error_category']}] {result['error_reason']}")
        for d in result["differences"]:
            print(f"             - {d['field']}: expected={d['expected']!r} actual={d['actual']!r}")
        if result.get("error"):
            print(f"             error: {result['error'][:200]}")


def _print_header(n: int) -> None:
    print("=" * 50)
    print("Recommendation Evaluation")
    print("=" * 50)
    print()
    print(f"Running {n} cases...")
    print()


def _print_footer(report: dict, latest: Path, archive: Optional[Path]) -> None:
    s = report["summary"]
    print()
    print("Summary")
    print()
    print(f"Total Cases: {s['total_cases']}")
    print(f"Pass: {s['passes']}")
    print(f"Known Gap: {s['known_gap_passes']}")
    print(f"Unexpected Failures: {s['unexpected_failures']}")
    print()
    print(f"Report: {latest}")
    if archive:
        print(f"        {archive}")


def _print_error_summary(report: dict) -> None:
    print()
    print(format_error_summary_console(report["error_summary"]))


# ── Validation of dataset shape (fail fast, don't half-run) ────────────────

def _validate_dataset(dataset: dict, dataset_path: Path) -> list[dict]:
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in dataset]
    if missing:
        print(f"[run_recommendation_evals] ERROR: dataset missing top-level keys: {missing}",
              file=sys.stderr)
        sys.exit(1)

    cases = dataset.get("cases", [])
    if not cases:
        print(f"[run_recommendation_evals] ERROR: no cases found in {dataset_path}",
              file=sys.stderr)
        sys.exit(1)

    return cases


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_recommendation_evals",
        description="Phase 2B recommendation evaluation runner — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--dataset", default=str(_DEFAULT_DATASET),
        help="Path to the recommendation eval gold dataset "
             "(default: evals/recommendation_eval_cases.json)",
    )
    p.add_argument(
        "--no-archive", action="store_true",
        help="Write only latest_recommendation_eval_report.json, skip timestamped archive",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Print per-field differences for every case, not just FAIL",
    )
    p.add_argument(
        "--ci", action="store_true",
        help="Exit 1 if any case has status FAIL (KNOWN_GAP does not trigger)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[run_recommendation_evals] ERROR: dataset not found: {dataset_path}",
              file=sys.stderr)
        sys.exit(1)

    with dataset_path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)

    cases = _validate_dataset(dataset, dataset_path)

    _print_header(len(cases))

    results: list[dict] = []
    for case in cases:
        result = _run_case(case)
        results.append(result)
        _print_case_live(result, verbose=args.verbose)

    report          = _build_report(results, dataset_path, dataset)
    latest, archive = _write_report(report, args.no_archive)
    _print_footer(report, latest, archive)
    _print_error_summary(report)

    print()
    print(format_console_summary(report["metrics"]))

    if args.ci and report["summary"]["unexpected_failures"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
