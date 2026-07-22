"""
rag/pipeline_adapters/recursive_chunker.py
Chunker adapter — RecursiveCharacterTextSplitter (langchain).

Reproduces `rag/chunking.py`'s historical behaviour EXACTLY so migrating
production changes no chunk boundary, id, or count:
  - same splitter config (chunk_size / chunk_overlap / separators, len-based),
  - same per-chunk `enumerate` index (empty-after-strip chunks are skipped but
    still consume an index, matching the legacy loop),
  - same chunk_id (`document_id_{i:04d}`, where document_id == md5(url)[:8]),
  - same metadata (the document's metadata + chunk_id + chunk_index).
"""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingestion.pipeline.config import PipelineConfig
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.ids import chunk_id as make_chunk_id, content_hash
from ingestion.pipeline.ports import Chunk


class RecursiveCharacterChunker:
    """Implements the ingestion.pipeline.ports.Chunker Protocol."""

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=list(self.config.separators),
            length_function=len,
            is_separator_regex=False,
        )

    def chunk(self, document: KnowledgeDocument) -> list[Chunk]:
        text = (document.text or "").strip()
        if not text:
            return []

        chunks: list[Chunk] = []
        for i, raw in enumerate(self._splitter.split_text(text)):
            chunk_text = raw.strip()
            if not chunk_text:
                continue
            cid = make_chunk_id(document.document_id, i)
            metadata = {**document.metadata, "chunk_id": cid, "chunk_index": i}
            chunks.append(Chunk(
                chunk_id=cid,
                document_id=document.document_id,
                index=i,
                text=chunk_text,
                content_hash=content_hash(chunk_text),
                metadata=metadata,
            ))
        return chunks
