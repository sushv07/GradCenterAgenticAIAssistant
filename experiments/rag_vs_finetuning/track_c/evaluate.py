"""
experiments/rag_vs_finetuning/track_c/evaluate.py
Official Track C evaluation report (Phase P11).

Scores the frozen Track C hybrid responses with the EXISTING, UNMODIFIED
evaluation pipeline (runner.run_evaluation + metrics.score_case) and the identical
derived-metric helpers used for Track B, so all three tracks share one code path.
Because Track C populates retrieved_chunk_ids and citation_chunk_ids, the citation
and retrieval metrics are computed here too (they were N/A for Track B). No metric
is changed. Runs under any interpreter (no MLX import).

  python3 -m experiments.rag_vs_finetuning.track_c.evaluate
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.dataset import load_dataset
from experiments.rag_vs_finetuning.evaluation.models import EvalDataset, ResponseRecord
from experiments.rag_vs_finetuning.evaluation.runner import run_evaluation
# Reuse the exact P8.2 helpers so Track C is scored identically to Track B.
from experiments.rag_vs_finetuning.track_b.evaluate import (
    _category_extremes, _derived_metrics, _failure_analysis, _percentile,
    _representatives,
)

RESULTS = Path(
    "experiments/rag_vs_finetuning/data/evaluation/results/track_c_responses.jsonl")
REPORT_JSON = Path(
    "experiments/rag_vs_finetuning/data/evaluation/reports/track_c_evaluation.json")
REPORT_MD = Path(
    "experiments/rag_vs_finetuning/data/evaluation/reports/track_c_evaluation.md")
TRACK = "track_c_hybrid"


def load_responses(path: Path = RESULTS) -> list[dict]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def to_response_record(r: dict) -> ResponseRecord:
    return ResponseRecord(
        question=r["question"], answer=r["answer"],
        insufficient_evidence=r["insufficient_evidence"],
        citation_chunk_ids=r["citation_chunk_ids"],
        retrieved_chunk_ids=r["retrieved_chunk_ids"],
        retrieval_latency_ms=r["retrieval_latency_ms"],
        generation_latency_ms=r["generation_latency_ms"],
        answer_char_count=r["answer_char_count"], track=TRACK)


def _operational(responses: list[dict]) -> dict:
    gen = [r["generation_latency_ms"] for r in responses]
    e2e = [r["retrieval_latency_ms"] + r["generation_latency_ms"] for r in responses]
    ret = [r["retrieval_latency_ms"] for r in responses]
    return {
        "avg_latency_ms": round(sum(e2e) / len(e2e), 3) if e2e else None,
        "p50_latency_ms": _percentile(e2e, 0.50),
        "p95_latency_ms": _percentile(e2e, 0.95),
        "avg_generation_latency_ms": round(sum(gen) / len(gen), 3) if gen else None,
        "avg_retrieval_latency_ms": round(sum(ret) / len(ret), 3) if ret else None,
        "max_latency_ms": round(max(e2e), 3) if e2e else None,
    }


def build_report(dataset: EvalDataset, responses: list[dict]) -> dict:
    records = [to_response_record(r) for r in responses]
    by_q = {r.question.strip(): r for r in records}
    resp_by_q = {r["question"].strip(): r for r in responses}
    report = run_evaluation(dataset, records, track=TRACK)

    m = dict(report.metrics)
    m.update(_derived_metrics(dataset, by_q))
    v0 = responses[0]["versions"] if responses else {}
    model_calls = sum(1 for r in responses if r.get("model_called"))
    return {
        "track": TRACK,
        "condition": "hybrid — retrieval grounding + Track B LoRA adapter",
        "dataset_version": dataset.dataset_version,
        "dataset_checksum": dataset.dataset_checksum,
        "case_count": len(dataset.cases),
        "responded_count": report.responded_count,
        "config": {
            "base_model": v0.get("base_model"),
            "adapter_checksum": v0.get("adapter_checksum"),
            "prompt_version": v0.get("prompt_version"),
            "retrieval_version": v0.get("retrieval_version"),
            "embedding_model": v0.get("embedding_model"),
            "vector_store": "chroma / masters_track_a_v1 (cosine, top_k=4, thr=0.0)",
            "decoding": v0.get("decoding"), "max_tokens": v0.get("max_tokens"),
            "seed": v0.get("seed"),
            "model_invocations": f"{model_calls}/{len(responses)} "
                                 "(rest refused on empty retrieval)",
        },
        "evaluation_timestamp": responses[0]["timestamp"] if responses else None,
        "primary_metrics": {
            "answer_accuracy": m["answer_accuracy"],
            "completeness": m["completeness"],
            "hallucination_rate": m["hallucination_rate"],
            "unsupported_claim_rate": m["unsupported_claim_rate"],
            "refusal_rate": m["refusal_rate"],
            "abstention_accuracy": m["abstention_accuracy"],
        },
        "groundedness_and_citations": {
            "citation_precision": m["citation_precision"],
            "citation_recall": m["citation_recall"],
            "retrieval_recall_at_k": m["retrieval_recall_at_k"],
            "retrieval_precision_at_k": m["retrieval_precision_at_k"],
        },
        "operational_metrics": _operational(responses),
        "overall_metrics": m,
        "metrics_by_category": report.metrics_by_category,
        "category_extremes": _category_extremes(report.metrics_by_category),
        "failure_analysis": _failure_analysis(dataset, by_q),
        "representatives": _representatives(dataset, by_q, resp_by_q),
        "limitations": [
            "Reuses the P8.1 Track B adapter, which was fine-tuned WITHOUT retrieved "
            "context and overfit on 121 examples; grounded context is supplied but the "
            "adapter still tends to degenerate.",
            "Retrieval is the frozen Track A stack (top_k=4, threshold=0.0), so answer "
            "quality is bounded by its recall (same retrieval as Track A).",
            "Deterministic substring/set scoring, not an LLM judge.",
            "MLX greedy decoding is deterministic for a fixed version/hardware.",
        ],
    }


def render_markdown(report: dict) -> str:
    pm, gc = report["primary_metrics"], report["groundedness_and_citations"]
    op, ce, c = report["operational_metrics"], report["category_extremes"], report["config"]
    L = ["# Track C — Hybrid (RAG + Fine-Tuned) Evaluation Report", "",
         "## Executive summary", "",
         f"- condition: **{report['condition']}**",
         f"- base `{c['base_model']}` + adapter `{(c['adapter_checksum'] or '')[:23]}…`; "
         f"retrieval `{c['vector_store']}`",
         f"- benchmark: {report['dataset_version']} ({report['case_count']} cases), "
         f"checksum `{report['dataset_checksum'][:20]}…`",
         f"- decoding: {c['decoding']}, max_tokens={c['max_tokens']}, seed={c['seed']}; "
         f"model invocations: {c['model_invocations']}",
         f"- responded: {report['responded_count']}/{report['case_count']}", "",
         "## Metric table", "", "| metric | value |", "| --- | --- |"]
    for k, v in pm.items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Groundedness & citations", "", "| metric | value |", "| --- | --- |"]
    for k, v in gc.items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Operational metrics", "",
          f"- end-to-end avg {op['avg_latency_ms']} ms · P50 {op['p50_latency_ms']} ms · "
          f"P95 {op['p95_latency_ms']} ms",
          f"- avg generation {op['avg_generation_latency_ms']} ms · avg retrieval "
          f"{op['avg_retrieval_latency_ms']} ms", "",
          "## Category results", ""]
    for cat, cm in report["metrics_by_category"].items():
        L.append(f"- {cat}: accuracy={cm['accuracy']} (responded {cm['responded']}/{cm['count']})")
    L += ["",
          f"- strongest: {', '.join(ce.get('strongest', [])) or 'n/a'} (acc={ce.get('strongest_accuracy')})",
          f"- weakest: {', '.join(ce.get('weakest', [])) or 'n/a'} (acc={ce.get('weakest_accuracy')})",
          "", "## Error analysis (counts)", ""]
    for k, v in report["failure_analysis"]["counts"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## Representative successes", ""]
    for s in report["representatives"]["successes"]:
        L.append(f"- {s['id']} ({s['category']}): expected `{s['expected_answer']}` · {s['answer'][:150]}")
    if not report["representatives"]["successes"]:
        L.append("- (none)")
    L += ["", "## Representative failures", ""]
    for f in report["representatives"]["failures"]:
        L.append(f"- {f['id']} ({f['category']}, {f['failure_mode']}): {f['answer'][:150]}")
    L += ["", "## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
    return "\n".join(L) + "\n"


def main() -> None:
    dataset = load_dataset()
    responses = load_responses()
    if not responses:
        raise SystemExit(f"no Track C responses at {RESULTS}; run inference first")
    report = build_report(dataset, responses)
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    REPORT_MD.write_text(render_markdown(report), "utf-8")
    pm = report["primary_metrics"]
    print(f"[track-c] responded {report['responded_count']}/{report['case_count']}")
    print(f"[track-c] answer_accuracy={pm['answer_accuracy']} hallucination_rate={pm['hallucination_rate']} "
          f"refusal_rate={pm['refusal_rate']} citation_recall={report['groundedness_and_citations']['citation_recall']}")
    print(f"[track-c] wrote {REPORT_JSON.name} + {REPORT_MD.name}")


if __name__ == "__main__":
    main()
