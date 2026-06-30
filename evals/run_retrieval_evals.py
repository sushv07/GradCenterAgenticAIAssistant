#!/usr/bin/env python3
"""
evals/run_retrieval_evals.py
Phase 8A evaluation runner for retrieval quality — independent of
recommendation quality, answer generation, or LLM performance.

Loads evals/retrieval_eval_cases.json and runs each case through the REAL
rag.retriever.retrieve() against the real, live persisted Chroma store —
no mocking, no LLM, no semantic/embedding similarity computed by this
runner itself (the underlying retriever uses embeddings; the EVALUATION
methodology here only compares structured fields: page_type, url,
chunk_id, score, and result count).

Why this exercises the real function instead of reimplementing checks:
    Mirrors run_recommendation_evals.py calling the real handle_discovery()
    and run_llm_evals.py calling the real attach_explanations()/
    synthesize_answer() — retrieval correctness is measured against
    rag.retriever.retrieve()'s actual current behavior, never a
    reimplementation that could silently drift from it.

This script is evaluation infrastructure only:
  - does NOT modify rag/retriever.py, rag/store.py, or any chunking/
    ranking/embedding logic
  - does NOT use an LLM, semantic similarity, or embedding similarity for
    evaluation itself
  - does NOT redesign retrieval, chunking, or ranking — see the Phase 8A
    output report for the one real finding (a reproducible duplicate
    chunk_id) this run surfaced, which is documented, not fixed

Usage (from project root):
    python evals/run_retrieval_evals.py
    python -m evals.run_retrieval_evals [--no-archive] [--verbose] [--ci]
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

from rag.retriever import retrieve  # noqa: E402
from evals.metrics_retrieval import compute_retrieval_metrics, format_console_summary  # noqa: E402
from evals.error_classification_retrieval import (  # noqa: E402
    classify_retrieval, build_error_summary, format_error_summary_console,
)

# ── Paths ────────────────────────────────────────────────────────────────────
_EVALS_DIR       = Path(__file__).parent
_REPORTS_DIR     = _EVALS_DIR / "reports"
_DEFAULT_DATASET = _EVALS_DIR / "retrieval_eval_cases.json"

_REQUIRED_TOP_KEYS = ("_schema_version", "_scope", "_source", "cases")


# ---------------------------------------------------------------------------
# Source matching
# ---------------------------------------------------------------------------

def _matches_source(result: dict, spec: dict) -> bool:
    if "page_type" in spec and result.get("page_type") != spec["page_type"]:
        return False
    if "url" in spec and result.get("url") != spec["url"]:
        return False
    return True


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------

def _run_case(case: dict) -> dict:
    results = retrieve(
        case["query"],
        k=case.get("k", 3),
        page_type=case.get("page_type_filter"),
    )

    is_empty   = len(results) == 0
    top_score  = results[0]["score"] if results else 0.0
    chunk_ids  = [r["chunk_id"] for r in results]
    has_duplicates = len(chunk_ids) != len(set(chunk_ids))

    expected_sources  = case.get("expected_sources", [])
    forbidden_sources = case.get("forbidden_sources", [])

    expected_source_results = []
    for spec in expected_sources:
        positions = [i for i, r in enumerate(results) if _matches_source(r, spec)]
        expected_source_results.append({
            "spec": spec, "found": bool(positions),
            "best_position": positions[0] if positions else None,
        })

    forbidden_found = [
        spec for spec in forbidden_sources
        if any(_matches_source(r, spec) for r in results)
    ]

    top1_match = bool(expected_sources) and bool(results) and any(
        _matches_source(results[0], spec) for spec in expected_sources
    )
    topk_match = bool(expected_sources) and any(s["found"] for s in expected_source_results)

    actual = {
        "num_results":   len(results),
        "is_empty":       is_empty,
        "top_score":      top_score,
        "has_duplicates": has_duplicates,
        "page_types_returned": [r["page_type"] for r in results],
        "urls_returned":  [r["url"] for r in results],
        "chunk_ids":      chunk_ids,
    }

    # ── Pass/fail determination ─────────────────────────────────────────────
    failures: list[str] = []
    if case.get("expect_empty") and not is_empty:
        failures.append("expected_empty_but_got_results")
    if not case.get("expect_empty") and case.get("expected_min_chunks", 0) > 0 and is_empty:
        failures.append("insufficient_chunks")
    if expected_sources and not topk_match:
        failures.append("missing_expected_source")
    if forbidden_found:
        failures.append("unexpected_source")
    if has_duplicates and not case.get("allow_duplicate_chunks", False):
        failures.append("duplicate_chunks")
    if expected_sources and topk_match and not top1_match and len(expected_sources) == 1:
        # A single-expected-source case where the source was found but not
        # ranked first is still a FAIL for Top-1 evaluation purposes.
        failures.append("ranking_error")

    status = "FAIL" if failures else "PASS"

    result: dict = {
        "case_id":      case["case_id"],
        "description":  case.get("description", ""),
        "query":        case["query"],
        "status":       status,
        "actual":       actual,
        "expected_sources": expected_sources,
        "expected_source_results": expected_source_results,
        "forbidden_found": forbidden_found,
        "top1_match":   top1_match,
        "topk_match":   topk_match,
        "failures":     failures,
    }

    error_category, error_reason = classify_retrieval(case, result)
    result["error_category"] = error_category
    result["error_reason"]   = error_reason

    return result


# ---------------------------------------------------------------------------
# Dataset loading / validation
# ---------------------------------------------------------------------------

def _load_dataset(path: Path) -> dict:
    if not path.exists():
        print(f"[run_retrieval_evals] ERROR: dataset not found: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in dataset]
    if missing:
        print(f"[run_retrieval_evals] ERROR: dataset missing top-level keys: {missing}", file=sys.stderr)
        sys.exit(1)
    if not dataset.get("cases"):
        print(f"[run_retrieval_evals] ERROR: no cases found in {path}", file=sys.stderr)
        sys.exit(1)
    return dataset


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_summary(results: list[dict]) -> dict:
    return {
        "total_cases": len(results),
        "passed":      sum(1 for r in results if r["status"] == "PASS"),
        "failed":      sum(1 for r in results if r["status"] == "FAIL"),
        "skipped":     0,
    }


def _build_report(results: list[dict], dataset_path: Path, dataset: dict, execution_time_ms: float) -> dict:
    return {
        "schema_version":   "1.0",
        "run_id":           str(uuid.uuid4()),
        "timestamp":        (datetime.now(timezone.utc)
                             .isoformat(timespec="seconds")
                             .replace("+00:00", "Z")),
        "dataset_path":     str(dataset_path),
        "dataset_schema_version": dataset.get("_schema_version"),
        "summary":          {**_build_summary(results), "execution_time_ms": execution_time_ms},
        "cases":            results,
        "metrics":          compute_retrieval_metrics(results),
        "error_summary":    build_error_summary(results),
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_retrieval_eval_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"retrieval_eval_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def _print_header(n: int) -> None:
    print("=" * 50)
    print("Retrieval Evaluation")
    print("=" * 50)
    print()
    print(f"Running {n} cases against the live Chroma store...")
    print()


def _print_case_live(result: dict, verbose: bool) -> None:
    label = result["status"]
    print(f"{label:<6} {result['case_id']:<14} "
          f"n={result['actual']['num_results']} top_score={result['actual']['top_score']:.4f}")
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
        prog="run_retrieval_evals",
        description="Phase 8A retrieval evaluation runner — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--dataset", default=str(_DEFAULT_DATASET),
        help="Path to the retrieval eval dataset (default: evals/retrieval_eval_cases.json)",
    )
    p.add_argument(
        "--no-archive", action="store_true",
        help="Write only latest_retrieval_eval_report.json, skip timestamped archive",
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
