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

import os
from typing import Any, Callable, Iterable, Optional, Sequence

from config.settings import CHROMA_DIR
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.pipeline import IngestionSummary, KnowledgePipeline
from rag.pipeline_adapters.chroma_indexer import ChromaVectorIndex
from rag.pipeline_adapters.hf_embedder import HuggingFaceEmbeddingBackend
from rag.pipeline_adapters.recursive_chunker import RecursiveCharacterChunker
from rag.pipeline_adapters.wiring import production_config

# Config (env feature-flag idiom, matching agents/llm_synthesizer.py). Opt-in by
# default so the deployed build and tests are unchanged until explicitly enabled;
# set MASTERS_INGESTION_ENABLED=true to make a normal production rebuild include
# master's knowledge — no code change required.
MASTERS_INGESTION_ENABLED = os.getenv("MASTERS_INGESTION_ENABLED", "false").lower() == "true"
MASTERS_INGESTION_DEPTH = int(os.getenv("MASTERS_INGESTION_DEPTH", "1"))


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


# ---------------------------------------------------------------------------
# Production build hook (Phase 5)
# ---------------------------------------------------------------------------

def acquire_masters_documents(
    *,
    depth: Optional[int] = None,
    index_html: Any = None,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> list[KnowledgeDocument]:
    """Full master's acquisition → validated KnowledgeDocuments.

    directory → nested discovery → extraction → conversion, reusing the Phase 1-3
    modules unchanged. `index_html`/`fetch_fn` are injectable for offline tests;
    in production the live master's directory is fetched.
    """
    from ingestion.masters.discovery import discover_from_html
    from rag.masters_discovery import (
        MASTERS_INDEX_URL, apply_seed_overrides, discover_masters_program_pages,
    )
    from rag.masters_extraction import build_masters_documents, directory_card_documents

    if fetch_fn is None:
        from rag.ingestion import fetch_page
        fetch_fn = fetch_page

    html = index_html if index_html is not None else fetch_fn(MASTERS_INDEX_URL)
    if not html:
        return []
    manifest = discover_from_html(html, source_url=MASTERS_INDEX_URL)
    # Phase 9B: remap directory seeds with verified replacements (the CLA CMS
    # decommission left 14 seeds redirecting to a college homepage). Applied
    # before nested discovery AND card building, so crawl seeds and each
    # card's "Official program page" line both cite the live page. Fail-safe:
    # no config -> no changes.
    programs, _applied = apply_seed_overrides(manifest.programs)
    result = discover_masters_program_pages(
        programs, depth=depth or MASTERS_INGESTION_DEPTH, fetch_fn=fetch_fn)
    docs, _summary = build_masters_documents(result.pages, programs, fetch_fn=fetch_fn)
    # Phase 7: directory-card facts (advisor / deadlines) — previously only in
    # the un-indexed DiscoveryManifest; the advisor eval category scored 0%.
    docs = docs + directory_card_documents(programs, MASTERS_INDEX_URL)
    return docs


def masters_build_documents(
    *,
    enabled: Optional[bool] = None,
    depth: Optional[int] = None,
    chunker=None,
    index_html: Any = None,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> list:
    """Production-build hook: master's knowledge as chunked LangChain Documents.

    Returns [] when disabled (default) or if acquisition raises — FAIL-SAFE, so a
    master's failure never breaks the base production build. The returned
    Documents are chunked with the SAME production chunker used for every other
    source, then appended to the build's document list (one unified index).
    """
    from langchain_core.documents import Document

    if enabled is None:
        enabled = MASTERS_INGESTION_ENABLED
    if not enabled:
        return []

    try:
        knowledge_docs = acquire_masters_documents(
            depth=depth, index_html=index_html, fetch_fn=fetch_fn)
        chunker = chunker or RecursiveCharacterChunker(production_config())
        out: list = []
        for kd in knowledge_docs:
            for chunk in chunker.chunk(kd):
                out.append(Document(page_content=chunk.text, metadata=dict(chunk.metadata)))
        print(f"[masters] production build: {len(knowledge_docs)} documents "
              f"-> {len(out)} chunks")
        return out
    except Exception as exc:  # never break the base build
        print(f"[masters] acquisition failed, skipping master's source: {exc}")
        return []
