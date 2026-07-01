"""
evals/metrics_ingestion.py
Phase 9A — deterministic metrics over an ingestion evaluation run.

Pure post-processing over per-case results produced by run_ingestion_evals.py.
No LLM, no semantic similarity, no embedding comparison — every metric is a
count or ratio over facts the runner already established.
"""
from __future__ import annotations


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def compute_ingestion_metrics(cases: list[dict]) -> dict:
    """
    Compute the Phase 9A metric set from a list of run_ingestion_evals.py
    case results.
    """
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "PASS")
    failed = sum(1 for c in cases if c["status"] == "FAIL")

    # ── Page Coverage ─────────────────────────────────────────────────────
    page_type_cases = [c for c in cases if c["check_type"] == "page_type_chunk_count"]
    page_type_passed = sum(1 for c in page_type_cases if c["status"] == "PASS")

    # ── Program Coverage ───────────────────────────────────────────────────
    program_cases = [c for c in cases if c["check_type"] == "program_chunk_count"]
    program_passed = sum(1 for c in program_cases if c["status"] == "PASS")

    # ── Metadata Completeness ─────────────────────────────────────────────
    metadata_cases = [c for c in cases if c["check_type"] == "metadata_completeness"]
    metadata_passed = sum(1 for c in metadata_cases if c["status"] == "PASS")

    # ── Chunk Quality ─────────────────────────────────────────────────────
    quality_types = {"no_empty_chunks", "max_chunk_size"}
    quality_cases = [c for c in cases if c["check_type"] in quality_types]
    quality_passed = sum(1 for c in quality_cases if c["status"] == "PASS")

    # ── URL Coverage ─────────────────────────────────────────────────────
    url_cases = [c for c in cases if c["check_type"] == "url_chunk_count"]
    url_passed = sum(1 for c in url_cases if c["status"] == "PASS")

    # ── Volume / Size ─────────────────────────────────────────────────────
    volume_types = {"total_chunk_count", "distinct_program_count"}
    volume_cases = [c for c in cases if c["check_type"] in volume_types]
    volume_passed = sum(1 for c in volume_cases if c["status"] == "PASS")

    # ── Known Duplicate Tracking ───────────────────────────────────────────
    dup_cases = [c for c in cases if c["check_type"] == "chunk_id_count"]
    dup_passed = sum(1 for c in dup_cases if c["status"] == "PASS")

    return {
        "overall_counts": {"total_cases": total, "pass": passed, "fail": failed},
        "overall_pass_rate":           _pct(passed, total),
        "page_coverage_rate":          _pct(page_type_passed, len(page_type_cases)),
        "program_coverage_rate":       _pct(program_passed, len(program_cases)),
        "metadata_completeness_rate":  _pct(metadata_passed, len(metadata_cases)),
        "chunk_quality_rate":          _pct(quality_passed, len(quality_cases)),
        "url_coverage_rate":           _pct(url_passed, len(url_cases)),
        "volume_sanity_rate":          _pct(volume_passed, len(volume_cases)),
        "duplicate_tracking_rate":     _pct(dup_passed, len(dup_cases)),
    }


def format_console_summary(metrics: dict, execution_time_ms: float) -> str:
    """Render the Phase 9A metrics as a readable console block."""
    width = 50
    lines: list[str] = []
    lines.append("=" * width)
    lines.append("Ingestion Evaluation Summary")
    lines.append("=" * width)
    lines.append("")

    oc = metrics["overall_counts"]
    lines.append("Cases")
    lines.append(f"  Total: {oc['total_cases']}  Pass: {oc['pass']}  Fail: {oc['fail']}")
    lines.append(f"  Overall Pass Rate: {metrics['overall_pass_rate']}%")
    lines.append("")

    lines.append("Knowledge Base Structure")
    lines.append(f"  Page Coverage Rate:       {metrics['page_coverage_rate']}%")
    lines.append(f"  Program Coverage Rate:    {metrics['program_coverage_rate']}%")
    lines.append(f"  URL Coverage Rate:        {metrics['url_coverage_rate']}%")
    lines.append(f"  Volume Sanity Rate:       {metrics['volume_sanity_rate']}%")
    lines.append("")

    lines.append("Quality")
    lines.append(f"  Metadata Completeness:    {metrics['metadata_completeness_rate']}%")
    lines.append(f"  Chunk Quality Rate:       {metrics['chunk_quality_rate']}%")
    lines.append(f"  Duplicate Tracking Rate:  {metrics['duplicate_tracking_rate']}%")
    lines.append("")

    lines.append(f"Execution Time: {execution_time_ms} ms")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)
