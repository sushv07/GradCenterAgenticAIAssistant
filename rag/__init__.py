"""
rag/__init__.py
Multi-source RAG package for the CSULB Graduate Center AI Assistant.

Public API — import from here, not from submodules directly:

    from rag.retriever import retrieve, retrieve_multi
    from rag.store import get_or_build_store, invalidate_store
    from rag.ingestion import PAGE_SOURCES, ingest_pages
    from rag.chunking import chunk_documents

Pipeline summary:
    ingest_pages()       → fetch + clean 4 CSULB pages
    chunk_documents()    → split into overlapping chunks with metadata
    get_or_build_store() → embed + persist to ChromaDB (or load existing)
    retrieve(query)      → cosine similarity search → ranked result dicts

No OpenAI dependency anywhere in this package.
Embeddings: all-MiniLM-L6-v2 (sentence-transformers, local CPU).
Vector store: ChromaDB persisted under ./chroma_db/.
"""

from rag.retriever import retrieve, retrieve_multi
from rag.store import get_or_build_store, invalidate_store
from rag.ingestion import PAGE_SOURCES, ingest_pages
from rag.chunking import chunk_documents

__all__ = [
    "retrieve",
    "retrieve_multi",
    "get_or_build_store",
    "invalidate_store",
    "PAGE_SOURCES",
    "ingest_pages",
    "chunk_documents",
]
