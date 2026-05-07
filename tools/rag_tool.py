"""
tools/rag_tool.py
Raw semantic search over the full CSULB multi-source vector store.

This tool wraps rag.retrieve() directly without page_type filtering.
Use it when:
  - The user's intent spans multiple sources (e.g. "how do I apply and am I eligible?")
  - No more specific tool (deadlines_tool, eligibility_tool, etc.) matched
  - You want the globally top-k chunks regardless of source

For source-scoped retrieval, prefer the specialised tools:
    deadlines_tool       → page_type="deadlines"
    eligibility_tool     → page_type="eligibility"
    application_steps_tool → page_type="application_process"

Output schema:
    {
        "found":     bool,
        "tool":      "rag_tool",
        "sources":   list[str],    # deduplicated citation URLs from results
        "error":     None | str,
        "results":   list[dict],   # raw retrieve() output dicts
        "top_score": float,        # highest cosine similarity score (0.0 if empty)
        "query":     str,          # echoed back for logging / debugging
    }

Each item in results has:
    text, title, url, page_type, score, chunk_id
"""

from __future__ import annotations

from rag import retrieve


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_rag(
    query:     str,
    k:         int   = 5,
    min_score: float = 0.30,
) -> dict:
    """
    Retrieve the top-k most relevant chunks from the full CSULB vector store.

    No page_type filter is applied — results can come from any of the four
    source pages (faq, deadlines, eligibility, application_process).

    Args:
        query:     User question or search phrase.
        k:         Maximum number of results to return (default 5).
        min_score: Minimum cosine similarity threshold (default 0.30).
                   Increase to 0.50+ for tighter relevance.

    Returns:
        {
            "found":     bool,
            "tool":      "rag_tool",
            "sources":   list[str],  # citation URLs, deduplicated
            "error":     None | str,
            "results":   list[dict], # up to k chunk dicts from retrieve()
            "top_score": float,
            "query":     str,
        }
    """
    if not query or not query.strip():
        return {
            "found":     False,
            "tool":      "rag_tool",
            "sources":   [],
            "error":     "Query is empty.",
            "results":   [],
            "top_score": 0.0,
            "query":     query,
        }

    try:
        results = retrieve(query, k=k, min_score=min_score)
    except Exception as exc:
        return {
            "found":     False,
            "tool":      "rag_tool",
            "sources":   [],
            "error":     f"RAG retrieval failed: {exc}",
            "results":   [],
            "top_score": 0.0,
            "query":     query,
        }

    # Deduplicate source URLs while preserving order
    seen_urls:  set[str]  = set()
    sources:    list[str] = []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            sources.append(url)

    top_score = results[0]["score"] if results else 0.0

    return {
        "found":     len(results) > 0,
        "tool":      "rag_tool",
        "sources":   sources,
        "error":     None,
        "results":   results,
        "top_score": top_score,
        "query":     query,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test search_rag() with representative queries.

    Run from the project root:
        python -m tools.rag_tool
    """
    import textwrap

    TEST_CASES = [
        ("what are the steps to apply for graduate school?", 5, 0.30),
        ("do I need a master's degree to apply for a PhD?",  3, 0.30),
        ("when is the fall application deadline?",           3, 0.30),
        ("xyznonexistentquery",                              3, 0.30),
    ]

    print("=" * 60)
    print("rag_tool — CLI smoke test")
    print("=" * 60)

    for query, k, min_score in TEST_CASES:
        result = search_rag(query, k=k, min_score=min_score)
        status = "✓" if result["found"] else "✗"
        print(f"\n  {status}  found={result['found']}  top_score={result['top_score']:.4f}")
        print(f"     query: {query!r}")

        if result["error"]:
            print(f"     error: {result['error']}")
        elif result["results"]:
            for i, r in enumerate(result["results"], 1):
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"     [{i}] [{r['page_type']}] score={r['score']:.4f}  {snippet}")
        else:
            print("     No results above threshold.")

    print(f"\n{'='*60}")
    print("rag_tool smoke test complete.")


if __name__ == "__main__":
    run_cli_test()
