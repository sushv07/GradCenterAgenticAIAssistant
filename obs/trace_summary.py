"""
obs/trace_summary.py
Phase 8E — summarize reconstructed request traces.

Pure aggregation over obs.request_trace.reconstruct_traces()'s output —
never re-reads the log file itself, never touches routing/retrieval/
recommendation/LLM code. Mirrors obs/retrieval_summary.py's role from
Phase 8B: a CLI-friendly report over already-reconstructed structured
data, kept deliberately simple (counts, rates, averages, a slowest-N list)
rather than a dashboard.

Usage:
    from obs.trace_summary import summarize_traces
    summary = summarize_traces()                  # default log path
    summary = summarize_traces(Path("some.log"))  # explicit path

    python -m obs.trace_summary               # CLI: prints the summary
    python -m obs.trace_summary --slowest 10
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from obs.request_trace import reconstruct_traces, RequestTrace


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def summarize_traces(log_path: Optional[Path] = None, slowest_n: int = 5) -> dict:
    """
    Compute aggregate statistics over every reconstructed trace:
    counts, stage-coverage rates, average/total elapsed time, the N
    slowest traces, error/fallback rates, and how many raw log events were
    emitted with no request_id at all (a trace-coverage gap, not a trace
    itself — see missing_request_id_event_count).
    """
    traces = reconstruct_traces(log_path, include_empty_request_id=False)
    total = len(traces)

    with_retrieval      = sum(1 for t in traces if t.retrieval_summary.get("ran"))
    with_recommendation = sum(1 for t in traces if t.recommendation_summary.get("ran"))
    with_llm            = sum(1 for t in traces if t.llm_summary.get("synthesis_ran") or t.llm_summary.get("explanation_ran"))
    with_errors          = sum(1 for t in traces if t.errors)
    with_fallbacks        = sum(1 for t in traces if t.fallbacks)

    elapsed_values = [t.total_elapsed_ms for t in traces if t.total_elapsed_ms is not None]

    slowest = sorted(
        (t for t in traces if t.total_elapsed_ms is not None),
        key=lambda t: t.total_elapsed_ms, reverse=True,
    )[:slowest_n]

    no_id_traces = reconstruct_traces(log_path, include_empty_request_id=True)
    missing_request_id_event_count = sum(
        t.event_count for t in no_id_traces if t.request_id == ""
    )

    return {
        "total_traces":               total,
        "traces_with_retrieval":      with_retrieval,
        "traces_with_recommendation": with_recommendation,
        "traces_with_llm":            with_llm,
        "traces_with_errors":         with_errors,
        "traces_with_fallbacks":      with_fallbacks,
        "retrieval_rate":             _pct(with_retrieval, total),
        "recommendation_rate":        _pct(with_recommendation, total),
        "llm_rate":                   _pct(with_llm, total),
        "error_rate":                 _pct(with_errors, total),
        "fallback_rate":              _pct(with_fallbacks, total),
        "average_total_elapsed_ms":   _avg(elapsed_values),
        "slowest_traces": [
            {
                "request_id": t.request_id,
                "route":      t.route,
                "query":      t.query[:80],
                "elapsed_ms": t.total_elapsed_ms,
            }
            for t in slowest
        ],
        "missing_request_id_event_count": missing_request_id_event_count,
    }


def format_console_summary(summary: dict) -> str:
    width = 56
    lines = ["=" * width, "Request Trace Summary", "=" * width, ""]
    lines.append(f"Total Traces: {summary['total_traces']}")
    lines.append("")
    lines.append(f"With Retrieval:      {summary['traces_with_retrieval']}  ({summary['retrieval_rate']}%)")
    lines.append(f"With Recommendation: {summary['traces_with_recommendation']}  ({summary['recommendation_rate']}%)")
    lines.append(f"With LLM:            {summary['traces_with_llm']}  ({summary['llm_rate']}%)")
    lines.append(f"With Errors:          {summary['traces_with_errors']}  ({summary['error_rate']}%)")
    lines.append(f"With Fallbacks:        {summary['traces_with_fallbacks']}  ({summary['fallback_rate']}%)")
    lines.append("")
    lines.append(f"Average Total Elapsed: {summary['average_total_elapsed_ms']} ms")
    lines.append("")
    if summary["slowest_traces"]:
        lines.append("Slowest Traces:")
        for t in summary["slowest_traces"]:
            lines.append(f"  {t['elapsed_ms']:>10} ms  [{t['route']}]  {t['request_id'][:8]}  {t['query']}")
        lines.append("")
    lines.append(f"Events With No request_id: {summary['missing_request_id_event_count']}")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="trace_summary",
        description="Phase 8E request trace summary — CSULB Grad Center AI Assistant",
    )
    p.add_argument("--slowest", type=int, default=5, help="Number of slowest traces to list")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    print(format_console_summary(summarize_traces(slowest_n=args.slowest)))
