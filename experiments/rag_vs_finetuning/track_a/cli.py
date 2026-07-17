"""
experiments/rag_vs_finetuning/track_a/cli.py
Track A CLI (Phase P7).

    python -m experiments.rag_vs_finetuning.track_a.cli ask "<question>"
    python -m experiments.rag_vs_finetuning.track_a.cli retrieve "<question>"
    python -m experiments.rag_vs_finetuning.track_a.cli trace
    python -m experiments.rag_vs_finetuning.track_a.cli verify
"""
from __future__ import annotations

import sys
from pathlib import Path

from experiments.rag_vs_finetuning.configs.config import load_config


def _open_collection():
    import chromadb
    cfg = load_config()
    persist = Path.cwd() / cfg.vector_store.persistence_path
    client = chromadb.PersistentClient(path=str(persist))
    return cfg, client.get_collection(cfg.vector_store.collection_name)


def _embedder():
    from experiments.rag_vs_finetuning.embeddings.embedder import SentenceTransformerEmbedder
    cfg = load_config()
    return SentenceTransformerEmbedder(
        model_id=cfg.embedding.model, device=cfg.embedding.device,
        normalize=cfg.embedding.normalize, batch_size=cfg.embedding.batch_size)


def _llm(cfg):
    from experiments.rag_vs_finetuning.track_a.llm import OllamaLLM
    t = cfg.track_a.llm
    return OllamaLLM(base_url=t.base_url, model=t.model, temperature=t.temperature,
                     top_p=t.top_p, max_tokens=t.max_tokens, seed=t.seed)


def cmd_retrieve(question: str) -> int:
    from experiments.rag_vs_finetuning.track_a.retriever import retrieve
    cfg, coll = _open_collection()
    res = retrieve(question, embedder=_embedder(), collection=coll,
                   top_k=cfg.track_a.top_k, threshold=cfg.track_a.similarity_threshold)
    print(f"query: {question}")
    for c in res.retrieved_chunks:
        print(f"  {c.chunk_id} [{c.program_id}/{c.section}] sim={c.similarity_score} "
              f"src={[s.source_id for s in c.source_references]}")
    print(f"latency_ms: {res.retrieval_latency_ms}")
    return 0


def cmd_ask(question: str) -> int:
    from experiments.rag_vs_finetuning.track_a.pipeline import ask
    from experiments.rag_vs_finetuning.track_a.trace import persist_trace
    cfg, coll = _open_collection()
    trace = ask(question, embedder=_embedder(), collection=coll, llm=_llm(cfg),
                top_k=cfg.track_a.top_k, threshold=cfg.track_a.similarity_threshold)
    persist_trace(trace, Path.cwd() / cfg.track_a.traces_path)
    print(f"Q: {question}")
    print(f"A: {trace.answer}")
    print(f"insufficient_evidence: {trace.insufficient_evidence}")
    print("citations:")
    for c in trace.citations:
        print(f"  - {c.chunk_id} [{c.program_id}/{c.section}] sources={c.source_ids}")
    print(f"latency: retrieval={trace.retrieval_latency_ms}ms "
          f"generation={trace.generation_latency_ms}ms")
    return 0


def cmd_trace() -> int:
    from experiments.rag_vs_finetuning.track_a.trace import load_traces
    cfg = load_config()
    traces = load_traces(Path.cwd() / cfg.track_a.traces_path)
    print(f"traces: {len(traces)}")
    for t in traces[-10:]:
        print(f"  Q: {t.question[:50]!r} -> insufficient={t.insufficient_evidence} "
              f"citations={len(t.citations)} model={t.model}")
    return 0


def cmd_verify() -> int:
    from experiments.rag_vs_finetuning.freeze.freeze import verify_frozen_corpus
    from experiments.rag_vs_finetuning.index.build import verify_collection
    from experiments.rag_vs_finetuning.index.run import load_chunks
    cfg, coll = _open_collection()
    data_root = Path.cwd() / cfg.corpus.data_root
    verify_frozen_corpus(data_root)
    chunks = load_chunks(data_root / "chunks" / "chunks.jsonl")
    print("frozen corpus: OK")
    print("collection:", verify_collection(coll, chunks))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "ask" and rest:
        return cmd_ask(" ".join(rest))
    if cmd == "retrieve" and rest:
        return cmd_retrieve(" ".join(rest))
    if cmd == "trace":
        return cmd_trace()
    if cmd == "verify":
        return cmd_verify()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
