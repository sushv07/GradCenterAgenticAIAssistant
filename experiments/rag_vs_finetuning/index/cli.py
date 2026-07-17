"""
experiments/rag_vs_finetuning/index/cli.py
Non-LLM inspection CLI for the isolated experiment index (Phase P6).

    python -m experiments.rag_vs_finetuning.index.cli summary
    python -m experiments.rag_vs_finetuning.index.cli program accountancy
    python -m experiments.rag_vs_finetuning.index.cli chunk accountancy::overview::chunk::000
    python -m experiments.rag_vs_finetuning.index.cli verify

No semantic query / retrieval / LLM here — that belongs to P7.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from experiments.rag_vs_finetuning.configs.config import load_config


def _open():
    import chromadb
    config = load_config()
    root = Path.cwd()
    persist = root / config.vector_store.persistence_path
    client = chromadb.PersistentClient(path=str(persist))
    collection = client.get_or_create_collection(config.vector_store.collection_name)
    return config, collection


def _manifest() -> dict:
    config = load_config()
    p = Path.cwd() / config.corpus.data_root / "manifests" / "index_manifest.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def cmd_summary() -> int:
    config, coll = _open()
    man = _manifest()
    print(f"collection: {config.vector_store.collection_name}")
    print(f"vector_count: {coll.count()}")
    print(f"embedding_model: {man.get('embedding_model')} dim={man.get('embedding_dimension')}")
    print(f"identity: {man.get('collection_identity_hash', 'n/a')}")
    got = coll.get(include=["metadatas"])
    from collections import Counter
    print("by_section:", dict(sorted(Counter(m['section'] for m in got['metadatas']).items())))
    return 0


def cmd_program(program_id: str) -> int:
    _, coll = _open()
    got = coll.get(where={"program_id": program_id}, include=["metadatas", "documents"])
    for cid, md, doc in sorted(zip(got["ids"], got["metadatas"], got["documents"])):
        print(f"{cid} [{md['section']}] {doc[:70]!r}")
    return 0


def cmd_chunk(chunk_id: str) -> int:
    _, coll = _open()
    got = coll.get(ids=[chunk_id], include=["metadatas", "documents"])
    if not got["ids"]:
        print(f"not found: {chunk_id}"); return 1
    md, doc = got["metadatas"][0], got["documents"][0]
    print(f"chunk_id: {chunk_id}")
    print(f"program: {md['program_id']} | section: {md['section']}")
    print(f"source_ids: {md['source_ids']}")
    print(f"source_hashes: {md['source_hashes']}")
    print(f"embedding_model: {md['embedding_model']}")
    print(f"content: {doc}")
    return 0


def cmd_verify() -> int:
    from experiments.rag_vs_finetuning.index.build import verify_collection
    from experiments.rag_vs_finetuning.index.run import load_chunks
    config, coll = _open()
    data_root = Path.cwd() / config.corpus.data_root
    chunks = load_chunks(data_root / "chunks" / "chunks.jsonl")
    result = verify_collection(coll, chunks)
    print("verify: OK", result)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "summary":
        return cmd_summary()
    if cmd == "program" and rest:
        return cmd_program(rest[0])
    if cmd == "chunk" and rest:
        return cmd_chunk(rest[0])
    if cmd == "verify":
        return cmd_verify()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
