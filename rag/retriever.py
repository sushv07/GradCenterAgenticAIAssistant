"""
rag/retriever.py
Query interface for the multi-source CSULB RAG vector store.

Retrieval flow:
    1.  Ensure the vector store is loaded (or trigger a build if missing).
    2.  Embed the user query using the same all-MiniLM-L6-v2 model.
    3.  Find the top (k * 2) most similar document chunks via cosine similarity.
    4.  Filter out chunks scoring below MIN_RELEVANCE.
    5.  Return up to k result dicts sorted by score descending.

Similarity score interpretation (cosine, hnsw:space=cosine):
    1.0 = vectors are identical (perfect match)
    0.8+ = strong semantic match
    0.5–0.8 = moderate relevance
    0.3–0.5 = weak match but may still be useful context
    < 0.30 = below threshold — treated as off-topic / not in scope

MIN_RELEVANCE = 0.30:
    Same threshold as faq_rag_module.py (_MIN_RELEVANCE = 0.30).
    Empirically this rejects clearly unrelated queries while accepting
    paraphrased or partial questions about CSULB grad admissions.

Over-fetching (k * 2 candidates):
    We fetch more candidates than k before applying the threshold so we can
    return up to k high-quality results even when some candidates fall below
    the cutoff.  The caller always gets at most k results.

Optional page_type filter:
    retrieve(query, page_type="eligibility") restricts the search to chunks
    from that source only.  Useful for intent-aware routing:
        "what GPA do I need?" → page_type="eligibility"
        "when is the deadline?" → page_type="deadlines"
    retrieve() without page_type searches across all 4 sources.

retrieve_multi():
    Fetches up to k_per_type results from each page type and returns them
    grouped.  Useful when you want broad coverage across all sources
    (e.g. surfacing both FAQ and eligibility results for an admissions query).
"""

from __future__ import annotations

import time
from typing import Optional

from rag.store import get_or_build_store
from gradcenter_logging import emit
from telemetry.tracing import set_attributes, span, traced
from config.settings import (
    RETRIEVAL_MIN_RELEVANCE as MIN_RELEVANCE,
    RETRIEVAL_DEFAULT_TOP_K as _DEFAULT_TOP_K,
)
from obs.retrieval_events import (
    emit_retrieval_started,
    emit_retrieval_vector_search,
    emit_retrieval_filtering,
    emit_retrieval_completed,
    emit_retrieval_failed,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# MIN_RELEVANCE now lives in config/settings.py (Phase 5A) — imported above
# under its original local name. Minimum cosine similarity to include in
# results; queries with no chunks meeting this threshold are out-of-scope.

# Valid page_type values — mirrors PAGE_SOURCES + PROGRAM_SOURCES in ingestion.py.
PAGE_TYPES = frozenset({
    "faq", "deadlines", "eligibility", "application_process", "program_application"
})


# ---------------------------------------------------------------------------
# Core retrieval
# ---------------------------------------------------------------------------

@traced("rag.retrieve")
def retrieve(
    query:        str,
    k:            int   = _DEFAULT_TOP_K,
    min_score:    float = MIN_RELEVANCE,
    page_type:    Optional[str] = None,
    program_name: Optional[str] = None,
) -> list[dict]:
    """
    Retrieve the top-k most relevant chunks for a query.

    Args:
        query:        User query string.  Embedded with all-MiniLM-L6-v2.
        k:            Maximum number of results to return.
                      Internally fetches k*2 candidates before score filtering.
        min_score:    Minimum cosine similarity to include.  Default 0.30.
        page_type:    If provided, restrict search to one source type.
                      Must be one of: "faq", "deadlines", "eligibility",
                      "application_process", "program_application".
                      Unknown values are ignored.
        program_name: If provided, restrict to chunks from one specific program.
                      Use canonical names like "Physical Therapy (DPT)".
                      Can be combined with page_type for a compound filter.

    Returns:
        List of result dicts, sorted by score descending, at most k items:
        [
            {
                "text":               str,    chunk text (up to ~500 chars)
                "title":              str,    source page title
                "url":                str,    source URL — use this for citations
                "page_type":          str,    faq | deadlines | eligibility | application_process | program_application
                "content_category":   str,    department_application | supplemental_application | …
                "parent_program_url": str,    "" for seed pages; seed URL for nested subpages
                "workflow_priority":  int,    1–6 (1=most specific)
                "score":              float,  cosine similarity in [0.0, 1.0]
                "chunk_id":           str,    stable chunk identifier
            },
            ...
        ]

        Returns [] when:
          - query is empty or whitespace
          - vector store is unavailable (build failed)
          - no chunks meet the min_score threshold

    Design notes:
        We fetch k*2 candidates from ChromaDB, apply the threshold, then
        take the top k.  This is cheaper than fetching only k and getting
        all of them below threshold (requiring another round-trip).

        similarity_search_with_relevance_scores() already returns results
        sorted by score descending; we re-sort after filtering to be safe.
    """
    if not query or not query.strip():
        return []

    _t_pipeline_start = time.perf_counter()  # Phase 8B — total pipeline timer
                                              # for retrieval.completed/.failed;
                                              # observability only, never read
                                              # by any retrieval decision.

    emit_retrieval_started(query, k, min_score, page_type, program_name)

    store = get_or_build_store()
    if store is None:
        print("[retriever] Vector store unavailable — cannot retrieve")
        emit_retrieval_failed(
            "store_unavailable",
            elapsed_ms=round((time.perf_counter() - _t_pipeline_start) * 1000, 1),
        )
        return []

    # Build ChromaDB metadata filter.
    # Single-field: {"field": {"$eq": value}}
    # Compound:     {"$and": [{"field1": {"$eq": v1}}, {"field2": {"$eq": v2}}]}
    where_filter: Optional[dict] = None
    filter_clauses: list[dict] = []

    if page_type:
        if page_type not in PAGE_TYPES:
            print(f"[retriever] Unknown page_type '{page_type}' — ignoring filter")
        else:
            filter_clauses.append({"page_type": {"$eq": page_type}})

    if program_name:
        filter_clauses.append({"program_name": {"$eq": program_name}})

    if len(filter_clauses) == 1:
        where_filter = filter_clauses[0]
    elif len(filter_clauses) > 1:
        where_filter = {"$and": filter_clauses}

    # Over-fetch to have room for threshold filtering
    fetch_k = k * 2

    # Build optional fields once — used in both the success and exception emit paths
    _opt: dict = {"k_requested": fetch_k}
    if page_type and page_type in PAGE_TYPES:
        _opt["page_type"] = page_type
    if program_name:
        _opt["program_name"] = program_name

    _t0 = time.perf_counter()
    # vectordb.query — the ChromaDB round-trip (embedding + vector search),
    # isolated so its cost is visible separately from the surrounding
    # filtering/formatting done in this function.
    with span("vectordb.query", attributes={
        "db.system": "chroma", "db.k_requested": fetch_k,
        "db.filtered": where_filter is not None,
    }):
        try:
            if where_filter is not None:
                raw_results = store.similarity_search_with_relevance_scores(
                    query, k=fetch_k, filter=where_filter
                )
            else:
                raw_results = store.similarity_search_with_relevance_scores(
                    query, k=fetch_k
                )
        except Exception as exc:
            _elapsed = round((time.perf_counter() - _t0) * 1000, 1)
            emit("retrieval.result", level="ERROR",
                 num_returned=0, top_score=0.0, elapsed_ms=_elapsed,
                 min_score_used=min_score,
                 error=str(exc)[:200], error_type=type(exc).__name__, **_opt)
            emit_retrieval_failed(
                "search_exception", error=str(exc), error_type=type(exc).__name__,
                elapsed_ms=_elapsed,
            )
            print(f"[retriever] Query failed: {exc}")
            return []

    _elapsed = round((time.perf_counter() - _t0) * 1000, 1)
    emit_retrieval_vector_search(len(raw_results), _elapsed, page_type)

    # Filter, format, and cap at k results
    results: list[dict] = []
    for doc, score in raw_results:
        if score < min_score:
            continue

        results.append({
            "text":               doc.page_content,
            "title":              doc.metadata.get("title", ""),
            "url":                doc.metadata.get("url", ""),
            "page_type":          doc.metadata.get("page_type", ""),
            "program_name":       doc.metadata.get("program_name", ""),
            "content_category":   doc.metadata.get("content_category", ""),
            "discovered_from":    doc.metadata.get("discovered_from", ""),
            "parent_program_url": doc.metadata.get("parent_program_url", ""),
            "workflow_priority":  doc.metadata.get("workflow_priority", 6),
            "score":              round(float(score), 4),
            "chunk_id":           doc.metadata.get("chunk_id", ""),
        })

    emit_retrieval_filtering(len(raw_results), len(results), min_score)

    # Re-sort after filtering (similarity_search_with_relevance_scores sorts by
    # score descending, but filtering can leave a gap in the ordering)
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:k]

    _top_score = results[0]["score"] if results else 0.0
    emit("retrieval.result",
         level="INFO" if results else "WARNING",
         num_returned=len(results),
         top_score=round(_top_score, 4),
         elapsed_ms=_elapsed,
         min_score_used=min_score,
         **_opt)

    emit_retrieval_completed(
        returned_count=len(results),
        scores=[r["score"] for r in results],
        chunk_ids=[r["chunk_id"] for r in results],
        page_types=[r["page_type"] for r in results],
        elapsed_ms=round((time.perf_counter() - _t_pipeline_start) * 1000, 1),
    )

    # Annotate the rag.retrieve span with RAG-quality signals (bounded, no chunk
    # text). retrieval.empty is the leading indicator of ungrounded answers.
    set_attributes(**{
        "retrieval.k":         k,
        "retrieval.min_score": min_score,
        "retrieval.hits":      len(results),
        "retrieval.top_score": _top_score,
        "retrieval.empty":     not results,
    })

    return results


# ---------------------------------------------------------------------------
# Multi-source retrieval
# ---------------------------------------------------------------------------

def retrieve_multi(
    query:       str,
    k_per_type:  int   = 2,
    min_score:   float = MIN_RELEVANCE,
) -> dict[str, list[dict]]:
    """
    Retrieve results from each page type separately.

    Returns a dict keyed by page_type with up to k_per_type results each.
    Page types with no relevant results return an empty list.

    Use this when you want representation from all sources:
        results = retrieve_multi("how do I apply for a doctoral program?")
        faq_hits         = results["faq"]
        steps_hits       = results["application_process"]
        eligibility_hits = results["eligibility"]

    Compared to retrieve() (global top-k):
        retrieve() returns the globally best k chunks — if 3 FAQ chunks all
        score higher than any eligibility chunk, eligibility is absent.
        retrieve_multi() guarantees up to k_per_type from each source, even if
        cross-source scores differ.

    Args:
        query:       User query string.
        k_per_type:  Results per page type (default 2).
        min_score:   Minimum similarity threshold per type.

    Returns:
        {
            "faq":                [...],
            "deadlines":          [...],
            "eligibility":        [...],
            "application_process": [...],
        }
    """
    return {
        pt: retrieve(query, k=k_per_type, min_score=min_score, page_type=pt)
        for pt in sorted(PAGE_TYPES)
    }


# ---------------------------------------------------------------------------
# CLI / retrieval quality test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Interactive CLI to verify retrieval quality against the built vector store.

    Run from the project root:
        python -m rag.retriever
        python -m rag.retriever --build   # force rebuild first

    Or interactively:
        python -m rag.retriever "what are the GPA requirements for doctoral admission?"
    """
    import sys
    import textwrap

    args = sys.argv[1:]

    # ── Force rebuild if requested ────────────────────────────────────────────
    if "--build" in args:
        args = [a for a in args if a != "--build"]
        from rag.store import invalidate_store
        invalidate_store()
        print("[cli] Forced rebuild requested — store cache cleared\n")

    # ── Predefined test queries for quality verification ─────────────────────
    # These cover each page_type and typical student query patterns.
    TEST_QUERIES = [
        # FAQ page queries
        ("faq",              "I don't know where to start with graduate school"),
        ("faq",              "How do I request an appointment with an advisor?"),
        # Deadlines page queries
        ("deadlines",        "When is the application deadline for fall admission?"),
        ("deadlines",        "What are the doctoral program deadlines?"),
        # Eligibility page queries
        ("eligibility",      "What GPA do I need to apply for a doctoral program?"),
        ("eligibility",      "Do I need a master's degree to apply for a PhD?"),
        # Application process queries
        ("application_process", "How do I apply to a doctoral program at CSULB?"),
        ("application_process", "What documents do I need to submit my application?"),
        # Cross-source queries (no page_type filter)
        (None,               "What are the steps to apply for graduate school?"),
        (None,               "Who should I contact about my application?"),
    ]

    # ── Single-query mode: passed as CLI argument ─────────────────────────────
    if args and not args[0].startswith("--"):
        query = " ".join(args)
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}")

        results = retrieve(query, k=5)
        if not results:
            print("  ✗ No results above threshold")
        else:
            for i, r in enumerate(results, 1):
                print(f"\n  Result {i}  [{r['page_type']}]  score={r['score']:.4f}")
                print(f"  URL: {r['url']}")
                print(f"  {textwrap.fill(r['text'][:300], width=60, subsequent_indent='  ')}")

        sys.exit(0)

    # ── Batch test mode: run all TEST_QUERIES ──────────────────────────────────
    print("=" * 60)
    print("CSULB RAG Retriever — quality verification")
    print("=" * 60)
    print(f"\nRunning {len(TEST_QUERIES)} test queries...\n")

    pass_count = 0
    fail_count = 0

    for expected_type, query in TEST_QUERIES:
        # Use page_type filter when expected_type is set
        results = retrieve(query, k=3, page_type=expected_type)

        has_results = len(results) > 0
        top_score   = results[0]["score"] if results else 0.0
        top_type    = results[0]["page_type"] if results else "—"

        # A result is "passing" if we got at least one result above threshold
        passed = has_results
        status = "✓" if passed else "✗"

        if passed:
            pass_count += 1
        else:
            fail_count += 1

        filter_label = f"[filter:{expected_type}]" if expected_type else "[no filter]"
        print(f"  {status} {filter_label}")
        print(f"    Query: {query[:65]}")

        if results:
            print(f"    Top:   score={top_score:.4f}  type={top_type}")
            print(f"    Text:  {results[0]['text'][:120].strip()}…")
        else:
            print(f"    ✗ No results above threshold ({MIN_RELEVANCE})")

        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = pass_count + fail_count
    print(f"{'='*60}")
    print(f"Results: {pass_count}/{total} queries returned results")

    if fail_count > 0:
        print(
            f"\n  {fail_count} queries returned no results above MIN_RELEVANCE ({MIN_RELEVANCE}).\n"
            f"  Consider:\n"
            f"    1. Lowering MIN_RELEVANCE (current: {MIN_RELEVANCE})\n"
            f"    2. Rebuilding the store: python -m rag.retriever --build\n"
            f"    3. Checking that the source pages fetched correctly:\n"
            f"       python -m rag.ingestion"
        )
    else:
        print("\n  All queries returned results. Retrieval quality looks good.")

    # ── Bonus: retrieve_multi demo ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("retrieve_multi() demo — cross-source query:")
    demo_q = "what do I need to apply and am I eligible for a doctoral program?"
    print(f"  Query: {demo_q}\n")

    multi = retrieve_multi(demo_q, k_per_type=1)
    for pt, hits in multi.items():
        if hits:
            r = hits[0]
            print(f"  [{pt}]  score={r['score']:.4f}")
            print(f"    {r['text'][:120].strip()}…")
        else:
            print(f"  [{pt}]  no results above threshold")
