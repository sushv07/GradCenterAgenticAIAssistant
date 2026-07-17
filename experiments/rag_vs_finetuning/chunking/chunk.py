"""
experiments/rag_vs_finetuning/chunking/chunk.py
Deterministic, section-aware chunking (Phase P6).

Policy (character-based; unit is explicitly characters, never tokens):
  - if a projected document's content fits within chunk_size_characters, it is
    retained as ONE chunk (the projected sections are already coherent);
  - otherwise it is split deterministically into fixed-size character windows
    with chunk_overlap_characters of overlap.

No LangChain / Chroma / model / network dependencies. Identical input + config
always yields identical chunks, IDs, offsets, ordering, and checksums.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from experiments.rag_vs_finetuning.chunking.models import RetrievalChunk
from experiments.rag_vs_finetuning.projection.models import (
    RetrievalDocument, SourceReference,
)

CHUNKING_VERSION = "chunking-0.1"


@dataclass(frozen=True)
class ChunkConfig:
    version: str = CHUNKING_VERSION
    unit: str = "characters"
    chunk_size_characters: int = 500
    chunk_overlap_characters: int = 75

    def as_dict(self) -> dict:
        return {
            "version": self.version, "unit": self.unit,
            "chunk_size_characters": self.chunk_size_characters,
            "chunk_overlap_characters": self.chunk_overlap_characters,
        }


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _word_count(text: str) -> int:
    return len(text.split())


def _windows(length: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """Deterministic [start, end) character windows with overlap."""
    if length <= size:
        return [(0, length)]
    step = max(1, size - overlap)
    spans: list[tuple[int, int]] = []
    start = 0
    while start < length:
        end = min(start + size, length)
        spans.append((start, end))
        if end == length:
            break
        start += step
    return spans


def chunk_document(doc: RetrievalDocument, config: ChunkConfig) -> list[RetrievalChunk]:
    content = doc.content
    spans = _windows(len(content), config.chunk_size_characters, config.chunk_overlap_characters)
    chunks: list[RetrievalChunk] = []
    for idx, (start, end) in enumerate(spans):
        piece = content[start:end]
        chunk_id = f"{doc.document_id}::chunk::{idx:03d}"
        meta = dict(doc.metadata)
        meta.update({"chunk_id": chunk_id, "chunk_index": idx,
                     "chunking_version": config.version})
        chunks.append(RetrievalChunk(
            chunk_id=chunk_id, document_id=doc.document_id, program_id=doc.program_id,
            program_level=doc.program_level, title=doc.title, section=doc.section,
            content=piece, chunk_index=idx, character_start=start, character_end=end,
            token_count=_word_count(piece),
            source_references=[SourceReference(**s.model_dump()) for s in doc.source_references],
            volatility=doc.volatility, freshness_status=doc.freshness_status,
            metadata=meta, canonical_record_hash=doc.canonical_record_hash,
            projection_version=doc.projection_version, chunking_version=config.version,
            content_hash=_sha256(piece),
        ))
    return chunks


def chunk_documents(documents: list[RetrievalDocument], config: ChunkConfig) -> list[RetrievalChunk]:
    out: list[RetrievalChunk] = []
    for doc in sorted(documents, key=lambda d: d.document_id):
        out.extend(chunk_document(doc, config))
    out.sort(key=lambda c: c.chunk_id)
    return out


def load_projected_documents(documents_jsonl: Path) -> list[RetrievalDocument]:
    lines = Path(documents_jsonl).read_text(encoding="utf-8").strip().splitlines()
    return [RetrievalDocument.model_validate_json(l) for l in lines if l.strip()]


def aggregate_chunk_checksum(chunks: list[RetrievalChunk]) -> str:
    payload = "\n".join(
        json.dumps(c.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for c in sorted(chunks, key=lambda c: c.chunk_id))
    return _sha256(payload)


def build_chunk_manifest(chunks: list[RetrievalChunk], *, config: ChunkConfig,
                         projection_version: str, projection_checksum: str,
                         document_count: int, generated_from: str) -> dict:
    from collections import Counter
    by_section = Counter(c.section for c in chunks)
    by_program = Counter(c.program_id for c in chunks)
    return {
        "chunking_version": config.version,
        "projection_version": projection_version,
        "projection_checksum": projection_checksum,
        "configuration": config.as_dict(),
        "document_count": document_count,
        "chunk_count": len(chunks),
        "chunks_by_section": dict(sorted(by_section.items())),
        "chunks_by_program": dict(sorted(by_program.items())),
        "aggregate_chunk_checksum": aggregate_chunk_checksum(chunks),
        "generated_from": generated_from,
        "chunks": [
            {"chunk_id": c.chunk_id, "document_id": c.document_id,
             "program_id": c.program_id, "section": c.section,
             "chunk_checksum": c.content_hash,
             "source_hashes": [s.content_hash for s in c.source_references]}
            for c in sorted(chunks, key=lambda c: c.chunk_id)
        ],
    }


def persist_chunks(chunks: list[RetrievalChunk], chunks_jsonl: Path) -> None:
    chunks_jsonl = Path(chunks_jsonl)
    chunks_jsonl.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(c.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
             for c in sorted(chunks, key=lambda c: c.chunk_id)]
    chunks_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
