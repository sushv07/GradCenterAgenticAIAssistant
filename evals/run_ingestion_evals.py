#!/usr/bin/env python3
"""
evals/run_ingestion_evals.py
Phase 9A evaluation runner for the ingestion pipeline output.

Loads evals/ingestion_eval_cases.json and evaluates the health of the
current knowledge base by inspecting the live Chroma store — NO network
requests, NO re-ingestion, NO re-embedding. This is a pure read-only
inspection of the already-built vector store, making it:

    - Offline: no fetch_page() calls, no HTTP requests
    - Safe: nothing written to chroma_db/ or any production file
    - Fast: store inspection is O(N) over chunk count, typically <2s
    - Deterministic: same store state → same results

Why inspect the store rather than re-running ingest_pages():
    ingestion.py fetches live CSULB pages over HTTP — running it in an
    offline eval would need network access to CSULB servers and would
    produce different results every time the pages change (non-reproducible
    without caching, and potentially slow). The built store IS the
    ingestion output artifact. Inspecting it directly is the correct
    "evaluate what was produced" approach, analogous to how run_evals.py
    inspects retrieval results rather than re-scraping sources.

What this runner evaluates (9 check types):
    total_chunk_count       — total chunks in store within [min, max]
    page_type_chunk_count   — chunks with given page_type within [min, max]
    program_chunk_count     — chunks with given program_name >= min
    distinct_program_count  — distinct non-empty program_name values >= min
    metadata_completeness   — required field non-empty on all chunks
    no_empty_chunks         — no chunks with empty page_content
    max_chunk_size          — no chunk exceeds CHUNK_SIZE characters
    url_chunk_count         — specific URL has chunks within [min, max]
    chunk_id_count          — specific chunk_id appears exactly N times

What this runner does NOT do:
    - does NOT modify rag/ingestion.py, rag/chunking.py, rag/store.py
    - does NOT re-ingest pages or rebuild the vector store
    - does NOT fetch any URL
    - does NOT use semantic similarity or LLM-as-judge

Usage (from project root):
    python evals/run_ingestion_evals.py
    python -m evals.run_ingestion_evals [--no-archive] [--verbose] [--ci]
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

from rag.store import load_vector_store  # noqa: E402
from evals.metrics_ingestion import compute_ingestion_metrics, format_console_summary  # noqa: E402
from evals.error_classification_ingestion import (  # noqa: E402
    classify_ingestion, build_error_summary, format_error_summary_console,
)

# ── Paths ────────────────────────────────────────────────────────────────────
_EVALS_DIR       = Path(__file__).parent
_REPORTS_DIR     = _EVALS_DIR / "reports"
_DEFAULT_DATASET = _EVALS_DIR / "ingestion_eval_cases.json"

_REQUIRED_TOP_KEYS = ("_schema_version", "_scope", "_source", "cases")


# ---------------------------------------------------------------------------
# Store inspection helpers
# ---------------------------------------------------------------------------

def _get_all_metadatas_and_docs(collection) -> tuple[list[dict], list[str]]:
    """Load all metadata and document text from the Chroma collection.
    Cached in a module-level variable within a single runner invocation
    to avoid re-fetching on every case."""
    items = collection.get(include=["metadatas", "documents"])
    return items["metadatas"], items["documents"]


_CACHED_METADATAS: Optional[list[dict]] = None
_CACHED_DOCUMENTS: Optional[list[str]] = None


def _get_cached(collection) -> tuple[list[dict], list[str]]:
    global _CACHED_METADATAS, _CACHED_DOCUMENTS
    if _CACHED_METADATAS is None:
        _CACHED_METADATAS, _CACHED_DOCUMENTS = _get_all_metadatas_and_docs(collection)
    return _CACHED_METADATAS, _CACHED_DOCUMENTS


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------

def _run_case(case: dict, collection) -> dict:
    """
    Execute one ingestion eval case by inspecting the Chroma collection.
    Returns a result dict with status, actual_value, and classification.
    """
    check_type = case["check_type"]
    metadatas, documents = _get_cached(collection)
    total = len(metadatas)

    # Shared result skeleton
    result: dict = {
        "case_id":    case["case_id"],
        "description": case.get("description", "")[:120],
        "check_type": check_type,
        "status":     "PASS",
        "actual_value": None,
        "failures":   [],
    }

    # ── total_chunk_count ─────────────────────────────────────────────────
    if check_type == "total_chunk_count":
        actual = total
        expected_min = case.get("expected_min", 0)
        expected_max = case.get("expected_max", float("inf"))
        result["actual_value"] = actual
        result["expected_min"] = expected_min
        result["expected_max"] = expected_max
        if not (expected_min <= actual <= expected_max):
            result["status"] = "FAIL"
            result["failures"].append(
                f"total_chunks={actual} not in [{expected_min}, {expected_max}]"
            )

    # ── page_type_chunk_count ─────────────────────────────────────────────
    elif check_type == "page_type_chunk_count":
        page_type = case["page_type"]
        actual = sum(1 for m in metadatas if m.get("page_type") == page_type)
        expected_min = case.get("expected_min", 1)
        expected_max = case.get("expected_max", float("inf"))
        result["actual_value"] = actual
        result["page_type"] = page_type
        result["expected_min"] = expected_min
        result["expected_max"] = expected_max
        if not (expected_min <= actual <= expected_max):
            result["status"] = "FAIL"
            result["failures"].append(
                f"page_type={page_type!r}: {actual} chunks not in [{expected_min}, {expected_max}]"
            )

    # ── program_chunk_count ───────────────────────────────────────────────
    elif check_type == "program_chunk_count":
        program_name = case["program_name"]
        actual = sum(1 for m in metadatas if m.get("program_name") == program_name)
        expected_min = case.get("expected_min", 1)
        result["actual_value"] = actual
        result["program_name"] = program_name
        result["expected_min"] = expected_min
        if actual < expected_min:
            result["status"] = "FAIL"
            result["failures"].append(
                f"program_name={program_name!r}: {actual} chunks < expected_min {expected_min}"
            )

    # ── distinct_program_count ────────────────────────────────────────────
    elif check_type == "distinct_program_count":
        distinct = {m["program_name"] for m in metadatas
                    if m.get("program_name", "").strip()}
        actual = len(distinct)
        expected_min = case.get("expected_min", 1)
        result["actual_value"] = actual
        result["actual_programs"] = sorted(distinct)
        result["expected_min"] = expected_min
        if actual < expected_min:
            result["status"] = "FAIL"
            result["failures"].append(
                f"only {actual} distinct program names, expected >= {expected_min}"
            )

    # ── metadata_completeness ─────────────────────────────────────────────
    elif check_type == "metadata_completeness":
        field = case["field"]
        missing = [i for i, m in enumerate(metadatas) if not m.get(field, "").strip()
                   if isinstance(m.get(field, ""), str)]
        # Handle non-string fields (e.g. workflow_priority is int)
        if field == "workflow_priority":
            missing = [i for i, m in enumerate(metadatas)
                       if m.get(field) is None]
        else:
            missing = [i for i, m in enumerate(metadatas)
                       if not str(m.get(field, "")).strip()]
        missing_count = len(missing)
        result["actual_value"] = total - missing_count
        result["missing_count"] = missing_count
        result["field"] = field
        if missing_count > 0:
            result["status"] = "FAIL"
            result["failures"].append(
                f"field={field!r}: {missing_count}/{total} chunks have empty value"
            )

    # ── no_empty_chunks ───────────────────────────────────────────────────
    elif check_type == "no_empty_chunks":
        empty_count = sum(1 for d in documents if not d.strip())
        result["actual_value"] = empty_count
        result["empty_count"] = empty_count
        if empty_count > 0:
            result["status"] = "FAIL"
            result["failures"].append(f"{empty_count} chunks have empty page_content")

    # ── max_chunk_size ────────────────────────────────────────────────────
    elif check_type == "max_chunk_size":
        expected_max = case.get("expected_max_chars", 500)
        violations = [len(d) for d in documents if len(d) > expected_max]
        violation_count = len(violations)
        max_seen = max((len(d) for d in documents), default=0)
        result["actual_value"] = max_seen
        result["violation_count"] = violation_count
        result["expected_max_chars"] = expected_max
        if violation_count > 0:
            result["status"] = "FAIL"
            result["failures"].append(
                f"{violation_count} chunk(s) exceed {expected_max} chars; max seen={max_seen}"
            )

    # ── url_chunk_count ───────────────────────────────────────────────────
    elif check_type == "url_chunk_count":
        url = case["url"]
        actual = sum(1 for m in metadatas if m.get("url") == url)
        expected_min = case.get("expected_min", 1)
        expected_max = case.get("expected_max", float("inf"))
        result["actual_value"] = actual
        result["url"] = url
        result["expected_min"] = expected_min
        result["expected_max"] = expected_max
        if not (expected_min <= actual <= expected_max):
            result["status"] = "FAIL"
            result["failures"].append(
                f"url={url!r}: {actual} chunks not in [{expected_min}, {expected_max}]"
            )

    # ── chunk_id_count ────────────────────────────────────────────────────
    elif check_type == "chunk_id_count":
        chunk_id = case["chunk_id"]
        actual = sum(1 for m in metadatas if m.get("chunk_id") == chunk_id)
        expected_count = case["expected_count"]
        result["actual_value"] = actual
        result["chunk_id"] = chunk_id
        result["expected_count"] = expected_count
        if actual != expected_count:
            result["status"] = "FAIL"
            result["failures"].append(
                f"chunk_id={chunk_id!r}: found {actual}, expected {expected_count}"
            )

    else:
        result["status"] = "FAIL"
        result["failures"].append(f"unknown check_type: {check_type!r}")

    error_category, error_reason = classify_ingestion(case, result)
    result["error_category"] = error_category
    result["error_reason"]   = error_reason

    return result


# ---------------------------------------------------------------------------
# Dataset loading / validation
# ---------------------------------------------------------------------------

def _load_dataset(path: Path) -> dict:
    if not path.exists():
        print(f"[run_ingestion_evals] ERROR: dataset not found: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in dataset]
    if missing:
        print(f"[run_ingestion_evals] ERROR: dataset missing top-level keys: {missing}", file=sys.stderr)
        sys.exit(1)
    if not dataset.get("cases"):
        print(f"[run_ingestion_evals] ERROR: no cases found in {path}", file=sys.stderr)
        sys.exit(1)
    return dataset


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(
    results: list[dict],
    dataset_path: Path,
    dataset: dict,
    store_chunk_count: int,
    execution_time_ms: float,
) -> dict:
    return {
        "schema_version":   "1.0",
        "run_id":           str(uuid.uuid4()),
        "timestamp":        (datetime.now(timezone.utc)
                             .isoformat(timespec="seconds")
                             .replace("+00:00", "Z")),
        "dataset_path":     str(dataset_path),
        "dataset_schema_version": dataset.get("_schema_version"),
        "store_chunk_count": store_chunk_count,
        "summary": {
            "total_cases":       len(results),
            "passed":            sum(1 for r in results if r["status"] == "PASS"),
            "failed":            sum(1 for r in results if r["status"] == "FAIL"),
            "skipped":           0,
            "execution_time_ms": execution_time_ms,
        },
        "cases":          results,
        "metrics":        compute_ingestion_metrics(results),
        "error_summary":  build_error_summary(results),
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_ingestion_eval_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"ingestion_eval_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def _print_header(n: int, store_chunk_count: int) -> None:
    print("=" * 56)
    print("Ingestion Evaluation")
    print("=" * 56)
    print()
    print(f"Store: {store_chunk_count} total chunks")
    print(f"Running {n} inspection cases...")
    print()


def _print_case_live(result: dict, verbose: bool) -> None:
    label = result["status"]
    av    = result.get("actual_value")
    av_str = f"actual={av}" if av is not None else ""
    print(f"{label:<6} {result['case_id']:<12} [{result['check_type']}] {av_str}")
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
        prog="run_ingestion_evals",
        description="Phase 9A ingestion evaluation runner — CSULB Grad Center AI Assistant",
    )
    p.add_argument(
        "--dataset", default=str(_DEFAULT_DATASET),
        help="Path to the ingestion eval dataset",
    )
    p.add_argument(
        "--no-archive", action="store_true",
        help="Write only latest_ingestion_eval_report.json, skip timestamped archive",
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

    store = load_vector_store()
    if store is None:
        print(
            "[run_ingestion_evals] ERROR: vector store not found at chroma_db/. "
            "Run rag/store.py first to build the store before running ingestion evals.",
            file=sys.stderr,
        )
        sys.exit(1)

    collection = store._collection
    store_chunk_count = collection.count()

    # Reset cache for a clean run
    global _CACHED_METADATAS, _CACHED_DOCUMENTS
    _CACHED_METADATAS = None
    _CACHED_DOCUMENTS = None

    dataset_path = Path(args.dataset)
    dataset      = _load_dataset(dataset_path)
    cases        = dataset["cases"]

    _print_header(len(cases), store_chunk_count)

    t0 = time.perf_counter()
    results: list[dict] = []
    for case in cases:
        result = _run_case(case, collection)
        results.append(result)
        _print_case_live(result, verbose=args.verbose)
    execution_time_ms = round((time.perf_counter() - t0) * 1000, 1)

    report = _build_report(results, dataset_path, dataset, store_chunk_count, execution_time_ms)
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
