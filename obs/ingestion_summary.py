"""
obs/ingestion_summary.py
Phase 9D — summarize ingestion observability events from structured logs.

Reads logs/gradcenter.log (NDJSON — see gradcenter_logging.py) and
computes aggregate statistics from ingestion.* events. Pure log-reading:
never calls into rag/ingestion.py, rag/chunking.py, or rag/store.py, and
never affects the knowledge base in any way.

Distinct from evals/run_ingestion_evals.py (Phase 9A): that runner
inspects the BUILT Chroma store and runs structural assertions ("does faq
have >= 50 chunks?"). This module reads LOG EVENTS emitted during
ingestion runs and measures OPERATIONAL characteristics — how many pages
were attempted, how many succeeded, how long each stage took — with no
notion of "correct" or "incorrect". Same distinction as Phase 8B's
retrieval_summary.py vs. run_retrieval_evals.py.

Distinct from obs/kb_health_report.py (Phase 9B): that module inspects the
current store state. This module reads the historical log of ingestion
runs, potentially spanning multiple rebuilds.

Usage:
    from obs.ingestion_summary import summarize_ingestion_events
    summary = summarize_ingestion_events()            # default log path
    summary = summarize_ingestion_events(Path("x"))   # explicit path

    python -m obs.ingestion_summary
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.settings import LOG_FILE


def _read_events(log_path: Path, event_names: set[str]) -> list[dict]:
    """Read and parse every NDJSON line whose 'event' field is in
    event_names.  Malformed lines are skipped."""
    if not log_path.exists():
        return []
    events: list[dict] = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") in event_names:
                events.append(record)
    return events


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def summarize_ingestion_events(log_path: Optional[Path] = None) -> dict:
    """
    Compute aggregate ingestion-observability statistics from
    ingestion.started/.page_fetched/.page_retry/.page_parsed/
    .page_chunked/.page_failed/.completed events in the log.

    Returns a dict with: runs (started/completed/failed counts),
    page-level stats, stage timing averages, failure breakdowns.
    """
    log_path = log_path or LOG_FILE

    started_events  = _read_events(log_path, {"ingestion.started"})
    fetched_events  = _read_events(log_path, {"ingestion.page_fetched"})
    retry_events    = _read_events(log_path, {"ingestion.page_retry"})
    parsed_events   = _read_events(log_path, {"ingestion.page_parsed"})
    chunked_events  = _read_events(log_path, {"ingestion.page_chunked"})
    failed_events   = _read_events(log_path, {"ingestion.page_failed"})
    completed_events = _read_events(log_path, {"ingestion.completed"})

    # ── Run-level stats ────────────────────────────────────────────────────
    total_runs = len(started_events)
    completed_runs = len(completed_events)
    failed_runs = sum(1 for e in completed_events if e.get("pages_failed", 0) > 0)

    # ── Page-level stats ───────────────────────────────────────────────────
    pages_attempted = sum(e.get("pages_attempted", 0) for e in completed_events)
    pages_succeeded = sum(e.get("pages_succeeded", 0) for e in completed_events)
    pages_failed    = sum(e.get("pages_failed", 0) for e in failed_events)
    total_retries   = len(retry_events)
    total_chunks    = sum(e.get("chunks_generated", 0) for e in chunked_events)
    total_chars     = sum(e.get("total_chars", 0) for e in completed_events)

    # ── Timing averages ────────────────────────────────────────────────────
    avg_fetch_ms   = _avg([e.get("fetch_elapsed_ms", 0.0) for e in fetched_events])
    avg_parse_ms   = _avg([e.get("parse_elapsed_ms", 0.0) for e in parsed_events])
    avg_chunk_ms   = _avg([e.get("chunk_elapsed_ms", 0.0) for e in chunked_events])
    avg_total_ms   = _avg([e.get("elapsed_ms", 0.0) for e in completed_events])
    avg_chunks_per_page = _avg([e.get("chunks_generated", 0) for e in chunked_events])
    avg_chars_per_page  = _avg([e.get("char_count", 0) for e in parsed_events])

    # ── Failure breakdown ──────────────────────────────────────────────────
    failure_reasons: dict[str, int] = {}
    for e in failed_events:
        r = e.get("reason", "unknown")
        failure_reasons[r] = failure_reasons.get(r, 0) + 1

    retry_error_types: dict[str, int] = {}
    for e in retry_events:
        et = e.get("error_type", "unknown")
        retry_error_types[et] = retry_error_types.get(et, 0) + 1

    return {
        "log_path":              str(log_path),
        "total_runs":             total_runs,
        "completed_runs":         completed_runs,
        "failed_runs":             failed_runs,
        "pages_attempted":         pages_attempted,
        "pages_succeeded":         pages_succeeded,
        "pages_failed":            pages_failed,
        "total_retries":           total_retries,
        "total_chunks_generated":  total_chunks,
        "total_chars_ingested":    total_chars,
        "average_fetch_ms":        avg_fetch_ms,
        "average_parse_ms":        avg_parse_ms,
        "average_chunk_ms":        avg_chunk_ms,
        "average_total_run_ms":    avg_total_ms,
        "average_chunks_per_page": avg_chunks_per_page,
        "average_chars_per_page":  avg_chars_per_page,
        "failure_reasons":          failure_reasons,
        "retry_error_types":        retry_error_types,
    }


def format_console_summary(summary: dict) -> str:
    width = 52
    lines = ["=" * width, "Ingestion Observability Summary", "=" * width, ""]
    lines.append(f"Log: {summary['log_path']}")
    lines.append("")

    lines.append("Runs")
    lines.append(f"  Total Started:    {summary['total_runs']}")
    lines.append(f"  Completed:        {summary['completed_runs']}")
    lines.append(f"  With Failures:    {summary['failed_runs']}")
    lines.append("")

    lines.append("Pages")
    lines.append(f"  Attempted:        {summary['pages_attempted']}")
    lines.append(f"  Succeeded:        {summary['pages_succeeded']}")
    lines.append(f"  Failed:           {summary['pages_failed']}")
    lines.append(f"  Retries:          {summary['total_retries']}")
    lines.append("")

    lines.append("Output")
    lines.append(f"  Total Chunks:     {summary['total_chunks_generated']}")
    lines.append(f"  Total Chars:      {summary['total_chars_ingested']:,}")
    lines.append(f"  Avg Chunks/Page:  {summary['average_chunks_per_page']}")
    lines.append(f"  Avg Chars/Page:   {summary['average_chars_per_page']}")
    lines.append("")

    lines.append("Timing (averages)")
    lines.append(f"  Fetch:            {summary['average_fetch_ms']} ms")
    lines.append(f"  Parse:            {summary['average_parse_ms']} ms")
    lines.append(f"  Chunk:            {summary['average_chunk_ms']} ms")
    lines.append(f"  Total Run:        {summary['average_total_run_ms']} ms")

    if summary["failure_reasons"]:
        lines.append("")
        lines.append("Failure Reasons:")
        for reason, count in sorted(summary["failure_reasons"].items(),
                                     key=lambda kv: -kv[1]):
            lines.append(f"  {reason}: {count}")

    if summary["retry_error_types"]:
        lines.append("")
        lines.append("Retry Error Types:")
        for etype, count in sorted(summary["retry_error_types"].items(),
                                    key=lambda kv: -kv[1]):
            lines.append(f"  {etype}: {count}")

    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_console_summary(summarize_ingestion_events()))
