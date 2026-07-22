"""
rag/pipeline_adapters/hf_embedder.py
Embedding adapter — HuggingFace sentence-transformers via langchain.

Implements the ingestion.pipeline.ports.EmbeddingBackend Protocol and owns the
embedding model (production default: all-MiniLM-L6-v2, cpu, normalized). It
exposes the underlying langchain embeddings object so the Chroma indexer can use
it directly — that is the "Embedder → Indexer" edge, kept as composition so the
indexer is the only place that talks to the vector store.

To avoid loading the model twice in production, callers may inject the existing
`rag.store.get_embeddings()` singleton; otherwise one is constructed from config.
"""
from __future__ import annotations

from typing import Optional, Sequence

from langchain_community.embeddings import HuggingFaceEmbeddings

from ingestion.pipeline.config import PipelineConfig


class HuggingFaceEmbeddingBackend:
    """Implements the ingestion.pipeline.ports.EmbeddingBackend Protocol."""

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        embeddings: Optional[HuggingFaceEmbeddings] = None,
    ) -> None:
        self.config = config or PipelineConfig()
        # Reuse an injected embeddings singleton when provided (no double load).
        self._embeddings = embeddings or HuggingFaceEmbeddings(
            model_name=self.config.embedding_model,
            model_kwargs={"device": self.config.embedding_device},
            encode_kwargs={"normalize_embeddings": self.config.embedding_normalize},
        )

    @property
    def model_id(self) -> str:
        return self.config.embedding_model

    @property
    def langchain_embeddings(self) -> HuggingFaceEmbeddings:
        """The underlying langchain embeddings, for the vector-store adapter."""
        return self._embeddings

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(list(texts))
