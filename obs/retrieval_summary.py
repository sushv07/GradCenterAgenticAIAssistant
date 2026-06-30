"""
obs/retrieval_summary.py
Phase 8B — summarize retrieval observability events from structured logs.

Reads logs/gradcenter.log (NDJSON, one event per line — see
gradcenter_logging.py) and computes aggregate statistics from
retrieval.* events. Pure log-reading: never calls into rag/retriever.py,
never touches the vector store, never affects retrieval in any way.

Distinct from evals/run_retrieval_evals.py (Phase 8A): that runner drives
controlled, known-answer queries through the real retriever and measures
CORRECTNESS against a gold dataset. This module summarizes whatever
retrieval traffic actually happened — real or test — and measures
OPERATIONAL characteristics (latency, candidate volume, filtering rate),
with no notion of "correct" or "incorrect." See ARCHITECTURE_ANALYSIS.md's
Phase 8B section for the full distinction.

Usage:
    from obs.retrieval_summary import summarize_retrieval_events
    summary = summarize_retrieval_events()                  # default log path
    summary = summarize_retrieval_events(Path("some.log"))  # explicit path

    python -m obs.retrieval_summary               # CLI: prints the summary
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.settings import LOG_FILE


def _read_events(log_path: Path, event_names: set[str]) -> list[dict]:
    """Read and parse every line in log_path whose "event" field is in
    event_names. Malformed lines (shouldn't happen — emit() always writes
    valid JSON — but a hand-edited or truncated log file is possible) are
    skipped rather than raising, since this is a read-only reporting tool."""
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


def summarize_retrieval_events(log_path: Optional[Path] = None) -> dict:
    """
    Compute aggregate retrieval-observability statistics from
    retrieval.started/.vector_search/.filtering/.completed/.failed events
    already present in the log file.

    Returns a dict with: total_started, total_completed, total_failed,
    average_latency_ms, average_candidate_count, average_returned_chunks,
    filtering_percentage, empty_retrieval_percentage,
    failure_reason_breakdown.
    """
    log_path = log_path or LOG_FILE

    started_events   = _read_events(log_path, {"retrieval.started"})
    search_events    = _read_events(log_path, {"retrieval.vector_search"})
    filtering_events = _read_events(log_path, {"retrieval.filtering"})
    completed_events = _read_events(log_path, {"retrieval.completed"})
    failed_events     = _read_events(log_path, {"retrieval.failed"})

    total_started   = len(started_events)
    total_completed = len(completed_events)
    total_failed     = len(failed_events)

    average_latency_ms = _avg([e.get("elapsed_ms", 0.0) for e in completed_events])
    average_candidate_count = _avg([e.get("candidate_count", 0) for e in search_events])
    average_returned_chunks = _avg([e.get("returned_count", 0) for e in completed_events])

    total_candidates = sum(e.get("candidate_count", 0) for e in filtering_events)
    total_filtered    = sum(e.get("filtered_count", 0) for e in filtering_events)
    filtering_percentage = _pct(total_filtered, total_candidates)

    empty_count = sum(1 for e in completed_events if e.get("returned_count", 0) == 0)
    empty_retrieval_percentage = _pct(empty_count, total_completed)

    failure_reason_breakdown: dict[str, int] = {}
    for e in failed_events:
        reason = e.get("reason", "unknown")
        failure_reason_breakdown[reason] = failure_reason_breakdown.get(reason, 0) + 1

    return {
        "log_path":                str(log_path),
        "total_started":           total_started,
        "total_completed":         total_completed,
        "total_failed":            total_failed,
        "average_latency_ms":      average_latency_ms,
        "average_candidate_count": average_candidate_count,
        "average_returned_chunks": average_returned_chunks,
        "filtering_percentage":    filtering_percentage,
        "empty_retrieval_percentage": empty_retrieval_percentage,
        "failure_reason_breakdown": failure_reason_breakdown,
    }


def format_console_summary(summary: dict) -> str:
    width = 50
    lines = ["=" * width, "Retrieval Observability Summary", "=" * width, ""]
    lines.append(f"Log: {summary['log_path']}")
    lines.append("")
    lines.append(f"Started:   {summary['total_started']}")
    lines.append(f"Completed: {summary['total_completed']}")
    lines.append(f"Failed:    {summary['total_failed']}")
    lines.append("")
    lines.append(f"Average Latency:          {summary['average_latency_ms']} ms")
    lines.append(f"Average Candidate Count:  {summary['average_candidate_count']}")
    lines.append(f"Average Returned Chunks:  {summary['average_returned_chunks']}")
    lines.append(f"Filtering Percentage:     {summary['filtering_percentage']}%")
    lines.append(f"Empty Retrieval Percentage: {summary['empty_retrieval_percentage']}%")
    if summary["failure_reason_breakdown"]:
        lines.append("")
        lines.append("Failure Reasons:")
        for reason, count in summary["failure_reason_breakdown"].items():
            lines.append(f"  {reason}: {count}")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_console_summary(summarize_retrieval_events()))
