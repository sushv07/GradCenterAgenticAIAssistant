"""
experiments/rag_vs_finetuning/evaluation/report.py
Track A baseline report: metrics + failure analysis + retrieval diagnostics
(Phase P7.2).

Consumes the frozen dataset + persisted official responses and produces the
official Track A baseline. Uses the existing (unmodified) evaluation runner for
metrics. Deterministic given fixed inputs; no LLM scoring.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.execute import (
    OfficialResponse, to_response_record,
)
from experiments.rag_vs_finetuning.evaluation.metrics import abstained, score_case
from experiments.rag_vs_finetuning.evaluation.models import EvalDataset
from experiments.rag_vs_finetuning.evaluation.runner import run_evaluation

REPORT_JSON = Path(
    "experiments/rag_vs_finetuning/data/evaluation/reports/track_a_baseline.json")
REPORT_MD = Path(
    "experiments/rag_vs_finetuning/data/evaluation/reports/track_a_baseline.md")


def _per_program(dataset: EvalDataset, by_q) -> dict:
    out = defaultdict(lambda: {"count": 0, "responded": 0, "correct": 0})
    for case in dataset.cases:
        resp = by_q.get(case.question)
        r = score_case(case, to_response_record(resp) if resp else None)
        p = out[case.program]
        p["count"] += 1
        if r.responded:
            p["responded"] += 1
            if r.answer_correct:
                p["correct"] += 1
    return {k: {**v, "accuracy": round(v["correct"] / v["responded"], 4) if v["responded"] else None}
            for k, v in sorted(out.items())}


def _failure_analysis(dataset: EvalDataset, by_q) -> dict:
    buckets = defaultdict(list)
    for case in dataset.cases:
        resp = by_q.get(case.question)
        if resp is None:
            buckets["generation_failure"].append(case.id)
            continue
        rr = to_response_record(resp)
        r = score_case(case, rr)
        if not rr.answer.strip():
            buckets["generation_failure"].append(case.id)
        if case.answerable:
            if not r.answer_correct and not r.abstained:
                buckets["incorrect_answer"].append(case.id)
            if r.abstained:
                buckets["abstention_error"].append(case.id)  # should have answered
            if r.retrieval_recall is not None and r.retrieval_recall < 1.0:
                buckets["retrieval_failure"].append(case.id)
            if r.citation_recall is not None and r.citation_recall < 1.0:
                buckets["missing_citation"].append(case.id)
            if r.citation_precision is not None and r.citation_precision < 1.0:
                buckets["incorrect_citation"].append(case.id)
        else:
            if r.hallucinated:
                buckets["hallucination"].append(case.id)
                buckets["abstention_error"].append(case.id)  # failed to abstain
    counts = {k: len(v) for k, v in sorted(buckets.items())}
    examples = {k: v[:3] for k, v in sorted(buckets.items())}
    by_category = defaultdict(Counter)
    cat_of = {c.id: c.category for c in dataset.cases}
    for k, ids in buckets.items():
        for cid in ids:
            by_category[k][cat_of[cid]] += 1
    return {"counts": counts, "examples": examples,
            "by_category": {k: dict(v) for k, v in by_category.items()}}


def _retrieval_diagnostics(dataset: EvalDataset, responses: list[OfficialResponse]) -> dict:
    all_retrieved = [cid for r in responses for cid in r.retrieved_chunk_ids]
    all_sims = [s for r in responses for s in r.similarity_scores]
    freq = Counter(all_retrieved)
    # universe of chunk ids appears in retrieval; "never retrieved" needs the full set
    from experiments.rag_vs_finetuning.evaluation.dataset import load_chunk_ids
    universe = load_chunk_ids(Path.cwd() / "experiments/rag_vs_finetuning/data/chunks/chunks.jsonl")
    never = sorted(universe - set(freq))
    no_chunk_qs = [r.question_id for r in responses if not r.retrieved_chunk_ids]
    return {
        "avg_retrieved_chunks": round(len(all_retrieved) / len(responses), 3) if responses else 0,
        "avg_similarity": round(sum(all_sims) / len(all_sims), 4) if all_sims else None,
        "most_frequently_retrieved": freq.most_common(5),
        "never_retrieved_count": len(never),
        "never_retrieved": never[:10],
        "questions_with_no_chunks": no_chunk_qs,
    }


def build_baseline_report(dataset: EvalDataset, responses: list[OfficialResponse]) -> dict:
    by_q = {r.question: r for r in responses}
    report = run_evaluation(dataset, [to_response_record(r) for r in responses], track="track_a_pure_rag")
    return {
        "track": "track_a_pure_rag",
        "dataset_version": dataset.dataset_version,
        "dataset_checksum": dataset.dataset_checksum,
        "case_count": len(dataset.cases),
        "responded_count": report.responded_count,
        "config": {
            "model": responses[0].model if responses else None,
            "embedding_model": responses[0].versions.get("embedding_model") if responses else None,
            "vector_store": "chroma / masters_track_a_v1 (cosine)",
            "prompt_version": responses[0].prompt_version if responses else None,
            "retrieval_version": responses[0].versions.get("retrieval_version") if responses else None,
        },
        "overall_metrics": report.metrics,
        "metrics_by_category": report.metrics_by_category,
        "metrics_by_program": _per_program(dataset, by_q),
        "retrieval_diagnostics": _retrieval_diagnostics(dataset, responses),
        "failure_analysis": _failure_analysis(dataset, by_q),
        "limitations": [
            "Single greedy run (temperature 0); Ollama decoding is not guaranteed "
            "bit-identical across versions.",
            "Answer scoring is deterministic substring/set matching, not an LLM judge.",
            "Baseline reflects the frozen retrieval/prompt/model; no tuning applied.",
        ],
    }


def render_markdown(report: dict) -> str:
    m = report["overall_metrics"]
    lines = ["# Track A — Pure RAG Baseline Report", "",
             f"- dataset: {report['dataset_version']} ({report['case_count']} cases), "
             f"checksum `{report['dataset_checksum'][:20]}…`",
             f"- model: `{report['config']['model']}` · embedding: "
             f"`{report['config']['embedding_model']}` · prompt: "
             f"`{report['config']['prompt_version']}`",
             f"- vector store: {report['config']['vector_store']}", "",
             "## Overall metrics", ""]
    for k, v in m.items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Metrics by category", ""]
    for cat, cm in report["metrics_by_category"].items():
        lines.append(f"- {cat}: accuracy={cm['accuracy']} (n={cm['count']})")
    lines += ["", "## Failure analysis (counts)", ""]
    for k, v in report["failure_analysis"]["counts"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Retrieval diagnostics", ""]
    rd = report["retrieval_diagnostics"]
    lines.append(f"- avg retrieved chunks: {rd['avg_retrieved_chunks']} · avg similarity: {rd['avg_similarity']}")
    lines.append(f"- never-retrieved chunks: {rd['never_retrieved_count']}")
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
    return "\n".join(lines) + "\n"


def persist_report(report: dict) -> None:
    import json
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    REPORT_MD.write_text(render_markdown(report), "utf-8")
