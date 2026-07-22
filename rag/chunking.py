"""
rag/chunking.py
Splits ingested page text into overlapping chunks and wraps them as LangChain Documents.

Chunking strategy:
    RecursiveCharacterTextSplitter tries separators in order — paragraph break
    → newline → sentence end → word — before falling back to a hard character
    split.  This maximises the chance that each chunk ends at a natural semantic
    boundary (a full sentence or paragraph) rather than mid-word.

Chunk parameters (why these numbers):
    chunk_size=500 characters
        Large enough to hold a complete FAQ answer, a full eligibility bullet
        list, or a single application step with its details.  Small enough to
        stay focused on one topic — a chunk that spans three unrelated steps
        will score weakly on every specific query.

    chunk_overlap=75 characters
        ~15% of chunk_size.  Ensures that a sentence split across a boundary
        by the splitter is fully visible in at least one of the two adjacent
        chunks.  Without overlap, a sentence like "The application fee is $70,
        nonrefundable" could appear half in chunk N and half in chunk N+1,
        making both chunks less useful for a fee-related query.

Metadata design:
    All metadata values are primitive types (str, int) because ChromaDB does
    not support nested objects or lists in metadata.  We store links_json as a
    JSON string in faq_rag_module.py; here we keep metadata flat and simple —
    the source URL is sufficient for citation purposes.

    Required metadata keys per chunk:
        title       — page title (for display in retrieval results)
        url         — source URL (for citation / source attribution)
        page_type   — content category (for filtered retrieval)
        chunk_id    — stable unique ID: "{url_hash8}_{index:04d}"
        chunk_index — integer position within the parent page (for diagnostics)

chunk_id design:
    "{md5(url)[:8]}_{index:04d}" — e.g. "a3f9c12b_0003"
    - URL hash: deterministic, filesystem-safe, 8 chars keeps IDs short
    - Zero-padded index: preserves sort order; supports up to 9999 chunks/page
      (more than enough — typical pages produce 20–60 chunks)
    - Stable across re-ingestions as long as chunk_size/overlap don't change
"""

from __future__ import annotations

import time

from langchain_core.documents import Document
from config.settings import CHUNK_SIZE, CHUNK_OVERLAP
from ingestion.pipeline.loaders.pages import page_to_document
from rag.pipeline_adapters.wiring import production_chunker
from obs.ingestion_events import emit_ingestion_page_chunked

# ---------------------------------------------------------------------------
# Chunking parameters
# ---------------------------------------------------------------------------
# CHUNK_SIZE / CHUNK_OVERLAP now live in config/settings.py (Phase 5A) and are
# re-exported here for backward compatibility. The actual splitting is delegated
# to the shared Knowledge Ingestion Pipeline (ingestion/pipeline/) via the
# production chunker adapter (rag/pipeline_adapters/), which reads the same
# settings — so chunk boundaries, ids, and metadata are byte-identical to before.


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_documents(pages: list[dict]) -> list[Document]:
    """
    Split each ingested page into overlapping text chunks with full metadata.

    Each chunk is a LangChain Document with:
        page_content = the chunk text (up to CHUNK_SIZE characters)
        metadata     = {
            "title":            str  — source page title
            "url":              str  — source URL (always present for citation)
            "page_type":        str  — faq | deadlines | eligibility |
                                       application_process | program_application
            "program_name":     str  — canonical program name, "" for generic pages
            "content_category": str  — e.g. department_application, supplemental_application,
                                       program_overview, generic_application, ""
            "chunk_id":         str  — "{url_hash8}_{index:04d}" unique identifier
            "chunk_index":      int  — position within the parent page (0-based)
        }

    Args:
        pages: List of page dicts from ingestion.ingest_pages().
               Each dict must have: url, page_type, title, text.

    Returns:
        Flat list of Document objects across all pages, ready for embedding.
        Empty pages are skipped with a warning.

    Example:
        pages  = ingest_pages()          # 4 page dicts
        docs   = chunk_documents(pages)  # ~120–200 Document objects
        store  = build_vector_store(docs)
    """
    # Delegate the actual splitting to the shared pipeline's production chunker.
    # It reproduces the historical splitter config, chunk ids, and metadata
    # exactly (see rag/pipeline_adapters/recursive_chunker.py), so the returned
    # LangChain Documents are byte-identical to the previous implementation.
    chunker = production_chunker()

    all_docs: list[Document] = []

    for page in pages:
        url               = page.get("url", "")
        page_type         = page.get("page_type", "unknown")
        program_name      = page.get("program_name", "")
        text              = page.get("text", "").strip()

        if not text:
            print(f"[chunking] Skipping empty page: {url}")
            continue

        # page dict → KnowledgeDocument → deterministic Chunks → LangChain Documents.
        _t_chunk = time.perf_counter()
        chunks = chunker.chunk(page_to_document(page))
        page_docs: list[Document] = [
            Document(page_content=c.text, metadata=dict(c.metadata)) for c in chunks
        ]

        _chunk_elapsed = round((time.perf_counter() - _t_chunk) * 1000, 1)
        emit_ingestion_page_chunked(
            url=url, page_type=page_type, program_name=program_name,
            chunks_generated=len(page_docs), chars_in=len(text),
            chunk_elapsed_ms=_chunk_elapsed,
        )
        print(
            f"[chunking] [{page_type}] {len(page_docs)} chunks "
            f"(avg {int(len(text) / max(len(page_docs), 1))} chars each)"
        )
        all_docs.extend(page_docs)

    total_pages = len(pages)
    print(
        f"\n[chunking] Total: {len(all_docs)} chunks across {total_pages} page(s), "
        f"avg {int(sum(len(d.page_content) for d in all_docs) / max(len(all_docs), 1))} "
        f"chars per chunk"
    )
    return all_docs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Sanity-check: ingest pages and print chunk statistics."""
    import sys
    from rag.ingestion import ingest_pages

    print("=" * 60)
    print("CSULB RAG Chunking — sanity check")
    print("=" * 60)

    pages = ingest_pages()
    if not pages:
        print("No pages ingested — cannot test chunking.")
        sys.exit(1)

    docs = chunk_documents(pages)

    if not docs:
        print("No chunks produced — check ingestion output.")
        sys.exit(1)

    print(f"\n{'Page Type':<22} {'Chunks':>7}  {'Min':>5}  {'Max':>5}  {'Avg':>5}")
    print("-" * 55)

    # Group by page_type for the summary table
    by_type: dict[str, list[Document]] = {}
    for d in docs:
        pt = d.metadata.get("page_type", "unknown")
        by_type.setdefault(pt, []).append(d)

    for pt, type_docs in sorted(by_type.items()):
        lengths = [len(d.page_content) for d in type_docs]
        print(
            f"{pt:<22} {len(type_docs):>7}  "
            f"{min(lengths):>5}  {max(lengths):>5}  {int(sum(lengths)/len(lengths)):>5}"
        )

    print(f"\nTotal chunks: {len(docs)}")

    # Show 3 sample chunks with metadata
    print("\n── Sample chunks ──")
    sample_indices = [0, len(docs) // 2, len(docs) - 1]
    for idx in sample_indices:
        d = docs[idx]
        print(f"\n[{d.metadata['page_type']}] chunk_id={d.metadata['chunk_id']}")
        print(f"  url: {d.metadata['url']}")
        print(f"  text ({len(d.page_content)} chars): {d.page_content[:150].strip()}…")
