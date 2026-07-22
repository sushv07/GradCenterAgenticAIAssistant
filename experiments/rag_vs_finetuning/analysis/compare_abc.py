"""
experiments/rag_vs_finetuning/analysis/compare_abc.py
Phase P11 — Three-way comparative analysis: Track A vs Track B vs Track C.

Analysis-only. Re-scores all three tracks' frozen official responses through the
UNMODIFIED evaluation pipeline (verified to reproduce each frozen report) plus the
identical derived-metric helpers, then emits side-by-side metric/category tables,
a three-way error-mode comparison, and data-driven research conclusions. Trains
nothing, reruns no benchmark, changes no metric. Leaves the P9 two-way report
(compare.py / comparative_analysis.*) untouched.

  python3 -m experiments.rag_vs_finetuning.analysis.compare_abc
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.dataset import compute_checksum, load_dataset
from experiments.rag_vs_finetuning.evaluation.execute import (
    load_responses as load_a, to_response_record as tr_a,
)
from experiments.rag_vs_finetuning.evaluation.runner import run_evaluation
from experiments.rag_vs_finetuning.track_b.evaluate import (
    _derived_metrics, load_responses as load_b, to_response_record as tr_b,
)
from experiments.rag_vs_finetuning.track_c.evaluate import (
    load_responses as load_c, to_response_record as tr_c,
)

DR = Path("experiments/rag_vs_finetuning/data")
OUT_JSON = DR / "evaluation/reports/comparative_analysis_abc.json"
OUT_MD = DR / "evaluation/reports/comparative_analysis_abc.md"

_HIGHER_BETTER = {"answer_accuracy", "completeness", "abstention_accuracy",
                  "citation_recall", "citation_precision", "retrieval_recall_at_k"}
_LOWER_BETTER = {"hallucination_rate", "unsupported_claim_rate"}


def _e2e(dicts):
    return [d.get("retrieval_latency_ms", 0.0) + d["generation_latency_ms"] for d in dicts]


def _load_all():
    ds = load_dataset()
    assert compute_checksum(ds) == ds.dataset_checksum
    a_raw, b_raw, c_raw = load_a(), load_b(), load_c()
    tracks = {}
    for key, raw, torec, dicts in [
        ("track_a", a_raw, tr_a, [r.model_dump() for r in a_raw]),
        ("track_b", b_raw, tr_b, b_raw),
        ("track_c", c_raw, tr_c, c_raw),
    ]:
        recs = [torec(r) for r in raw]
        ev = run_evaluation(ds, recs, track=key)
        by_q = {r.question.strip(): r for r in recs}
        der = _derived_metrics(ds, by_q)
        e2e = _e2e(dicts)
        tracks[key] = {"eval": ev, "derived": der, "dicts": dicts,
                       "avg_latency_ms": round(sum(e2e) / len(e2e), 1) if e2e else None,
                       "metric": {**ev.metrics, **der}}
    return ds, tracks


def _winner(metric, vals: dict):
    present = {k: v for k, v in vals.items() if v is not None}
    if not present:
        return "n/a"
    if metric in _LOWER_BETTER:
        best = min(present.values())
    elif metric in _HIGHER_BETTER:
        best = max(present.values())
    else:
        return "context"
    winners = [k for k, v in present.items() if v == best]
    return winners[0] if len(winners) == 1 else "tie"


def build() -> dict:
    ds, T = _load_all()
    A, B, C = T["track_a"]["metric"], T["track_b"]["metric"], T["track_c"]["metric"]

    overall = {}
    for m in ["answer_accuracy", "completeness", "hallucination_rate",
              "unsupported_claim_rate", "refusal_rate", "abstention_accuracy",
              "citation_precision", "citation_recall", "retrieval_recall_at_k"]:
        vals = {"track_a": A.get(m), "track_b": B.get(m), "track_c": C.get(m)}
        overall[m] = {**vals, "winner": _winner(m, vals)}

    cats = sorted(set(T["track_a"]["eval"].metrics_by_category)
                  | set(T["track_c"]["eval"].metrics_by_category))
    category = {}
    for c in cats:
        vals = {k: T[k]["eval"].metrics_by_category.get(c, {}).get("accuracy") for k in T}
        category[c] = {"n": T["track_a"]["eval"].metrics_by_category.get(c, {}).get("count"),
                       **vals, "winner": _winner("answer_accuracy", vals)}

    operational = {k: T[k]["avg_latency_ms"] for k in T}

    a_frozen = json.loads((DR / "evaluation/reports/track_a_baseline.json").read_text())
    b_frozen = json.loads((DR / "evaluation/reports/track_b_evaluation.json").read_text())
    c_frozen = json.loads((DR / "evaluation/reports/track_c_evaluation.json").read_text())
    failure = {"track_a": a_frozen["failure_analysis"]["counts"],
               "track_b": b_frozen["failure_analysis"]["counts"],
               "track_c": c_frozen["failure_analysis"]["counts"]}

    consistency = {
        "same_benchmark": (a_frozen["dataset_checksum"] == b_frozen["dataset_checksum"]
                           == c_frozen["dataset_checksum"] == ds.dataset_checksum),
        "reproduce_frozen": {
            "track_a": A["answer_accuracy"] == a_frozen["overall_metrics"]["answer_accuracy"],
            "track_b": B["answer_accuracy"] == b_frozen["overall_metrics"]["answer_accuracy"],
            "track_c": C["answer_accuracy"] == c_frozen["overall_metrics"]["answer_accuracy"]},
    }

    return {
        "phase": "P11_three_way_comparison", "analysis_only": True,
        "dataset_version": ds.dataset_version, "dataset_checksum": ds.dataset_checksum,
        "consistency_checks": consistency,
        "overall_comparison": overall, "category_comparison": category,
        "operational_avg_latency_ms": operational, "failure_comparison": failure,
        "discussion": _discussion(A, B, C),
        "error_analysis": _error_analysis(failure, c_frozen),
        "research_conclusions": _conclusions(A, B, C),
        "threats_to_validity": _threats(),
    }


def _cmp(x, y, eps=1e-9):
    if x is None or y is None:
        return "n/a"
    return "higher" if x > y + eps else "lower" if x < y - eps else "equal"


def _discussion(A, B, C) -> dict:
    return {
        "track_c_vs_track_b": (
            f"Adding retrieval to the same adapter changed answer accuracy "
            f"{B['answer_accuracy']} (B) -> {C['answer_accuracy']} (C) and hallucination "
            f"{B['hallucination_rate']} -> {C['hallucination_rate']}. Grounding is "
            f"{_cmp(C['answer_accuracy'], B['answer_accuracy'])} for accuracy vs fine-tuning-only."),
        "track_c_vs_track_a": (
            f"Against Pure RAG, Track C answer accuracy is {C['answer_accuracy']} vs "
            f"{A['answer_accuracy']} (A) — {_cmp(C['answer_accuracy'], A['answer_accuracy'])}; "
            f"hallucination {C['hallucination_rate']} vs {A['hallucination_rate']}. Track C uses "
            "the SAME retrieval as A, so any gap is attributable to the adapter's generation."),
        "did_retrieval_compensate": (
            "Retrieval " + ("substantially compensated" if (C['answer_accuracy'] or 0) >= 2 * (B['answer_accuracy'] or 0.0001)
                            else "only partly compensated") +
            " for the weak adapter: Track C recovers grounded evidence and citations that "
            "Track B lacked, but the reused context-free/overfit adapter still degrades the "
            "final generation."),
        "hybrid_as_expected": (
            "The architecture behaved as designed (retrieval feeds context, adapter generates, "
            "empty-retrieval abstains), but the reused Track B adapter — trained WITHOUT context "
            "and overfit — is the binding constraint, so the hybrid did not reach Track A quality."),
    }


def _error_analysis(failure, c_frozen) -> dict:
    return {
        "track_c_failure_counts": failure["track_c"],
        "track_c_failure_modes": [
            "Degenerate / low-information answers — the adapter emits short corrupted "
            "refusals ('I don't have that.') even when correct context is present.",
            "Grounding under-use — retrieved context is in the prompt and cited, but the "
            "adapter does not copy the grounded fact into the answer.",
            "Retrieval ceiling — some answerable questions retrieve the wrong program's "
            "chunk (shared Track A recall limit).",
            "Citations are populated from retrieved evidence, so citation errors track "
            "retrieval precision rather than fabrication.",
        ],
        "representative_failures": [
            {"id": f["id"], "mode": f["failure_mode"], "answer": f["answer"][:140]}
            for f in c_frozen["representatives"]["failures"][:4]],
    }


def _conclusions(A, B, C) -> dict:
    rag_over_ft = (A["answer_accuracy"] or 0) > (B["answer_accuracy"] or 0)
    hybrid_beats_ft = (C["answer_accuracy"] or 0) > (B["answer_accuracy"] or 0)
    hybrid_beats_rag = (C["answer_accuracy"] or 0) > (A["answer_accuracy"] or 0)
    return {
        "when_rag_over_finetuning": [
            f"On this benchmark RAG beat fine-tuning-only decisively "
            f"({A['answer_accuracy']} vs {B['answer_accuracy']} accuracy; hallucination "
            f"{A['hallucination_rate']} vs {B['hallucination_rate']})."
            if rag_over_ft else
            f"Fine-tuning-only matched/beat RAG ({B['answer_accuracy']} vs {A['answer_accuracy']}).",
            "Prefer RAG when institutional knowledge is factual, updatable, and larger than "
            "what a small SFT set can encode, and when safe abstention on missing evidence "
            "matters — RAG grounds answers and refuses instead of fabricating.",
            "Prefer fine-tuning only for fixed behaviour/format/style, not for storing facts; "
            "a 121-example LoRA injected no reliable knowledge and degraded generation.",
        ],
        "when_hybrid_adds_value": [
            (f"Hybrid improved on fine-tuning-only ({C['answer_accuracy']} vs "
             f"{B['answer_accuracy']}) by restoring grounding and citations."
             if hybrid_beats_ft else
             f"Hybrid did not beat fine-tuning-only ({C['answer_accuracy']} vs {B['answer_accuracy']})."),
            (f"Hybrid did NOT surpass Pure RAG ({C['answer_accuracy']} vs {A['answer_accuracy']}): "
             "reusing the weak, context-free Track B adapter as the generator capped quality."
             if not hybrid_beats_rag else
             f"Hybrid surpassed Pure RAG ({C['answer_accuracy']} vs {A['answer_accuracy']})."),
            "Hybrid RAG+fine-tuning adds value only when the adapter is trained ON the "
            "retrieval-augmented format (context -> grounded answer/refusal). Bolting an "
            "adapter tuned without context onto a RAG pipeline does not help and can hurt.",
            "Evidence-based recommendation: for a future Track C iteration, retrain a small "
            "adapter with retrieved context in the prompt and proper regularisation "
            "(more data, lower LR, early stopping); keep retrieval as the knowledge source.",
        ],
        "central_answer": (
            "Retrieval grounding is the dominant factor for factual, updatable QA. "
            "Fine-tuning helps only as a behaviour layer on top of retrieval, and only when "
            "trained for that setting; a weak adapter provides no hybrid benefit over pure RAG."),
    }


def _threats() -> list[str]:
    return [
        "Small SFT dataset (121/13) — Track B/C adapter is data-starved.",
        "Single institution and single base-model family (Qwen2.5-7B).",
        "Tracks A vs B/C use different runtimes (Ollama vs Apple MLX 4-bit); latency not directly comparable.",
        "Deterministic substring/set scoring, not an LLM judge.",
        "84-case benchmark; small per-category cells (n=5–13).",
        "Single greedy run per track; no variance sweep.",
        "Track C reuses the P8.1 adapter unchanged (mandated); it was not trained with context.",
    ]


def render_md(r: dict) -> str:
    oc, cat = r["overall_comparison"], r["category_comparison"]
    L = ["# Phase P11 — Three-Way Comparison: Track A vs Track B vs Track C", "",
         "## Consistency", "",
         f"- same benchmark for all three: {r['consistency_checks']['same_benchmark']}",
         f"- each reproduces its frozen report: {r['consistency_checks']['reproduce_frozen']}",
         "", "## Overall metric comparison", "",
         "| metric | Track A (RAG) | Track B (FT) | Track C (Hybrid) | winner |",
         "| --- | --- | --- | --- | --- |"]
    for m, v in oc.items():
        L.append(f"| {m} | {v['track_a']} | {v['track_b']} | {v['track_c']} | {v['winner']} |")
    L += ["", "## Operational (avg end-to-end latency, ms)", "",
          f"- A {r['operational_avg_latency_ms']['track_a']} · "
          f"B {r['operational_avg_latency_ms']['track_b']} · "
          f"C {r['operational_avg_latency_ms']['track_c']}",
          "> Latency not directly comparable across runtimes (Ollama vs MLX).",
          "", "## Category comparison (answer accuracy)", "",
          "| category | n | A | B | C | winner |", "| --- | --- | --- | --- | --- | --- |"]
    for c, v in cat.items():
        L.append(f"| {c} | {v['n']} | {v['track_a']} | {v['track_b']} | {v['track_c']} | {v['winner']} |")
    L += ["", "## Failure-mode comparison (counts)", "",
          f"- Track A: {r['failure_comparison']['track_a']}",
          f"- Track B: {r['failure_comparison']['track_b']}",
          f"- Track C: {r['failure_comparison']['track_c']}"]
    d = r["discussion"]
    L += ["", "## Discussion", "",
          f"- **Track C vs Track B:** {d['track_c_vs_track_b']}",
          f"- **Track C vs Track A:** {d['track_c_vs_track_a']}",
          f"- **Did retrieval compensate?** {d['did_retrieval_compensate']}",
          f"- **Hybrid as expected?** {d['hybrid_as_expected']}"]
    ea = r["error_analysis"]
    L += ["", "## Error analysis (Track C)", "", f"counts: {ea['track_c_failure_counts']}", ""]
    L += [f"- {m}" for m in ea["track_c_failure_modes"]]
    L += ["", "Representative Track C failures:", ""]
    L += [f"- {f['id']} ({f['mode']}): {f['answer']}" for f in ea["representative_failures"]]
    rc = r["research_conclusions"]
    L += ["", "## Research conclusions", "", "### When should RAG be preferred over fine-tuning?", ""]
    L += [f"- {x}" for x in rc["when_rag_over_finetuning"]]
    L += ["", "### When does hybrid RAG + fine-tuning add value?", ""]
    L += [f"- {x}" for x in rc["when_hybrid_adds_value"]]
    L += ["", f"**Central answer:** {rc['central_answer']}"]
    L += ["", "## Threats to validity", ""] + [f"- {x}" for x in r["threats_to_validity"]]
    return "\n".join(L) + "\n"


def main() -> None:
    r = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n", "utf-8")
    OUT_MD.write_text(render_md(r), "utf-8")
    oc = r["overall_comparison"]["answer_accuracy"]
    print(f"[p11] answer_accuracy  A={oc['track_a']}  B={oc['track_b']}  C={oc['track_c']}  winner={oc['winner']}")
    print(f"[p11] reproduce_frozen: {r['consistency_checks']['reproduce_frozen']}")
    print(f"[p11] wrote {OUT_JSON.name} + {OUT_MD.name}")


if __name__ == "__main__":
    main()
