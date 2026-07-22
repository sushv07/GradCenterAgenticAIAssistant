"""
rag/pipeline_adapters/chroma_indexer.py
Vector-store adapter — ChromaDB via langchain.

The ONLY module in the pipeline that knows a concrete vector store exists.
Swapping to Pinecone/Qdrant/pgvector later means writing a sibling adapter that
satisfies the same `ingestion.pipeline.ports.VectorIndex` Protocol — nothing in
chunking, embedding, metadata, validation, or orchestration changes.

Production parity: `build` / `build_from_langchain_documents` reproduce
`rag/store.build_vector_store`'s call exactly (`Chroma.from_documents(...,
embedding=..., collection_metadata={"hnsw:space": "cosine"})`), so the store the
retriever reads is unchanged. `upsert`/`delete`/`existing_ids` add idempotent,
incremental indexing (Phase 6) without altering the default full-rebuild path.
"""
from __future__ import annotations

from typing import Optional, Sequence

from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from ingestion.pipeline.ports import Chunk
from rag.pipeline_adapters.hf_embedder import HuggingFaceEmbeddingBackend


class ChromaVectorIndex:
    """Implements the ingestion.pipeline.ports.VectorIndex Protocol."""

    def __init__(
        self,
        persist_directory: str,
        collection_name: str,
        embedding_backend: HuggingFaceEmbeddingBackend,
        distance: str = "cosine",
    ) -> None:
        self.persist_directory = str(persist_directory)
        self.collection_name = collection_name
        self._embeddings = embedding_backend.langchain_embeddings
        self.distance = distance
        self.handle: Optional[Chroma] = None

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _to_documents(chunks: Sequence[Chunk]) -> list[Document]:
        return [Document(page_content=c.text, metadata=dict(c.metadata)) for c in chunks]

    def _load(self) -> Chroma:
        if self.handle is None:
            self.handle = Chroma(
                persist_directory=self.persist_directory,
                collection_name=self.collection_name,
                embedding_function=self._embeddings,
            )
        return self.handle

    # -- VectorIndex port ---------------------------------------------------
    def build_from_langchain_documents(self, documents: Sequence[Document]) -> Chroma:
        """Full (re)create from ready-made langchain Documents (production path)."""
        self.handle = Chroma.from_documents(
            documents=list(documents),
            embedding=self._embeddings,
            persist_directory=self.persist_directory,
            collection_name=self.collection_name,
            collection_metadata={"hnsw:space": self.distance},
        )
        return self.handle

    def build(self, chunks: Sequence[Chunk]) -> Chroma:
        """Full (re)create from pipeline Chunks (generic path)."""
        return self.build_from_langchain_documents(self._to_documents(chunks))

    def upsert(self, chunks: Sequence[Chunk]) -> int:
        """Idempotent add/update by deterministic chunk_id."""
        if not chunks:
            return 0
        store = self._load()
        docs = self._to_documents(chunks)
        store.add_documents(docs, ids=[c.chunk_id for c in chunks])
        return len(docs)

    def delete(self, chunk_ids: Sequence[str]) -> int:
        ids = list(chunk_ids)
        if not ids:
            return 0
        self._load()._collection.delete(ids=ids)
        return len(ids)

    def existing_ids(self) -> set[str]:
        try:
            return set(self._load()._collection.get(include=[]).get("ids", []))
        except Exception:
            return set()
