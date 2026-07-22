"""
ingestion/pipeline/ports.py
The Chunk value object and the pipeline's ports (Protocols).

"Ports & adapters": the pipeline depends only on these abstract Protocols, never
on a concrete text splitter, embedding model, or vector store. Infra adapters
(in `rag/pipeline_adapters/`) satisfy them structurally — no subclassing needed.
This is what makes the vector store swappable (Chroma today; Pinecone/Qdrant/
pgvector later) without touching chunking, validation, metadata, or orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from ingestion.pipeline.documents import KnowledgeDocument


@dataclass(frozen=True)
class Chunk:
    """A single retrievable unit: text + flat metadata + stable identity.

    `metadata` already contains everything to be stored in the vector store
    (including `chunk_id`/`chunk_index`); `document_id`/`content_hash` are kept
    as first-class fields to drive grouping and idempotency.
    """

    chunk_id: str
    document_id: str
    index: int
    text: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class KnowledgeLoader(Protocol):
    """Adapts a specific knowledge source into KnowledgeDocuments."""

    def load(self) -> Iterable[KnowledgeDocument]: ...


@runtime_checkable
class Chunker(Protocol):
    """Splits one KnowledgeDocument into deterministic, ordered Chunks."""

    def chunk(self, document: KnowledgeDocument) -> list[Chunk]: ...


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Turns text into vectors. Owns the model; knows nothing about the store."""

    @property
    def model_id(self) -> str: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorIndex(Protocol):
    """The ONLY port that knows a concrete vector store exists.

    `build` fully (re)creates the collection; `upsert`/`delete`/`existing_ids`
    support idempotent, incremental indexing without a full rebuild.
    """

    def build(self, chunks: Sequence[Chunk]) -> Any: ...

    def upsert(self, chunks: Sequence[Chunk]) -> int: ...

    def delete(self, chunk_ids: Sequence[str]) -> int: ...

    def existing_ids(self) -> set[str]: ...
