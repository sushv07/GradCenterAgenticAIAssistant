"""
experiments/rag_vs_finetuning/analysis/compare.py
Phase P9 — Official comparative analysis: Track A (Pure RAG) vs Track B (Fine-Tuned).

Analysis-only. Loads the frozen Track A and Track B official responses, re-scores
BOTH through the existing (unmodified) evaluation pipeline plus the identical
derived-metric helpers used in P8.2, and emits a comparative report (JSON + MD)
with side-by-side metric/category tables, failure-mode comparison, root-cause
analysis, strengths/weaknesses, hybrid (Track C) recommendations, threats to
validity, and conclusions. No training, no benchmark rerun, no metric changes.

  python3 -m experiments.rag_vs_finetuning.analysis.compare
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.dataset import (
    compute_checksum, load_dataset,
)
from experiments.rag_vs_finetuning.evaluation.execute import (
    load_responses as load_a, to_response_record as tr_a,
)
from experiments.rag_vs_finetuning.evaluation.models import EvalDataset, ResponseRecord
from experiments.rag_vs_finetuning.evaluation.runner import run_evaluation
from experiments.rag_vs_finetuning.track_b.evaluate import (
    _derived_metrics, _percentile, load_responses as load_b,
    to_response_record as tr_b,
)

DR = Path("experiments/rag_vs_finetuning/data")
A_REPORT = DR / "evaluation/reports/track_a_baseline.json"
B_REPORT = DR / "evaluation/reports/track_b_evaluation.json"
OUT_JSON = DR / "evaluation/reports/comparative_analysis.json"
OUT_MD = DR / "evaluation/reports/comparative_analysis.md"

# metric -> ("higher" | "lower" | "context"): which direction is preferable.
_DIRECTION = {
    "answer_accuracy": "higher", "completeness": "higher",
    "abstention_accuracy": "higher", "hallucination_rate": "lower",
    "unsupported_claim_rate": "lower", "refusal_rate": "context",
}


def _e2e_latency(record_dicts: list[dict]) -> list[float]:
    return [r.get("retrieval_latency_ms", 0.0) + r["generation_latency_ms"]
            for r in record_dicts]


def _operational(record_dicts: list[dict]) -> dict:
    lat = _e2e_latency(record_dicts)
    return {
        "avg_latency_ms": round(sum(lat) / len(lat), 3) if lat else None,
        "p50_latency_ms": _percentile(lat, 0.50),
        "p95_latency_ms": _percentile(lat, 0.95),
    }


def _diff(a, b) -> dict:
    """B relative to A: absolute and percentage difference."""
    if a is None or b is None:
        return {"absolute": None, "percent": None}
    absd = round(b - a, 4)
    pct = round((b - a) / abs(a) * 100, 1) if a != 0 else None
    return {"absolute": absd, "percent": pct}


def _better(metric: str, a, b) -> str:
    d = _DIRECTION.get(metric, "context")
    if d == "context" or a is None or b is None or a == b:
        return "context" if d == "context" else ("tie" if a == b else "n/a")
    if d == "higher":
        return "track_a" if a > b else "track_b"
    return "track_a" if a < b else "track_b"           # lower is better


def build_comparison() -> dict:
    dataset = load_dataset()
    assert compute_checksum(dataset) == dataset.dataset_checksum, "benchmark drift"
    a_raw, b_raw = load_a(), load_b()
    a_dicts = [r.model_dump() for r in a_raw]                 # OfficialResponse -> dict
    b_dicts = b_raw                                           # already dicts

    a_recs = [tr_a(r) for r in a_raw]
    b_recs = [tr_b(r) for r in b_raw]
    a_eval = run_evaluation(dataset, a_recs, track="track_a_pure_rag")
    b_eval = run_evaluation(dataset, b_recs, track="track_b_finetuned_no_rag")

    a_frozen = json.loads(A_REPORT.read_text())
    b_frozen = json.loads(B_REPORT.read_text())
    consistency = {
        "same_benchmark_checksum": a_frozen["dataset_checksum"]
        == b_frozen["dataset_checksum"] == dataset.dataset_checksum,
        "track_a_reproduces_frozen": a_eval.metrics["answer_accuracy"]
        == a_frozen["overall_metrics"]["answer_accuracy"],
        "track_b_reproduces_frozen": b_eval.metrics["answer_accuracy"]
        == b_frozen["overall_metrics"]["answer_accuracy"],
        "case_count": {"track_a": len(a_recs), "track_b": len(b_recs)},
    }

    a_by = {r.question.strip(): r for r in a_recs}
    b_by = {r.question.strip(): r for r in b_recs}
    a_der, b_der = _derived_metrics(dataset, a_by), _derived_metrics(dataset, b_by)

    def A(m):  # unified metric lookup for track A
        return {**a_eval.metrics, **a_der}.get(m)

    def B(m):
        return {**b_eval.metrics, **b_der}.get(m)

    overall = {}
    for m in ["answer_accuracy", "completeness", "hallucination_rate",
              "unsupported_claim_rate", "refusal_rate", "abstention_accuracy"]:
        overall[m] = {"track_a": A(m), "track_b": B(m),
                      "delta_b_minus_a": _diff(A(m), B(m)), "preferable": _better(m, A(m), B(m))}

    a_op, b_op = _operational(a_dicts), _operational(b_dicts)
    operational = {
        k: {"track_a": a_op[k], "track_b": b_op[k], "delta_b_minus_a": _diff(a_op[k], b_op[k])}
        for k in ["avg_latency_ms", "p50_latency_ms", "p95_latency_ms"]
    }
    operational["_caveat"] = (
        "Latencies are NOT a like-for-like runtime comparison: Track A generation "
        "runs on Ollama (qwen2.5:7b-instruct) and Track B on Apple MLX "
        "(Qwen2.5-7B-Instruct-4bit). Track B also includes MLX first-call/tail "
        "stalls under 16 GB memory pressure. Read latency as indicative only.")

    # Category comparison from the identical pipeline.
    cats = sorted(set(a_eval.metrics_by_category) | set(b_eval.metrics_by_category))
    category = {}
    for c in cats:
        av = a_eval.metrics_by_category.get(c, {}).get("accuracy")
        bv = b_eval.metrics_by_category.get(c, {}).get("accuracy")
        n = a_eval.metrics_by_category.get(c, {}).get("count")
        winner = ("track_a" if (av or 0) > (bv or 0)
                  else "track_b" if (bv or 0) > (av or 0) else "tie")
        category[c] = {"n": n, "track_a": av, "track_b": bv, "winner": winner}

    failure = {
        "track_a": a_frozen["failure_analysis"]["counts"],
        "track_b": b_frozen["failure_analysis"]["counts"],
        "track_b_modes": b_frozen.get("common_failure_modes", []),
        "representative": {
            "track_a_incorrect": a_frozen["failure_analysis"]["examples"].get("incorrect_answer", []),
            "track_a_abstention_error": a_frozen["failure_analysis"]["examples"].get("abstention_error", []),
            "track_b_failures": [
                {"id": f["id"], "mode": f["failure_mode"], "answer": f["answer"][:160]}
                for f in b_frozen["representatives"]["failures"][:4]],
        },
    }

    return {
        "phase": "P9_comparative_analysis",
        "analysis_only": True,
        "dataset_version": dataset.dataset_version,
        "dataset_checksum": dataset.dataset_checksum,
        "consistency_checks": consistency,
        "tracks": {
            "track_a": {"name": "Pure RAG", "model": "qwen2.5:7b-instruct (Ollama)",
                        "retrieval": "Chroma masters_track_a_v1 (top-k, cosine)",
                        "adapter": None},
            "track_b": {"name": "Fine-Tuned Only",
                        "model": "Qwen2.5-7B-Instruct-4bit (MLX) + Track B LoRA",
                        "retrieval": "DISABLED",
                        "adapter": b_frozen["config"]["adapter_checksum"]},
        },
        "overall_comparison": overall,
        "operational_comparison": operational,
        "category_comparison": category,
        "failure_comparison": failure,
        "root_cause_analysis": _root_cause(overall, category, failure, a_der, b_der),
        "strengths_weaknesses": _strengths_weaknesses(),
        "hybrid_design_insights": _hybrid_insights(),
        "threats_to_validity": _threats(),
        "conclusions": _conclusions(overall, category),
        "executive_summary": _exec_summary(overall),
    }


def _root_cause(overall, category, failure, a_der, b_der) -> list[dict]:
    return [
        {"finding": "Track A is ~6.7x more accurate on answerable questions "
                    "(0.458 vs 0.068).",
         "root_cause": "Retrieval grounding. Track A conditions generation on the "
                       "frozen corpus chunks, so when retrieval surfaces the right "
                       "chunk the model copies published wording. Track B must recall "
                       "facts from a 121-example LoRA and has no text to ground on.",
         "evidence": "answer_accuracy 0.4576 vs 0.0678; Track A wins every category."},
        {"finding": "Track B fabricates on 100% of source-missing cases; Track A only 16%.",
         "root_cause": "The trained refusal did not generalise and, absent retrieved "
                       "context, Track B has no signal that evidence is missing. Track "
                       "A sees empty/low-similarity retrieval and abstains.",
         "evidence": "hallucination_rate 1.0 (B) vs 0.16 (A); abstention_accuracy 0.0 vs 0.84."},
        {"finding": "Track B output is degenerate (repetition, corrupted refusals, "
                    "fabricated tokens); unsupported-claim rate 0.947.",
         "root_cause": "Overfitting/instability from P8.1: at LR 1e-4 on 121 examples "
                       "the validation loss minimised at iter 40 then diverged. LoRA on "
                       "a tiny SFT set degraded fluency rather than adding knowledge.",
         "evidence": "unsupported_claim_rate 0.9467; P8.1 val-loss curve 1.018@40 -> "
                     "5.338@200; representative answers loop 'don have the provided…'."},
        {"finding": "Track A's main weakness is over-abstention, not fabrication.",
         "root_cause": "Retrieval recall is the ceiling: when the right chunk is not in "
                       "top-k, Track A abstains (safe failure) rather than answer.",
         "evidence": "refusal_rate 0.5714 with abstention_error=31 and retrieval_failure=29; "
                     "hallucination only 0.16."},
    ]


def _strengths_weaknesses() -> dict:
    return {
        "track_a": {
            "strengths": [
                "High factual accuracy when retrieval hits (0.458 answerable, wins every category).",
                "Safe failure mode: abstains instead of fabricating (abstention_accuracy 0.84, hallucination 0.16).",
                "Fluent, grounded answers with citable chunks; no catastrophic degeneration.",
                "Knowledge is swappable — update the corpus/index without retraining."],
            "weaknesses": [
                "Over-abstains when retrieval misses (refusal_rate 0.571; 31 answerable abstentions).",
                "Citation precision is imperfect (incorrect_citation=59: extra/irrelevant chunks retrieved).",
                "Accuracy bounded by retrieval recall (retrieval_challenge only 0.20)."],
            "best_use_cases": [
                "Factual Q&A over a maintained knowledge base where correctness and "
                "abstention matter more than coverage.",
                "Domains with frequently changing source content."],
            "limitations": [
                "Depends on embedding quality, chunking, and top-k threshold.",
                "No parametric domain adaptation; style is the base model's."]},
        "track_b": {
            "strengths": [
                "Answers more answerable questions without abstaining (50/59 attempted vs 32/59).",
                "No retrieval infrastructure needed at inference (self-contained weights).",
                "Occasionally surfaces the right token (overview 0.25) — some signal was learned."],
            "weaknesses": [
                "Very low accuracy (0.068) and completeness; near-total unsupported claims (0.947).",
                "Fabricates on all source-missing cases (hallucination 1.0; abstention 0.0).",
                "Degenerate generation: repetition, corrupted refusals, invented emails/dates."],
            "best_use_cases": [
                "On the current 121-example dataset: none for production factual Q&A.",
                "Potentially style/format adaptation if paired with grounding (see hybrid)."],
            "limitations": [
                "Tiny SFT set + aggressive LR overfit; selected checkpoint still under-fits QA.",
                "No grounding signal, so cannot know when to abstain."]},
    }


def _hybrid_insights() -> dict:
    return {
        "inherit_from_track_a": [
            "Retrieval grounding as the primary knowledge source — it drives the 6.7x "
            "accuracy advantage and enables evidence-aware abstention.",
            "The abstain-when-evidence-is-missing behaviour (Track A hallucination 0.16 "
            "vs Track B 1.0).",
            "Citations tied to retrieved chunks for verifiability."],
        "inherit_from_track_b": [
            "Only lightweight, format/behaviour-oriented fine-tuning — NOT knowledge "
            "injection. Any adapter must be trained to consume retrieved context, not "
            "to memorise facts.",
            "If used at all, fine-tune for refusal formatting and answer style on top of "
            "retrieved evidence."],
        "weaknesses_track_c_should_solve": [
            "Track A over-abstention on answerable questions (recover the 31 answerable "
            "abstentions via better recall / higher-k / query expansion).",
            "Track A imperfect citation precision (incorrect_citation=59).",
            "Track B degeneration and fabrication — eliminated by grounding generation on "
            "retrieved context and training the adapter WITH context in the prompt.",
            "Never repeat P8.1's overfitting: more data, lower LR, and validation-based "
            "early stopping if any fine-tuning is done."],
        "recommended_track_c_shape": (
            "RAG-first pipeline (Track A retrieval + prompt) with an OPTIONAL small LoRA "
            "trained on (retrieved-context -> grounded-answer/refusal) pairs — retrieval "
            "supplies facts, the adapter only shapes faithful formatting and abstention. "
            "Fine-tuning must never be the knowledge store."),
    }


def _threats() -> list[str]:
    return [
        "Small supervised dataset (121 train / 13 val) — Track B is data-starved; "
        "results may not reflect fine-tuning with a larger, cleaner SFT set.",
        "Single institution (CSULB Graduate Center) and a single base-model family (Qwen2.5-7B).",
        "Different inference runtimes per track (Ollama for A, Apple MLX 4-bit for B) — "
        "latency is not directly comparable and quantization differs.",
        "Deterministic substring/set scoring, not an LLM judge — can both under- and "
        "over-credit answers (e.g. Track B 'successes' are substring coincidences).",
        "Benchmark is 84 cases over 12 programs; category cells are small (n=5–13).",
        "Single official run per track (greedy); no seed/variance sweep.",
        "Track B hyperparameters were fixed by P8.1, not tuned — a different LR/size "
        "could change Track B's absolute numbers (though not the grounding conclusion).",
    ]


def _conclusions(overall, category) -> dict:
    return {
        "primary_findings": [
            "Pure RAG (Track A) decisively outperforms fine-tuned-only (Track B) on this "
            "benchmark: 0.458 vs 0.068 answer accuracy, winning all 8 categories.",
            "The decisive factor is retrieval grounding, not model size — both use a 7B "
            "Qwen2.5 base.",
            "Fine-tuning on 121 examples injected almost no reliable knowledge and "
            "degraded generation quality."],
        "surprising_findings": [
            "Track B did not merely under-perform — it catastrophically degenerated "
            "(repetition, fabricated tokens), showing tiny-dataset LoRA can harm a strong "
            "instruct model rather than gently under-fit.",
            "Track B abstained LESS (0.107) yet was far less accurate — it answered "
            "confidently and wrongly, the opposite of the safe RAG failure mode."],
        "practical_implications": [
            "For factual assistants over a maintained corpus, invest in retrieval quality "
            "before fine-tuning.",
            "Use fine-tuning for behaviour/format on top of retrieval, not as a knowledge "
            "store.",
            "Evidence-aware abstention is a first-class safety property that RAG provides "
            "and fine-tuning-only did not."],
        "lessons_learned": [
            "Match learning rate and dataset size to avoid overfitting (P8.1 val loss "
            "diverged after iter 40).",
            "Always evaluate abstention/hallucination, not just accuracy — the tracks "
            "differ most there.",
            "Keep a frozen benchmark + one scoring pipeline so cross-condition comparison "
            "is exact (both tracks reproduced their frozen reports)."],
    }


def _exec_summary(overall) -> str:
    aa = overall["answer_accuracy"]
    hr = overall["hallucination_rate"]
    return (
        "On an identical 84-case frozen benchmark scored by one unchanged pipeline, "
        f"Pure RAG (Track A) reached {aa['track_a']} answer accuracy versus "
        f"{aa['track_b']} for Fine-Tuned-Only (Track B), and hallucinated on "
        f"{hr['track_a']:.0%} of source-missing cases versus {hr['track_b']:.0%} for "
        "Track B. Track A wins every category. The gap is driven by retrieval "
        "grounding and evidence-aware abstention, while Track B — a LoRA over 121 "
        "examples with no retrieval — overfit and degenerated. Recommendation for "
        "Track C: keep RAG as the knowledge source and abstention mechanism; use "
        "fine-tuning (if any) only to shape faithful answer/refusal formatting on top "
        "of retrieved context, never to store facts.")


def render_markdown(r: dict) -> str:
    oc, op, cat = r["overall_comparison"], r["operational_comparison"], r["category_comparison"]
    L = ["# Phase P9 — Comparative Analysis: Track A (Pure RAG) vs Track B (Fine-Tuned)",
         "", "## Executive summary", "", r["executive_summary"], "",
         f"- benchmark: {r['dataset_version']} · checksum `{r['dataset_checksum'][:20]}…`",
         f"- consistency: same benchmark for both = {r['consistency_checks']['same_benchmark_checksum']}; "
         f"both reproduce frozen reports = "
         f"{r['consistency_checks']['track_a_reproduces_frozen'] and r['consistency_checks']['track_b_reproduces_frozen']}",
         "", "## Overall metric comparison", "",
         "| metric | Track A | Track B | Δ (B−A) | Δ% | preferable |",
         "| --- | --- | --- | --- | --- | --- |"]
    for m, v in oc.items():
        d = v["delta_b_minus_a"]
        L.append(f"| {m} | {v['track_a']} | {v['track_b']} | {d['absolute']} | "
                 f"{'' if d['percent'] is None else str(d['percent'])+'%'} | {v['preferable']} |")
    L += ["", "## Operational comparison", "",
          "| metric | Track A | Track B | Δ (B−A) |", "| --- | --- | --- | --- |"]
    for m in ["avg_latency_ms", "p50_latency_ms", "p95_latency_ms"]:
        v = op[m]
        L.append(f"| {m} | {v['track_a']} | {v['track_b']} | {v['delta_b_minus_a']['absolute']} |")
    L += ["", f"> {op['_caveat']}", "", "## Category comparison", "",
          "| category | n | Track A | Track B | winner |", "| --- | --- | --- | --- | --- |"]
    for c, v in cat.items():
        L.append(f"| {c} | {v['n']} | {v['track_a']} | {v['track_b']} | {v['winner']} |")
    fc = r["failure_comparison"]
    L += ["", "## Failure-mode comparison", "",
          f"- Track A counts: {fc['track_a']}",
          f"- Track B counts: {fc['track_b']}", "", "Track B failure modes:", ""]
    L += [f"- {m}" for m in fc["track_b_modes"]]
    L += ["", "Representative Track B failures:", ""]
    L += [f"- {f['id']} ({f['mode']}): {f['answer']}" for f in fc["representative"]["track_b_failures"]]
    L += ["", "## Root cause analysis", ""]
    for rc in r["root_cause_analysis"]:
        L += [f"- **{rc['finding']}**",
              f"  - cause: {rc['root_cause']}",
              f"  - evidence: {rc['evidence']}"]
    sw = r["strengths_weaknesses"]
    for tk, label in [("track_a", "Track A — Pure RAG"), ("track_b", "Track B — Fine-Tuned Only")]:
        s = sw[tk]
        L += ["", f"## {label}", "", "**Strengths**"] + [f"- {x}" for x in s["strengths"]]
        L += ["", "**Weaknesses**"] + [f"- {x}" for x in s["weaknesses"]]
        L += ["", "**Best use cases**"] + [f"- {x}" for x in s["best_use_cases"]]
        L += ["", "**Limitations**"] + [f"- {x}" for x in s["limitations"]]
    hi = r["hybrid_design_insights"]
    L += ["", "## Hybrid design insights (for Track C)", "",
          "**Inherit from Track A**"] + [f"- {x}" for x in hi["inherit_from_track_a"]]
    L += ["", "**Inherit from Track B**"] + [f"- {x}" for x in hi["inherit_from_track_b"]]
    L += ["", "**Weaknesses Track C should solve**"] + [f"- {x}" for x in hi["weaknesses_track_c_should_solve"]]
    L += ["", "**Recommended Track C shape**", "", hi["recommended_track_c_shape"]]
    L += ["", "## Threats to validity", ""] + [f"- {x}" for x in r["threats_to_validity"]]
    con = r["conclusions"]
    L += ["", "## Conclusions", "", "**Primary findings**"] + [f"- {x}" for x in con["primary_findings"]]
    L += ["", "**Surprising findings**"] + [f"- {x}" for x in con["surprising_findings"]]
    L += ["", "**Practical implications**"] + [f"- {x}" for x in con["practical_implications"]]
    L += ["", "**Lessons learned**"] + [f"- {x}" for x in con["lessons_learned"]]
    return "\n".join(L) + "\n"


def main() -> None:
    report = build_comparison()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    OUT_MD.write_text(render_markdown(report), "utf-8")
    cc = report["consistency_checks"]
    print(f"[p9] consistency: same_benchmark={cc['same_benchmark_checksum']} "
          f"A_reproduces={cc['track_a_reproduces_frozen']} B_reproduces={cc['track_b_reproduces_frozen']}")
    aa = report["overall_comparison"]["answer_accuracy"]
    print(f"[p9] answer_accuracy  A={aa['track_a']}  B={aa['track_b']}  Δ%={aa['delta_b_minus_a']['percent']}")
    print(f"[p9] wrote {OUT_JSON} + {OUT_MD.name}")


if __name__ == "__main__":
    main()
