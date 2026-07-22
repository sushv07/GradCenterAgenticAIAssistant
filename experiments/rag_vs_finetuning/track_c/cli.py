"""
experiments/rag_vs_finetuning/track_c/cli.py
Track C functional-validation CLI (Phase P10) — runs on the 3.9 MLX interpreter.

Exercises the full hybrid path (retrieval -> grounded prompt -> base+adapter ->
answer + citations) on a few diagnostic questions and prints a compact trace so a
human can confirm: retrieval executed, the adapter loaded, retrieved context is in
the prompt, citations were produced, and insufficient-evidence is handled. This is
NOT the benchmark and computes NO metrics.

  /Library/Developer/CommandLineTools/usr/bin/python3 \
      -m experiments.rag_vs_finetuning.track_c.cli
  ... --question "What is the application deadline for Accountancy?"
"""
from __future__ import annotations

import argparse
import sys

from experiments.rag_vs_finetuning.track_a.smoke_questions import DEV_QUESTIONS
from experiments.rag_vs_finetuning.track_c import prompt_builder as pb
from experiments.rag_vs_finetuning.track_c.infer import TrackCModel

# A deliberately unanswerable probe (not in the corpus) to exercise abstention.
_SOURCE_MISSING_PROBE = "What is the tuition cost in US dollars for the Music program?"


def _print_trace(model: TrackCModel, question: str, *, threshold=None) -> dict:
    from experiments.rag_vs_finetuning.track_c.infer import retrieve_via_subprocess
    b = retrieve_via_subprocess(question, threshold=threshold)
    rec = model.generate_grounded(b)
    ctx = pb.format_context(b["chunks"])
    print("=" * 78)
    print(f"Q: {question}")
    print(f"  retrieval: {len(b['chunks'])} chunks, latency {b['retrieval_latency_ms']}ms, "
          f"top sims {b['similarity_scores'][:3]}")
    print(f"  retrieved_chunk_ids : {rec['retrieved_chunk_ids']}")
    print(f"  context-in-prompt   : {'YES' if ctx and 'chunk_id=' in ctx else 'NO'} "
          f"({len(ctx)} chars)")
    print(f"  insufficient_evidence: {rec['insufficient_evidence']}")
    print(f"  citation_chunk_ids   : {rec['citation_chunk_ids']}")
    print(f"  gen latency          : {rec['generation_latency_ms']}ms  "
          f"(model_called={rec['model_called']})")
    print(f"  answer: {rec['answer'][:280]}")
    return rec


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Track C functional validation")
    ap.add_argument("--question", action="append", help="repeatable; overrides defaults")
    args = ap.parse_args(argv)

    questions = args.question or [
        DEV_QUESTIONS[0],          # answerable: deadline
        DEV_QUESTIONS[1],          # answerable: contact
        _SOURCE_MISSING_PROBE,     # source-missing: should abstain
    ]
    print(f"[track-c] loading base + official Track B adapter (checksum-verified)…")
    model = TrackCModel()
    print(f"[track-c] adapter checksum OK: {model.adapter_checksum[:23]}…\n")

    records = [_print_trace(model, q) for q in questions]

    # Deterministic grounding-failure probe: force empty retrieval (high threshold)
    # so all chunks fall below it -> Track C refuses WITHOUT calling the model,
    # exercising the insufficient-evidence handler independent of adapter output.
    print("\n[track-c] grounding-failure probe (threshold=0.99 -> empty retrieval):")
    probe = _print_trace(model, DEV_QUESTIONS[0], threshold=0.99)

    print("=" * 78)
    checks = {
        "retrieval_executed": all(r["retrieval_latency_ms"] >= 0 for r in records),
        "adapter_loaded": bool(model.adapter_checksum),
        "context_injected": any(r["retrieved_chunk_ids"] for r in records),
        "citations_generated": any(r["citation_chunk_ids"] for r in records),
        # handler works: empty retrieval yields the insufficient sentinel, no model call
        "insufficient_handled": probe["insufficient_evidence"]
        and not probe["model_called"] and probe["retrieved_chunk_ids"] == [],
        "no_runtime_errors": True,
    }
    print("[track-c] functional checks:")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
