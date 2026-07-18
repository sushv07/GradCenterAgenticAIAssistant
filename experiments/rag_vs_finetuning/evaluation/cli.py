"""
experiments/rag_vs_finetuning/evaluation/cli.py
Evaluation CLI (Phase P7.1).

    python -m experiments.rag_vs_finetuning.evaluation.cli validate
    python -m experiments.rag_vs_finetuning.evaluation.cli summary
    python -m experiments.rag_vs_finetuning.evaluation.cli run-track-a
    python -m experiments.rag_vs_finetuning.evaluation.cli baseline-report
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.dataset import (
    DATASET_PATH, load_chunk_ids, load_dataset, validate_dataset,
)

_CHUNKS = Path("experiments/rag_vs_finetuning/data/chunks/chunks.jsonl")


def cmd_validate() -> int:
    ds = load_dataset(Path.cwd() / DATASET_PATH)
    errors = validate_dataset(ds, load_chunk_ids(Path.cwd() / _CHUNKS))
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  -", e)
        return 1
    print(f"VALID: {len(ds.cases)} cases, checksum {ds.dataset_checksum[:20]}…, frozen={ds.frozen}")
    return 0


def cmd_summary() -> int:
    ds = load_dataset(Path.cwd() / DATASET_PATH)
    print(f"dataset_version: {ds.dataset_version} | frozen: {ds.frozen} | cases: {len(ds.cases)}")
    print("by category:", dict(sorted(Counter(c.category for c in ds.cases).items())))
    print("by program:", dict(sorted(Counter(c.program for c in ds.cases).items())))
    print("by difficulty:", dict(sorted(Counter(c.difficulty for c in ds.cases).items())))
    print("answerable:", sum(c.answerable for c in ds.cases),
          "| source_missing:", sum(c.source_missing for c in ds.cases))
    return 0


def cmd_run_track_a() -> int:
    import chromadb
    from experiments.rag_vs_finetuning.configs.config import load_config
    from experiments.rag_vs_finetuning.embeddings.embedder import SentenceTransformerEmbedder
    from experiments.rag_vs_finetuning.evaluation.execute import persist_responses, run_track_a
    from experiments.rag_vs_finetuning.track_a.llm import OllamaLLM
    cfg = load_config()
    ds = load_dataset(Path.cwd() / DATASET_PATH)
    emb = SentenceTransformerEmbedder(model_id=cfg.embedding.model, device=cfg.embedding.device,
                                      normalize=cfg.embedding.normalize)
    coll = chromadb.PersistentClient(path=str(Path.cwd() / cfg.vector_store.persistence_path)) \
        .get_collection(cfg.vector_store.collection_name)
    t = cfg.track_a.llm
    llm = OllamaLLM(base_url=t.base_url, model=t.model, temperature=t.temperature,
                    top_p=t.top_p, max_tokens=t.max_tokens, seed=t.seed)
    responses = run_track_a(ds, embedder=emb, collection=coll, llm=llm,
                            top_k=cfg.track_a.top_k, threshold=cfg.track_a.similarity_threshold)
    persist_responses(responses)
    print(f"executed Track A on {len(responses)} cases; persisted official responses.")
    return 0


def cmd_baseline_report() -> int:
    from experiments.rag_vs_finetuning.evaluation.execute import load_responses
    from experiments.rag_vs_finetuning.evaluation.report import (
        build_baseline_report, persist_report,
    )
    ds = load_dataset(Path.cwd() / DATASET_PATH)
    responses = load_responses()
    if not responses:
        print("no persisted responses; run run-track-a first"); return 1
    report = build_baseline_report(ds, responses)
    persist_report(report)
    m = report["overall_metrics"]
    print("Track A baseline:")
    print(f"  answer_accuracy={m['answer_accuracy']} abstention_accuracy={m['abstention_accuracy']} "
          f"hallucination_rate={m['hallucination_rate']}")
    print(f"  citation_precision={m['citation_precision']} citation_recall={m['citation_recall']}")
    print(f"  retrieval_recall@k={m['retrieval_recall_at_k']} precision@k={m['retrieval_precision_at_k']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    if argv[0] == "validate":
        return cmd_validate()
    if argv[0] == "summary":
        return cmd_summary()
    if argv[0] == "run-track-a":
        return cmd_run_track_a()
    if argv[0] == "baseline-report":
        return cmd_baseline_report()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
