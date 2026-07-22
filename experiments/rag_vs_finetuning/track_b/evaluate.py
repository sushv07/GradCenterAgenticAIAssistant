"""
experiments/rag_vs_finetuning/track_b/evaluate.py
Official Track B evaluation report (Phase P8.2).

Consumes the fine-tuned responses produced by track_b/infer.py and scores them
with the EXISTING, UNMODIFIED frozen evaluation pipeline (runner.run_evaluation +
metrics.score_case). No metric is changed. On top of the standard metrics it
derives the P8.2-requested summaries (refusal rate, unsupported-claim rate,
completeness) and the operational latency percentiles, all computed from the same
per-case results — never by editing the evaluation code. Runs under the repo's
Python 3.13 interpreter (no MLX import here).

  python3 -m experiments.rag_vs_finetuning.track_b.evaluate
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.dataset import load_dataset
from experiments.rag_vs_finetuning.evaluation.metrics import abstained, score_case
from experiments.rag_vs_finetuning.evaluation.models import EvalDataset, ResponseRecord
from experiments.rag_vs_finetuning.evaluation.runner import run_evaluation

RESULTS = Path(
    "experiments/rag_vs_finetuning/data/evaluation/results/track_b_responses.jsonl")
REPORT_JSON = Path(
    "experiments/rag_vs_finetuning/data/evaluation/reports/track_b_evaluation.json")
REPORT_MD = Path(
    "experiments/rag_vs_finetuning/data/evaluation/reports/track_b_evaluation.md")
TRACK = "track_b_finetuned_no_rag"


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


def _percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def _derived_metrics(dataset: EvalDataset, by_q: dict[str, ResponseRecord]) -> dict:
    """P8.2-requested summaries, derived from the frozen per-case scoring."""
    answerable_answered = answerable_complete = 0
    answerable_total = 0
    substantive = unsupported = 0            # non-abstained responses / of those, wrong
    refusals = 0
    for case in dataset.cases:
        rr = by_q.get(case.question.strip())
        if rr is None:
            continue
        res = score_case(case, rr)
        abst = abstained(rr)
        if abst:
            refusals += 1
        else:
            substantive += 1
            if not res.answer_correct:
                unsupported += 1             # asserted something unverified / wrong
        if case.answerable:
            answerable_total += 1
            if not abst:
                answerable_answered += 1
            if res.answer_correct:
                answerable_complete += 1
    responded = sum(1 for c in dataset.cases if by_q.get(c.question.strip()))
    return {
        # fraction of ALL responses that declined to answer
        "refusal_rate": round(refusals / responded, 4) if responded else None,
        # of substantive (non-abstained) answers, fraction not supported by ground truth
        "unsupported_claim_rate": round(unsupported / substantive, 4) if substantive else None,
        # of answerable cases, fraction whose expected fact is present in the answer
        "completeness": round(answerable_complete / answerable_total, 4) if answerable_total else None,
        "answerable_attempted": answerable_answered,
        "answerable_total": answerable_total,
        "substantive_answers": substantive,
        "refusals": refusals,
    }


def _operational(responses: list[dict]) -> dict:
    lat = [r["generation_latency_ms"] for r in responses]
    slow = sorted(((r["generation_latency_ms"], r["question_id"]) for r in responses),
                  reverse=True)[:3]
    return {
        "avg_latency_ms": round(sum(lat) / len(lat), 3) if lat else None,
        "p50_latency_ms": _percentile(lat, 0.50),
        "p95_latency_ms": _percentile(lat, 0.95),
        "min_latency_ms": round(min(lat), 3) if lat else None,
        "max_latency_ms": round(max(lat), 3) if lat else None,
        "slowest_cases": [{"id": cid, "ms": round(ms, 1)} for ms, cid in slow],
        "note": ("On-device MLX generation is normally ~13.5 s/case (P50); a few "
                 "cases stalled to minutes under 16 GB unified-memory pressure "
                 "during sustained 7B decoding, inflating the mean and max. These "
                 "tail stalls are an inference-runtime artifact, not a model-quality "
                 "signal."),
    }


def _failure_analysis(dataset: EvalDataset, by_q: dict[str, ResponseRecord]) -> dict:
    buckets: dict[str, list[str]] = defaultdict(list)
    cat_of = {c.id: c.category for c in dataset.cases}
    for case in dataset.cases:
        rr = by_q.get(case.question.strip())
        if rr is None:
            buckets["generation_failure"].append(case.id)
            continue
        res = score_case(case, rr)
        if not rr.answer.strip():
            buckets["empty_generation"].append(case.id)
        if case.answerable:
            if res.abstained:
                buckets["over_refusal"].append(case.id)          # should have answered
            elif not res.answer_correct:
                buckets["incorrect_answer"].append(case.id)      # answered, wrong/unsupported
        else:
            if res.hallucinated:
                buckets["hallucination"].append(case.id)         # should have refused
    counts = {k: len(v) for k, v in sorted(buckets.items())}
    examples = {k: v[:5] for k, v in sorted(buckets.items())}
    by_category = defaultdict(Counter)
    for k, ids in buckets.items():
        for cid in ids:
            by_category[k][cat_of[cid]] += 1
    return {"counts": counts, "examples": examples,
            "by_category": {k: dict(v) for k, v in by_category.items()}}


def _category_extremes(metrics_by_category: dict) -> dict:
    scored = {c: m["accuracy"] for c, m in metrics_by_category.items()
              if m["accuracy"] is not None}
    if not scored:
        return {"strongest": [], "weakest": []}
    hi = max(scored.values())
    lo = min(scored.values())
    return {
        "strongest": sorted([c for c, a in scored.items() if a == hi]),
        "strongest_accuracy": hi,
        "weakest": sorted([c for c, a in scored.items() if a == lo]),
        "weakest_accuracy": lo,
    }


def _representatives(dataset: EvalDataset, by_q: dict[str, ResponseRecord],
                     resp_by_q: dict[str, dict]) -> dict:
    successes, failures = [], []
    for case in dataset.cases:
        rr = by_q.get(case.question.strip())
        if rr is None:
            continue
        res = score_case(case, rr)
        raw = resp_by_q[case.question.strip()]
        entry = {"id": case.id, "category": case.category, "answerable": case.answerable,
                 "question": case.question, "expected_answer": case.expected_answer,
                 "answer": raw["answer"][:400]}
        if res.answer_correct:
            successes.append(entry)
        else:
            failures.append({**entry,
                             "failure_mode": ("hallucination" if res.hallucinated
                                              else "over_refusal" if res.abstained and case.answerable
                                              else "incorrect_answer")})
    return {"successes": successes[:5], "failures": failures[:6]}


def build_report(dataset: EvalDataset, responses: list[dict]) -> dict:
    records = [to_response_record(r) for r in responses]
    by_q = {r.question.strip(): r for r in records}
    resp_by_q = {r["question"].strip(): r for r in responses}
    report = run_evaluation(dataset, records, track=TRACK)

    m = dict(report.metrics)
    m.update(_derived_metrics(dataset, by_q))
    v0 = responses[0]["versions"] if responses else {}
    return {
        "track": TRACK,
        "condition": "fine-tuned only (LoRA adapter, retrieval disabled)",
        "dataset_version": dataset.dataset_version,
        "dataset_checksum": dataset.dataset_checksum,
        "case_count": len(dataset.cases),
        "responded_count": report.responded_count,
        "config": {
            "base_model": v0.get("base_model"),
            "adapter_checksum": v0.get("adapter_checksum"),
            "prompt_version": v0.get("prompt_version"),
            "decoding": v0.get("decoding"),
            "max_tokens": v0.get("max_tokens"),
            "seed": v0.get("seed"),
            "mlx_lm": v0.get("mlx_lm"),
            "retrieval": "DISABLED (no Chroma / no embeddings)",
        },
        "evaluation_timestamp": responses[0]["timestamp"] if responses else None,
        "primary_metrics": {
            "answer_accuracy": m["answer_accuracy"],
            "hallucination_rate": m["hallucination_rate"],
            "unsupported_claim_rate": m["unsupported_claim_rate"],
            "completeness": m["completeness"],
            "refusal_rate": m["refusal_rate"],
            "abstention_accuracy": m["abstention_accuracy"],
        },
        "operational_metrics": _operational(responses),
        "overall_metrics": m,
        "metrics_by_category": report.metrics_by_category,
        "category_extremes": _category_extremes(report.metrics_by_category),
        "common_failure_modes": [
            "Degenerate repetition — answers loop the same fragment (e.g. 'don have "
            "the provided, don have the provided …') up to the 256-token cap.",
            "Refusal collapse — the model echoes a corrupted paraphrase of its trained "
            "refusal ('I don't have the provided <program> data to answer that') even "
            "for answerable questions, without stating the actual fact.",
            "Fabricated tokens — invented emails/date codes (e.g. 'ced-2011-01-01') and "
            "spurious identifiers appear in place of grounded content.",
            "Over-refusal on answerable cases (9) and failure to cleanly abstain on "
            "source_missing cases (hallucination_rate 1.0) — the trained refusal "
            "behaviour did not generalise.",
        ],
        "failure_analysis": _failure_analysis(dataset, by_q),
        "representatives": _representatives(dataset, by_q, resp_by_q),
        "limitations": [
            "Fine-tuned on 121 tiny SFT examples; the selected iter-40 adapter is "
            "the lowest-validation-loss checkpoint but the model still under-fits QA.",
            "Retrieval is disabled by design — answers rely solely on parametric "
            "(fine-tuned) knowledge, so citation/retrieval metrics are not applicable.",
            "Answer scoring is deterministic substring/set matching, not an LLM judge.",
            "MLX greedy decoding is deterministic for a fixed version/hardware but "
            "not guaranteed bit-identical across MLX versions.",
        ],
    }


def render_markdown(report: dict) -> str:
    pm = report["primary_metrics"]
    op = report["operational_metrics"]
    ce = report["category_extremes"]
    c = report["config"]
    L = ["# Track B — Fine-Tuned (LoRA) Evaluation Report", "",
         "## Executive summary", "",
         f"- condition: **{report['condition']}**",
         f"- base: `{c['base_model']}` + adapter `{(c['adapter_checksum'] or '')[:23]}…`",
         f"- benchmark: {report['dataset_version']} ({report['case_count']} cases), "
         f"checksum `{report['dataset_checksum'][:20]}…`",
         f"- decoding: {c['decoding']}, max_tokens={c['max_tokens']}, seed={c['seed']}; "
         f"retrieval {c['retrieval']}",
         f"- responded: {report['responded_count']}/{report['case_count']}", "",
         "## Metric table", "",
         "| metric | value |", "| --- | --- |"]
    for k, v in pm.items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Operational metrics", "",
          f"- avg latency: {op['avg_latency_ms']} ms · P50: {op['p50_latency_ms']} ms · "
          f"P95: {op['p95_latency_ms']} ms",
          f"- min/max: {op['min_latency_ms']} / {op['max_latency_ms']} ms", "",
          "## Category results", ""]
    for cat, cm in report["metrics_by_category"].items():
        L.append(f"- {cat}: accuracy={cm['accuracy']} (responded {cm['responded']}/{cm['count']})")
    L += ["",
          f"- strongest: {', '.join(ce.get('strongest', [])) or 'n/a'} "
          f"(acc={ce.get('strongest_accuracy')})",
          f"- weakest: {', '.join(ce.get('weakest', [])) or 'n/a'} "
          f"(acc={ce.get('weakest_accuracy')})", "",
          "## Error analysis", "", "Common failure modes:", ""]
    for fm in report["common_failure_modes"]:
        L.append(f"- {fm}")
    L += ["", "Failure counts:", ""]
    for k, v in report["failure_analysis"]["counts"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## Representative successes",
          "(substring matches on otherwise degenerate output — the expected token "
          "appears amid repetition, not a fluent correct answer)", ""]
    for s in report["representatives"]["successes"]:
        L.append(f"- {s['id']} ({s['category']}): Q: {s['question']}")
        L.append(f"  - expected `{s['expected_answer']}` · answer: {s['answer'][:160]}")
    if not report["representatives"]["successes"]:
        L.append("- (none)")
    L += ["", "## Representative failures", ""]
    for f in report["representatives"]["failures"]:
        L.append(f"- {f['id']} ({f['category']}, {f['failure_mode']}): Q: {f['question']}")
        L.append(f"  - expected `{f['expected_answer']}` · answer: {f['answer'][:160]}")
    L += ["", "## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
    return "\n".join(L) + "\n"


def main() -> None:
    dataset = load_dataset()
    responses = load_responses()
    if not responses:
        raise SystemExit(f"no Track B responses at {RESULTS}; run track_b/infer.py first")
    report = build_report(dataset, responses)
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    REPORT_MD.write_text(render_markdown(report), "utf-8")
    pm = report["primary_metrics"]
    print(f"[track-b] responded {report['responded_count']}/{report['case_count']}")
    print(f"[track-b] answer_accuracy={pm['answer_accuracy']} "
          f"hallucination_rate={pm['hallucination_rate']} refusal_rate={pm['refusal_rate']}")
    print(f"[track-b] wrote {REPORT_JSON} + {REPORT_MD.name}")


if __name__ == "__main__":
    main()
