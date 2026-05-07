"""
tools/eligibility_tool.py
Retrieve doctoral program eligibility information via RAG with JSON fallback.

Primary path: page_type="eligibility" filtered RAG retrieval.
Fallback path: data/admissions.json (content.eligibility section) — used when
  RAG returns no results above threshold (e.g. vector store not yet built,
  network unavailable during ingestion, or query is highly specific).

Why JSON fallback for eligibility (but not deadlines):
  Eligibility requirements (GPA thresholds, degree prerequisites) are stable
  year-to-year.  A JSON snapshot is reliable as a safety net.  Deadlines change
  each cycle, so no JSON fallback is offered there.

Output schema:
    {
        "found":         bool,
        "tool":          "eligibility_tool",
        "sources":       list[str],
        "error":         None | str,
        "results":       list[dict],   # RAG chunk dicts, or [] on JSON fallback
        "top_score":     float,
        "query":         str,
        "fallback_used": bool,         # True when JSON fallback was activated
        "fallback_data": dict | None,  # raw eligibility dict from admissions.json
        "disclaimer":    str,
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from rag import retrieve

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ELIGIBILITY_URL = "https://www.csulb.edu/admissions/doctoral-programs-admission-eligibility"
_ADMISSIONS_JSON = Path(__file__).parent.parent / "data" / "admissions.json"

_DISCLAIMER = (
    "ℹ️  Eligibility requirements are set by each program and may exceed the "
    "university minimums shown here. Always confirm requirements directly with "
    "your program's graduate advisor before applying."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_eligibility_json() -> dict | None:
    """
    Load the eligibility section from data/admissions.json.
    Returns None if the file is missing, unreadable, or malformed.
    """
    try:
        raw  = json.loads(_ADMISSIONS_JSON.read_text(encoding="utf-8"))
        data = raw.get("content", {}).get("eligibility")
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_eligibility(
    query:     str,
    k:         int   = 4,
    min_score: float = 0.30,
) -> dict:
    """
    Retrieve eligibility information for CSULB doctoral programs.

    Tries the RAG store first (scoped to page_type="eligibility").
    Falls back to the admissions.json snapshot if no chunks meet the threshold.

    Args:
        query:     User question, e.g. "what GPA do I need to apply?",
                   "do I need a master's to apply for a PhD?"
        k:         Maximum RAG results to return (default 4).
        min_score: Minimum cosine similarity (default 0.30).

    Returns:
        Standard tool dict with eligibility-specific keys.
        See module docstring for full schema.
    """
    if not query or not query.strip():
        return {
            "found":         False,
            "tool":          "eligibility_tool",
            "sources":       [_ELIGIBILITY_URL],
            "error":         "Query is empty.",
            "results":       [],
            "top_score":     0.0,
            "query":         query,
            "fallback_used": False,
            "fallback_data": None,
            "disclaimer":    _DISCLAIMER,
        }

    # ── Primary: RAG retrieval ────────────────────────────────────────────────
    rag_error:   str | None  = None
    rag_results: list[dict]  = []

    try:
        rag_results = retrieve(query, k=k, min_score=min_score, page_type="eligibility")
    except Exception as exc:
        rag_error = f"RAG retrieval failed: {exc}"

    if rag_results:
        # Deduplicate sources; always include canonical eligibility URL
        seen:    set[str]  = {_ELIGIBILITY_URL}
        sources: list[str] = [_ELIGIBILITY_URL]
        for r in rag_results:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                sources.append(url)

        return {
            "found":         True,
            "tool":          "eligibility_tool",
            "sources":       sources,
            "error":         None,
            "results":       rag_results,
            "top_score":     rag_results[0]["score"],
            "query":         query,
            "fallback_used": False,
            "fallback_data": None,
            "disclaimer":    _DISCLAIMER,
        }

    # ── Fallback: admissions.json ─────────────────────────────────────────────
    fallback = _load_eligibility_json()
    fallback_source = "https://www.csulb.edu/admissions/graduate-programs-admission-eligibility"

    sources = list({_ELIGIBILITY_URL, fallback_source})

    return {
        "found":         fallback is not None,
        "tool":          "eligibility_tool",
        "sources":       sources,
        "error":         rag_error,                # surface RAG error if present
        "results":       [],                       # no RAG chunks when using fallback
        "top_score":     0.0,
        "query":         query,
        "fallback_used": True,
        "fallback_data": fallback,
        "disclaimer":    _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test get_eligibility() with representative queries.

    Run from the project root:
        python -m tools.eligibility_tool
    """
    import textwrap

    TEST_CASES = [
        "what GPA do I need to apply for a doctoral program?",
        "do I need a master's degree to apply for a PhD at CSULB?",
        "what are the minimum eligibility requirements for doctoral admission?",
        "",
    ]

    print("=" * 60)
    print("eligibility_tool — CLI smoke test")
    print("=" * 60)

    for query in TEST_CASES:
        result = get_eligibility(query)
        status = "✓" if result["found"] else ("—" if not query else "✗")
        fallback_tag = "  [JSON fallback]" if result["fallback_used"] else ""
        print(f"\n  {status}  found={result['found']}  top_score={result['top_score']:.4f}{fallback_tag}")
        print(f"     query: {query!r}")

        if result["error"]:
            print(f"     error: {result['error']}")

        if result["results"]:
            for i, r in enumerate(result["results"][:2], 1):
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"     [{i}] score={r['score']:.4f}  {snippet}")
        elif result["fallback_data"]:
            gpa = result["fallback_data"].get("gpa_requirements", {})
            print(f"     fallback GPA standard: {gpa.get('standard', '?')}")
            print(f"     fallback additional:   {result['fallback_data'].get('additional', '')[:80]}")
        elif not result["found"]:
            print("     No results and fallback unavailable.")

        print(f"     disclaimer: {result['disclaimer'][:70]}…")

    print(f"\n{'='*60}")
    print("eligibility_tool smoke test complete.")


if __name__ == "__main__":
    run_cli_test()
