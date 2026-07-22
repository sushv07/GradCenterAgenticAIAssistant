"""
experiments/rag_vs_finetuning/track_c/retrieve.py
Track C retrieval stage (Phase P10) — runs on the 3.13 retrieval interpreter.

Reuses the FROZEN Track A retrieval pipeline EXACTLY (same embedder, same Chroma
collection, same top_k/threshold from config) — nothing about chunking,
embeddings, or the index is modified. Exposes retrieve_context() plus a CLI that
emits retrieved chunks as JSON, so the MLX inference stage (infer.py, Python 3.9)
can consume grounded context without importing chromadb.

  # single question -> JSON on stdout
  /opt/miniconda3/bin/python3 -m experiments.rag_vs_finetuning.track_c.retrieve \
      --question "Who should I contact for Social Work?"

  # batch -> retrieval bundle file (one JSON object per line)
  /opt/miniconda3/bin/python3 -m experiments.rag_vs_finetuning.track_c.retrieve \
      --questions-file questions.txt --out bundle.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

from experiments.rag_vs_finetuning.track_a.retriever import RETRIEVAL_VERSION, retrieve


@lru_cache(maxsize=1)
def _load_retrieval_stack():
    """Load the frozen embedder + Chroma collection + retrieval params (once)."""
    import chromadb
    from experiments.rag_vs_finetuning.configs.config import load_config
    from experiments.rag_vs_finetuning.embeddings.embedder import SentenceTransformerEmbedder
    cfg = load_config()
    embedder = SentenceTransformerEmbedder(
        model_id=cfg.embedding.model, device=cfg.embedding.device,
        normalize=cfg.embedding.normalize)
    collection = chromadb.PersistentClient(
        path=str(Path.cwd() / cfg.vector_store.persistence_path)
    ).get_collection(cfg.vector_store.collection_name)
    return embedder, collection, cfg.track_a.top_k, cfg.track_a.similarity_threshold


def retrieve_context(question: str, *, top_k: int | None = None,
                     threshold: float | None = None) -> dict:
    embedder, collection, cfg_k, cfg_t = _load_retrieval_stack()
    k = cfg_k if top_k is None else top_k
    t = cfg_t if threshold is None else threshold
    result = retrieve(question, embedder=embedder, collection=collection,
                      top_k=k, threshold=t)
    chunks = [{
        "chunk_id": c.chunk_id, "program_id": c.program_id, "section": c.section,
        "similarity_score": c.similarity_score, "content": c.content,
        "source_ids": [s.source_id for s in c.source_references],
        "source_hashes": [s.content_hash for s in c.source_references],
    } for c in result.retrieved_chunks]
    return {
        "question": question, "chunks": chunks,
        "retrieved_chunk_ids": [c["chunk_id"] for c in chunks],
        "similarity_scores": result.similarity_scores,
        "retrieval_latency_ms": result.retrieval_latency_ms,
        "top_k": k, "threshold": t, "retrieval_version": RETRIEVAL_VERSION,
        "embedding_model": embedder.info.model_id,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Track C retrieval stage")
    ap.add_argument("--question")
    ap.add_argument("--questions-file")
    ap.add_argument("--out")
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args(argv)

    if args.question:
        print(json.dumps(retrieve_context(
            args.question, top_k=args.top_k, threshold=args.threshold),
            ensure_ascii=False))
        return 0
    if args.questions_file:
        questions = [q.strip() for q in Path(args.questions_file).read_text("utf-8").splitlines()
                     if q.strip()]
        bundles = [retrieve_context(q, top_k=args.top_k, threshold=args.threshold)
                   for q in questions]
        out = "\n".join(json.dumps(b, ensure_ascii=False) for b in bundles) + "\n"
        if args.out:
            Path(args.out).write_text(out, "utf-8")
            print(f"wrote {len(bundles)} retrieval bundles -> {args.out}")
        else:
            sys.stdout.write(out)
        return 0
    ap.error("provide --question or --questions-file")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
