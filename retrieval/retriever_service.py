"""
retrieval/retriever_service.py
Phase 4B — unified Retriever abstraction.

Problem this solves:
    Today, callers depend directly on concrete retrieval implementations —
    `from rag import retrieve` (ChromaDB vector search), `from retrieval.query_handler
    import handle_query` (keyword scoring), `from retrieval.advisor_retrieval import
    find_advisor` (RapidFuzz fuzzy match), `from retrieval.faq_rag_module import
    faq_rag_lookup` (a second, independent in-memory Chroma store). Each has its
    own input/output shape. Swapping or adding a backend means touching every
    caller.

What this module does:
    Defines one interface — Retriever.retrieve(query, *, filters, top_k, min_score)
    -> list[RetrievedChunk] — and one concrete implementation, ChromaRetriever,
    which wraps rag.retriever.retrieve() unchanged. No retrieval algorithm,
    embedding model, Chroma configuration, or scoring logic is modified here;
    this module only normalizes the call shape and the return shape.

What this module deliberately does NOT do (see ARCHITECTURE_ANALYSIS.md /
Phase 4A and the Phase 4B task non-goals):
    - It does not change rag/'s retrieval quality, thresholds, or embeddings.
    - It does not migrate retrieval/query_handler.py, retrieval/advisor_retrieval.py,
      or retrieval/faq_rag_module.py yet — see module docstring "Future Readiness"
      notes in architecture review output for the planned migration order.
    - It does not delete or disable any existing retrieval code path.

Usage:
    from retrieval.retriever_service import retrieve
    chunks = retrieve("what GPA do I need?", filters={"page_type": "eligibility"}, top_k=3)
    # chunks: list[RetrievedChunk] — each has text/title/url/score/metadata
"""
from __future__ import annotations

from typing import Optional, Protocol

from contracts.response_types import RetrievedChunk
from rag.retriever import retrieve as _chroma_retrieve


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class Retriever(Protocol):
    """
    Structural interface every retrieval backend implements.

    filters is a generic, backend-interpreted dict (e.g. {"page_type": "deadlines",
    "program_name": "..."}) rather than named parameters, so a future backend
    (Pinecone, pgvector, Azure AI Search) can accept the same call shape even
    if it only honors a subset of filter keys, or maps them to a different
    underlying query mechanism (metadata filter, SQL WHERE clause, etc.).
    """

    def retrieve(
        self,
        query: str,
        *,
        filters:   Optional[dict] = None,
        top_k:     Optional[int]  = None,
        min_score: Optional[float] = None,
    ) -> list[RetrievedChunk]:
        ...


# ---------------------------------------------------------------------------
# Concrete backend — wraps the existing ChromaDB pipeline unchanged
# ---------------------------------------------------------------------------

# Known filter keys this backend understands today. Unknown keys are ignored
# (mirrors rag.retriever.retrieve()'s own permissive handling of an unknown
# page_type — silently skipped rather than raising).
_KNOWN_FILTER_KEYS = frozenset({"page_type", "program_name"})


class ChromaRetriever:
    """
    Retriever implementation backed by rag/'s persistent ChromaDB store.

    This is a pure wrapper: every call delegates to rag.retriever.retrieve()
    with the exact same arguments it would have received directly. No
    scoring, threshold, or embedding behavior is changed.
    """

    def retrieve(
        self,
        query: str,
        *,
        filters:   Optional[dict] = None,
        top_k:     Optional[int]  = None,
        min_score: Optional[float] = None,
    ) -> list[RetrievedChunk]:
        filters = filters or {}
        kwargs: dict = {}
        if "page_type" in filters:
            kwargs["page_type"] = filters["page_type"]
        if "program_name" in filters:
            kwargs["program_name"] = filters["program_name"]
        if top_k is not None:
            kwargs["k"] = top_k
        if min_score is not None:
            kwargs["min_score"] = min_score

        raw_results = _chroma_retrieve(query, **kwargs)
        return [_to_retrieved_chunk(r) for r in raw_results]


def _to_retrieved_chunk(raw: dict) -> RetrievedChunk:
    """Normalize one rag.retriever.retrieve() result dict into RetrievedChunk."""
    metadata = {
        k: v for k, v in raw.items()
        if k not in ("text", "title", "url", "score")
    }
    return RetrievedChunk(
        text=raw.get("text", ""),
        title=raw.get("title", ""),
        url=raw.get("url", ""),
        score=raw.get("score", 0.0),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Default instance + module-level convenience function
#
# The rest of the codebase calls retrieval functions directly (rag.retrieve,
# tools.search_rag, retrieval.advisor_retrieval.find_advisor) rather than
# instantiating classes — this free function matches that existing calling
# convention so migrated call sites read the same way they always have.
# ---------------------------------------------------------------------------

_default_retriever: Retriever = ChromaRetriever()


def retrieve(
    query: str,
    *,
    filters:   Optional[dict] = None,
    top_k:     Optional[int]  = None,
    min_score: Optional[float] = None,
) -> list[RetrievedChunk]:
    """
    Retrieve normalized chunks for a query via the default Retriever backend.

    Args:
        query:     User query string.
        filters:   Backend-interpreted filter dict. Today: {"page_type": ...,
                   "program_name": ...} — passed straight through to the
                   ChromaDB metadata filter, unchanged from rag.retriever.retrieve().
        top_k:     Maximum number of results. None uses the backend's own
                   default (rag.retriever.retrieve()'s default k=3).
        min_score: Minimum relevance score. None uses the backend's own
                   default (rag.retriever.MIN_RELEVANCE = 0.30).

    Returns:
        list[RetrievedChunk] — see contracts.response_types.RetrievedChunk.
    """
    return _default_retriever.retrieve(
        query, filters=filters, top_k=top_k, min_score=min_score,
    )
