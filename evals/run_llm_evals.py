#!/usr/bin/env python3
"""
evals/run_llm_evals.py
Phase 7D evaluation runner for LLM-generated content (recommendation
explanations and grounded answer generation).

Loads evals/llm_explanation_eval_cases.json and evals/llm_answer_eval_cases.json,
runs each case through the REAL production functions —
agents.recommendation_explainer.attach_explanations() and
agents.llm_synthesizer.synthesize_answer() — with requests.post mocked per
the case's "simulate" spec (a scripted Ollama-shaped response or a
simulated failure), and compares the observed outcome against each case's
expected_outcome.

Why this exercises the real functions instead of reimplementing checks:
    The grounding/safety logic (citation-fidelity checking, evidence
    parsing, graceful-degradation fallback) already lives in
    agents/recommendation_explainer.py (Phase 7B) and
    agents/llm_synthesizer.py (Phase 7C). Reimplementing those checks here
    would let this evaluation silently drift from what the system actually
    does. Mirrors how run_recommendation_evals.py calls the real
    handle_discovery() rather than reimplementing recommendation logic.

No live LLM required by default — every case's Ollama response is fully
scripted via the dataset's "simulate" field. There is no --live mode in
this phase; that would require a running local Ollama server and is left
as documented future work (see ARCHITECTURE_ANALYSIS.md's Phase 7D section).

This script is evaluation infrastructure only:
  - does NOT modify recommendation_explainer.py or llm_synthesizer.py
  - does NOT modify prompts
  - does NOT use an LLM, embeddings, semantic similarity, or LLM-as-judge
  - does NOT integrate LangSmith, OpenTelemetry, TruLens, DeepEval, or Ragas

Usage (from project root):
    python evals/run_llm_evals.py
    python -m evals.run_llm_evals [--no-archive] [--verbose] [--ci]
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
from unittest.mock import patch, MagicMock

import requests

# ── Project root on sys.path ────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import agents.recommendation_explainer as explainer  # noqa: E402
import agents.llm_synthesizer as synth  # noqa: E402
from agents.recommendation_explainer import attach_explanations  # noqa: E402
from agents.llm_synthesizer import synthesize_answer  # noqa: E402
from evals.metrics_llm import (  # noqa: E402
    compute_explanation_metrics, compute_answer_metrics, format_console_summary,
)
from evals.error_classification_llm import (  # noqa: E402
    classify_explanation, classify_answer, build_error_summary, format_error_summary_console,
)

# ── Paths ────────────────────────────────────────────────────────────────────
_EVALS_DIR             = Path(__file__).parent
_REPORTS_DIR           = _EVALS_DIR / "reports"
_EXPLANATION_DATASET   = _EVALS_DIR / "llm_explanation_eval_cases.json"
_ANSWER_DATASET        = _EVALS_DIR / "llm_answer_eval_cases.json"

_REQUIRED_TOP_KEYS = ("_schema_version", "_scope", "_source", "cases")

_DETERMINISTIC_FIELDS = ("program_id", "confidence", "score_basis", "advisor_email", "deadline_fall")


# ---------------------------------------------------------------------------
# Mocked Ollama response construction
# ---------------------------------------------------------------------------

def _patch_requests_post(simulate: dict):
    """Return an unentered patch() context manager for requests.post,
    configured per the case's simulate spec."""
    mode = simulate["mode"]

    if mode == "connection_error":
        return patch("requests.post", side_effect=requests.exceptions.ConnectionError("simulated outage"))
    if mode == "timeout":
        return patch("requests.post", side_effect=requests.exceptions.Timeout("simulated timeout"))
    if mode == "malformed_json":
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"content": "not valid json {"}}
        return patch("requests.post", return_value=resp)
    if mode == "success":
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        content = {k: v for k, v in simulate.items() if k != "mode"}
        resp.json.return_value = {"message": {"content": json.dumps(content)}}
        return patch("requests.post", return_value=resp)

    raise ValueError(f"unknown simulate mode: {mode!r}")


# ---------------------------------------------------------------------------
# Recommendation Explanation cases
# ---------------------------------------------------------------------------

def _derive_explanation_outcome(case: dict, match_before: dict, match_after: dict) -> str:
    if "explanation" in match_after:
        return "explanation_attached"

    evidence = explainer._parse_score_basis(match_before.get("score_basis") or [])
    if not explainer._has_any_evidence(evidence):
        return "no_explanation_no_evidence"

    mode = case["simulate"]["mode"]
    if mode in ("connection_error", "timeout"):
        return "no_explanation_graceful_fallback"
    return "no_explanation_validation_failure"


def _run_explanation_case(case: dict) -> dict:
    match_before = dict(case["program_match"])
    matches = [dict(match_before)]

    with patch.object(explainer, "_ENABLED", True), \
         _patch_requests_post(case["simulate"]), \
         patch("utils.retry.time.sleep"):
        attach_explanations(matches)
    match_after = matches[0]

    actual_outcome = _derive_explanation_outcome(case, match_before, match_after)
    drift_detected = any(match_before.get(f) != match_after.get(f) for f in _DETERMINISTIC_FIELDS)

    result: dict = {
        "case_id":                       case["case_id"],
        "description":                   case.get("description", ""),
        "expected_outcome":              case["expected_outcome"],
        "actual_outcome":                actual_outcome,
        "deterministic_drift_detected":  drift_detected,
    }

    if actual_outcome == "explanation_attached":
        explanation_text   = (match_after.get("explanation") or "").lower()
        expected_phrases    = case.get("expected_evidence_phrases", [])
        forbidden_phrases   = case.get("forbidden_phrases", [])
        missing             = [p for p in expected_phrases if p.lower() not in explanation_text]
        found_forbidden     = [p for p in forbidden_phrases if p.lower() in explanation_text]
        result["evidence_fully_covered"]    = not missing
        result["missing_evidence_phrases"]  = missing
        result["forbidden_phrase_found"]    = bool(found_forbidden)
        result["forbidden_phrases_found"]   = found_forbidden

    content_issue = (
        actual_outcome == "explanation_attached"
        and (result.get("forbidden_phrase_found") or not result.get("evidence_fully_covered", True))
    )
    status = "FAIL" if (drift_detected or actual_outcome != case["expected_outcome"] or content_issue) else "PASS"
    result["status"] = status

    error_category, error_reason = classify_explanation(case, result)
    result["error_category"] = error_category
    result["error_reason"]   = error_reason

    return result


# ---------------------------------------------------------------------------
# Grounded Answer cases
# ---------------------------------------------------------------------------

def _derive_answer_outcome(case: dict, llm_result: Optional[dict]) -> str:
    if llm_result is not None:
        return "accepted"

    mode = case["simulate"]["mode"]
    if mode in ("connection_error", "timeout"):
        return "rejected_network_failure"
    if mode == "malformed_json":
        return "rejected_malformed_output"

    # mode == "success" but still rejected by _validate() — figure out why
    answer_text = case["simulate"].get("answer", "")
    confidence  = case["simulate"].get("confidence", "")
    if not answer_text or not answer_text.strip() or confidence not in {"high", "medium", "low"}:
        return "rejected_malformed_output"
    return "rejected_fabricated_citation"


def _run_answer_case(case: dict) -> dict:
    with patch.object(synth, "_ENABLED", True), \
         _patch_requests_post(case["simulate"]), \
         patch("utils.retry.time.sleep"):
        llm_result = synthesize_answer(
            case["query"], case["retrieved_evidence"], "eval.json",
            source_url=case.get("source_url"),
        )

    actual_outcome = _derive_answer_outcome(case, llm_result)
    status = "PASS" if actual_outcome == case["expected_outcome"] else "FAIL"

    result: dict = {
        "case_id":             case["case_id"],
        "description":         case.get("description", ""),
        "expected_outcome":    case["expected_outcome"],
        "actual_outcome":      actual_outcome,
        "simulated_confidence": case["simulate"].get("confidence"),
        "llm_result":          llm_result,
        "status":              status,
    }

    error_category, error_reason = classify_answer(case, result)
    result["error_category"] = error_category
    result["error_reason"]   = error_reason

    return result


# ---------------------------------------------------------------------------
# Dataset loading / validation
# ---------------------------------------------------------------------------

def _load_dataset(path: Path) -> dict:
    if not path.exists():
        print(f"[run_llm_evals] ERROR: dataset not found: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in dataset]
    if missing:
        print(f"[run_llm_evals] ERROR: {path} missing top-level keys: {missing}", file=sys.stderr)
        sys.exit(1)
    if not dataset.get("cases"):
        print(f"[run_llm_evals] ERROR: no cases found in {path}", file=sys.stderr)
        sys.exit(1)
    return dataset


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(
    explanation_results: list[dict],
    answer_results: list[dict],
    explanation_dataset: dict,
    answer_dataset: dict,
    execution_time_ms: float,
) -> dict:
    explanation_metrics = compute_explanation_metrics(explanation_results)
    answer_metrics       = compute_answer_metrics(answer_results)

    return {
        "schema_version": "1.0",
        "run_id":         str(uuid.uuid4()),
        "timestamp":      (datetime.now(timezone.utc)
                           .isoformat(timespec="seconds")
                           .replace("+00:00", "Z")),
        "explanation_dataset_schema_version": explanation_dataset.get("_schema_version"),
        "answer_dataset_schema_version":      answer_dataset.get("_schema_version"),
        "summary": {
            "total_cases": len(explanation_results) + len(answer_results),
            "passed":      sum(1 for r in explanation_results + answer_results if r["status"] == "PASS"),
            "failed":      sum(1 for r in explanation_results + answer_results if r["status"] == "FAIL"),
            "skipped":     0,
            "execution_time_ms": execution_time_ms,
        },
        "recommendation_explanation": {
            "cases":   explanation_results,
            "metrics": explanation_metrics,
            "error_summary": build_error_summary(explanation_results),
        },
        "grounded_answer": {
            "cases":   answer_results,
            "metrics": answer_metrics,
            "error_summary": build_error_summary(answer_results),
        },
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_llm_eval_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"llm_eval_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def _print_header(n_explanation: int, n_answer: int) -> None:
    print("=" * 50)
    print("LLM Evaluation")
    print("=" * 50)
    print()
    print(f"Running {n_explanation} recommendation-explanation cases "
          f"and {n_answer} grounded-answer cases...")
    print()


def _print_case_live(result: dict, verbose: bool) -> None:
    label = result["status"]
    print(f"{label:<6} {result['case_id']:<14} {result['actual_outcome']}")
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
        prog="run_llm_evals",
        description="Phase 7D LLM evaluation runner — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--no-archive", action="store_true",
        help="Write only latest_llm_eval_report.json, skip timestamped archive",
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

    explanation_dataset = _load_dataset(_EXPLANATION_DATASET)
    answer_dataset       = _load_dataset(_ANSWER_DATASET)

    explanation_cases = explanation_dataset["cases"]
    answer_cases       = answer_dataset["cases"]

    _print_header(len(explanation_cases), len(answer_cases))

    t0 = time.perf_counter()

    explanation_results: list[dict] = []
    print("Recommendation Explanation")
    for case in explanation_cases:
        result = _run_explanation_case(case)
        explanation_results.append(result)
        _print_case_live(result, verbose=args.verbose)

    print()
    answer_results: list[dict] = []
    print("Grounded Answer Generation")
    for case in answer_cases:
        result = _run_answer_case(case)
        answer_results.append(result)
        _print_case_live(result, verbose=args.verbose)

    execution_time_ms = round((time.perf_counter() - t0) * 1000, 1)

    report = _build_report(
        explanation_results, answer_results, explanation_dataset, answer_dataset, execution_time_ms,
    )
    latest, archive = _write_report(report, args.no_archive)
    _print_footer(report, latest, archive)

    print()
    print(format_error_summary_console(
        report["recommendation_explanation"]["error_summary"], "Recommendation Explanation Errors"))
    print()
    print(format_error_summary_console(
        report["grounded_answer"]["error_summary"], "Grounded Answer Errors"))

    print()
    print(format_console_summary(
        report["recommendation_explanation"]["metrics"],
        report["grounded_answer"]["metrics"],
        execution_time_ms,
    ))

    if args.ci and report["summary"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
