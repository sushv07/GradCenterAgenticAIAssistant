"""
evals/metrics_retrieval.py
Phase 8A — deterministic metrics over a retrieval evaluation run.

Pure post-processing over the per-case results already produced by
run_retrieval_evals.py — mirrors evals/metrics_recommendation.py and
evals/metrics_llm.py's role for their respective runners. No LLM, no
semantic similarity, no embedding comparison for evaluation itself — every
metric here is a count/ratio over facts the runner already established
(did an expected source appear, did a forbidden source appear, were there
duplicate chunk_ids, what was the top score).
"""
from __future__ import annotations


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def compute_retrieval_metrics(cases: list[dict]) -> dict:
    """Compute the Phase 8A metric set from a list of run_retrieval_evals.py
    case results."""
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "PASS")
    failed = sum(1 for c in cases if c["status"] == "FAIL")

    # Cases that actually assert something about expected sources.
    cases_with_expectations = [c for c in cases if c.get("expected_sources")]
    n_expect = len(cases_with_expectations)

    top1_hits = sum(1 for c in cases_with_expectations if c.get("top1_match"))
    topk_hits = sum(1 for c in cases_with_expectations if c.get("topk_match"))

    # Expected-source recall at the level of individual source specs, not
    # cases — a case can list more than one expected source.
    all_specs = [spec for c in cases_with_expectations for spec in c.get("expected_source_results", [])]
    specs_found = sum(1 for s in all_specs if s["found"])

    forbidden_violations = sum(1 for c in cases if c.get("forbidden_found"))

    expect_empty_cases = [c for c in cases if c.get("expect_empty")]
    unexpected_retrieval = sum(1 for c in expect_empty_cases if not c["actual"]["is_empty"])

    no_result_cases = sum(1 for c in cases if c["actual"]["is_empty"])

    non_empty_cases = [c for c in cases if not c["actual"]["is_empty"]]
    avg_top_score = (
        round(sum(c["actual"]["top_score"] for c in non_empty_cases) / len(non_empty_cases), 4)
        if non_empty_cases else 0.0
    )
    avg_chunks = round(sum(c["actual"]["num_results"] for c in cases) / total, 2) if total else 0.0

    duplicate_cases = sum(1 for c in cases if c["actual"]["has_duplicates"])

    return {
        "overall_counts": {"total_cases": total, "pass": passed, "fail": failed},
        "top_1_accuracy":          _pct(top1_hits, n_expect),
        "top_k_accuracy":          _pct(topk_hits, n_expect),
        "top_k_recall":            _pct(specs_found, len(all_specs)),
        "expected_source_rate":    _pct(topk_hits, n_expect),
        "forbidden_source_rate":   _pct(forbidden_violations, total),
        "no_result_rate":          _pct(no_result_cases, total),
        "unexpected_retrieval_rate": _pct(unexpected_retrieval, len(expect_empty_cases)),
        "duplicate_chunk_rate":    _pct(duplicate_cases, total),
        "average_retrieval_score": avg_top_score,
        "average_retrieved_chunks": avg_chunks,
    }


def format_console_summary(metrics: dict, execution_time_ms: float) -> str:
    """Render the Phase 8A metrics as a readable console block."""
    width = 50
    lines: list[str] = []
    lines.append("=" * width)
    lines.append("Retrieval Evaluation Summary")
    lines.append("=" * width)
    lines.append("")

    oc = metrics["overall_counts"]
    lines.append("Cases")
    lines.append(f"  Total: {oc['total_cases']}  Pass: {oc['pass']}  Fail: {oc['fail']}")
    lines.append("")

    lines.append("Accuracy")
    lines.append(f"  Top-1 Accuracy: {metrics['top_1_accuracy']}%")
    lines.append(f"  Top-K Accuracy: {metrics['top_k_accuracy']}%")
    lines.append(f"  Top-K Recall: {metrics['top_k_recall']}%")
    lines.append(f"  Expected Source Rate: {metrics['expected_source_rate']}%")
    lines.append("")

    lines.append("Quality Signals")
    lines.append(f"  Forbidden Source Rate: {metrics['forbidden_source_rate']}%")
    lines.append(f"  No Result Rate: {metrics['no_result_rate']}%")
    lines.append(f"  Unexpected Retrieval Rate: {metrics['unexpected_retrieval_rate']}%")
    lines.append(f"  Duplicate Chunk Rate: {metrics['duplicate_chunk_rate']}%")
    lines.append("")

    lines.append("Volume")
    lines.append(f"  Average Retrieval Score: {metrics['average_retrieval_score']}")
    lines.append(f"  Average Retrieved Chunks: {metrics['average_retrieved_chunks']}")
    lines.append("")

    lines.append(f"Execution Time: {execution_time_ms} ms")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)
