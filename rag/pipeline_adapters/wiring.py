"""
rag/pipeline_adapters/wiring.py
Production wiring for the shared Knowledge Ingestion Pipeline.

Single source of truth that binds the source-agnostic pipeline to production's
configuration (`config/settings.py`) and its concrete adapters. Keeping the
constructors here means `rag/chunking.py` and `rag/store.py` become thin
delegators, and there is exactly one place that decides "production uses these
backends with these settings".

Split factories (`production_chunker`, `production_indexer`) let the chunking
path avoid loading the embedding model, and the build path reuse the existing
`rag.store` embeddings singleton — so migration adds no model loads.
"""
from __future__ import annotations

from typing import Optional

from config.settings import (
    CHROMA_COLLECTION_NAME,
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL,
    EMBEDDING_NORMALIZE,
)
from ingestion.pipeline.config import PipelineConfig
from ingestion.pipeline.pipeline import KnowledgePipeline
from rag.pipeline_adapters.chroma_indexer import ChromaVectorIndex
from rag.pipeline_adapters.hf_embedder import HuggingFaceEmbeddingBackend
from rag.pipeline_adapters.recursive_chunker import RecursiveCharacterChunker


def production_config() -> PipelineConfig:
    """PipelineConfig populated from config/settings.py (production values)."""
    return PipelineConfig(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        embedding_model=EMBEDDING_MODEL,
        embedding_device=EMBEDDING_DEVICE,
        embedding_normalize=EMBEDDING_NORMALIZE,
        collection_name=CHROMA_COLLECTION_NAME,
        distance="cosine",
    )


def production_chunker(config: Optional[PipelineConfig] = None) -> RecursiveCharacterChunker:
    """Chunker only — used by rag/chunking.py (no embedding model loaded)."""
    return RecursiveCharacterChunker(config or production_config())


def production_indexer(embeddings=None, config: Optional[PipelineConfig] = None) -> ChromaVectorIndex:
    """Chroma indexer wired to the production store; pass rag.store embeddings singleton."""
    cfg = config or production_config()
    backend = HuggingFaceEmbeddingBackend(cfg, embeddings=embeddings)
    return ChromaVectorIndex(
        persist_directory=str(CHROMA_DIR),
        collection_name=cfg.collection_name,
        embedding_backend=backend,
        distance=cfg.distance,
    )


def build_production_pipeline(embeddings=None) -> KnowledgePipeline:
    """A ready-to-run KnowledgePipeline using production adapters + settings."""
    cfg = production_config()
    return KnowledgePipeline(
        chunker=production_chunker(cfg),
        indexer=production_indexer(embeddings=embeddings, config=cfg),
        config=cfg,
    )
