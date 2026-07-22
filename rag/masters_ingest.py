"""
rag/masters_ingest.py
Feed master's KnowledgeDocuments through the SHARED production pipeline (Phase 4).

Integration, not redesign: master's documents go through the exact same
KnowledgePipeline (validate → chunk → embed → index) as every other source. The
only new code here is a thin, store-configurable factory so a pilot can index
into an isolated Chroma store instead of the deployed production one — the code
PATH is identical (same RecursiveCharacterChunker, HuggingFaceEmbeddingBackend,
ChromaVectorIndex, and KnowledgePipeline). No special cases, no forked path.

Default `mode="upsert"` makes ingestion idempotent (deterministic chunk IDs are
overwritten in place) and additive (it does not wipe other sources in the
collection, unlike the full-rebuild `mode="build"`).
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from config.settings import CHROMA_DIR
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.pipeline import IngestionSummary, KnowledgePipeline
from rag.pipeline_adapters.chroma_indexer import ChromaVectorIndex
from rag.pipeline_adapters.hf_embedder import HuggingFaceEmbeddingBackend
from rag.pipeline_adapters.recursive_chunker import RecursiveCharacterChunker
from rag.pipeline_adapters.wiring import production_config


def build_masters_pipeline(
    *,
    embeddings: Any = None,
    persist_directory: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> KnowledgePipeline:
    """A KnowledgePipeline wired with production adapters + settings.

    `persist_directory`/`collection_name` default to the production store; a pilot
    passes an isolated location so it does not disturb the deployed collection.
    """
    cfg = production_config()
    backend = HuggingFaceEmbeddingBackend(cfg, embeddings=embeddings)
    indexer = ChromaVectorIndex(
        persist_directory=str(persist_directory or CHROMA_DIR),
        collection_name=collection_name or cfg.collection_name,
        embedding_backend=backend,
        distance=cfg.distance,
    )
    return KnowledgePipeline(RecursiveCharacterChunker(cfg), indexer, cfg)


def ingest_masters_documents(
    documents: Sequence[KnowledgeDocument] | Iterable[KnowledgeDocument],
    *,
    pipeline: Optional[KnowledgePipeline] = None,
    mode: str = "upsert",
    prune: bool = False,
    embeddings: Any = None,
    persist_directory: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> tuple[Any, IngestionSummary]:
    """Ingest master's KnowledgeDocuments through the shared pipeline.

    Pass an existing `pipeline` (e.g. with an in-memory index for tests), or let
    a production-wired one be built. Returns (index_handle, IngestionSummary).
    """
    pipeline = pipeline or build_masters_pipeline(
        embeddings=embeddings, persist_directory=persist_directory,
        collection_name=collection_name)
    return pipeline.run(documents, mode=mode, prune=prune)
