"""
tools/application_steps_tool.py
Retrieve doctoral application process information via RAG with JSON fallback.

Primary path: page_type="application_process" filtered RAG retrieval.
Supplemental detection: a second RAG pass for "supplemental application" to
  surface any program-specific supplemental requirements.
Fallback path: data/admissions.json (content.doctoral_application_steps section).

Supplemental application detection:
  Most CSULB doctoral programs require a separate supplemental application in
  addition to the university-wide Cal State Apply submission.  We run a targeted
  query ("supplemental application doctoral requirements") and include those
  results in a separate supplemental_results field so the caller can surface
  them as a distinct actionable item.

Output schema:
    {
        "found":              bool,
        "tool":               "application_steps_tool",
        "sources":            list[str],
        "error":              None | str,
        "results":            list[dict],   # main application process chunks
        "supplemental_results": list[dict], # supplemental-specific chunks
        "has_supplemental":   bool,         # True if supplemental results found
        "top_score":          float,
        "query":              str,
        "fallback_used":      bool,
        "fallback_data":      list | None,  # doctoral_application_steps.steps
        "disclaimer":         str,
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from rag import retrieve

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROCESS_URL   = "https://www.csulb.edu/admissions/doctoral-programs-application-process"
_ADMISSIONS_JSON = Path(__file__).parent.parent / "data" / "admissions.json"

# Fixed supplemental probe — always run alongside the main query
_SUPPLEMENTAL_QUERY = "supplemental application doctoral program requirements"

_DISCLAIMER = (
    "ℹ️  Most doctoral programs require a supplemental application in addition "
    "to the university application via Cal State Apply. Requirements and "
    "deadlines vary by program — contact your program directly to confirm all "
    "required materials before you apply."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_application_steps_json() -> list | None:
    """
    Load doctoral_application_steps.steps from data/admissions.json.
    Returns None if the file is missing, unreadable, or malformed.
    """
    try:
        raw   = json.loads(_ADMISSIONS_JSON.read_text(encoding="utf-8"))
        block = raw.get("content", {}).get("doctoral_application_steps", {})
        steps = block.get("steps")
        return steps if isinstance(steps, list) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _dedup_sources(*url_lists: list[str]) -> list[str]:
    """Return a deduplicated, order-preserving list of URLs."""
    seen:    set[str]  = set()
    sources: list[str] = []
    for urls in url_lists:
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                sources.append(url)
    return sources


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_application_steps(
    query:            str,
    k:                int   = 5,
    min_score:        float = 0.30,
    supplemental_k:   int   = 3,
    supplemental_min: float = 0.30,
) -> dict:
    """
    Retrieve doctoral application process steps and supplemental requirements.

    Runs two RAG passes:
      1. Main query scoped to page_type="application_process".
      2. Fixed supplemental probe to surface program-specific requirements.

    Falls back to admissions.json if the main query returns no results.

    Args:
        query:            User question, e.g. "how do I apply for a doctoral program?"
        k:                Maximum main results (default 5).
        min_score:        Minimum similarity for main query (default 0.30).
        supplemental_k:   Maximum supplemental results (default 3).
        supplemental_min: Minimum similarity for supplemental probe (default 0.30).

    Returns:
        Standard tool dict with application-steps-specific keys.
        See module docstring for full schema.
    """
    if not query or not query.strip():
        return {
            "found":                False,
            "tool":                 "application_steps_tool",
            "sources":              [_PROCESS_URL],
            "error":                "Query is empty.",
            "results":              [],
            "supplemental_results": [],
            "has_supplemental":     False,
            "top_score":            0.0,
            "query":                query,
            "fallback_used":        False,
            "fallback_data":        None,
            "disclaimer":           _DISCLAIMER,
        }

    rag_error: str | None = None

    # ── Pass 1: main application process query ────────────────────────────────
    main_results: list[dict] = []
    try:
        main_results = retrieve(
            query,
            k=k,
            min_score=min_score,
            page_type="application_process",
        )
    except Exception as exc:
        rag_error = f"RAG retrieval failed: {exc}"

    # ── Pass 2: supplemental application probe (always run if store is up) ────
    supplemental_results: list[dict] = []
    try:
        supplemental_results = retrieve(
            _SUPPLEMENTAL_QUERY,
            k=supplemental_k,
            min_score=supplemental_min,
            page_type="application_process",
        )
        # Remove chunks that duplicated from the main results
        main_ids = {r.get("chunk_id") for r in main_results}
        supplemental_results = [
            r for r in supplemental_results
            if r.get("chunk_id") not in main_ids
        ]
    except Exception:
        supplemental_results = []

    # ── Source collection ─────────────────────────────────────────────────────
    main_urls = [r.get("url", "") for r in main_results]
    supp_urls = [r.get("url", "") for r in supplemental_results]
    sources   = _dedup_sources([_PROCESS_URL], main_urls, supp_urls)

    # ── Return if RAG found something ─────────────────────────────────────────
    if main_results:
        return {
            "found":                True,
            "tool":                 "application_steps_tool",
            "sources":              sources,
            "error":                None,
            "results":              main_results,
            "supplemental_results": supplemental_results,
            "has_supplemental":     len(supplemental_results) > 0,
            "top_score":            main_results[0]["score"],
            "query":                query,
            "fallback_used":        False,
            "fallback_data":        None,
            "disclaimer":           _DISCLAIMER,
        }

    # ── Fallback: admissions.json ─────────────────────────────────────────────
    fallback_steps = _load_application_steps_json()

    return {
        "found":                fallback_steps is not None,
        "tool":                 "application_steps_tool",
        "sources":              sources,
        "error":                rag_error,
        "results":              [],
        "supplemental_results": supplemental_results,   # may still have hits
        "has_supplemental":     len(supplemental_results) > 0,
        "top_score":            0.0,
        "query":                query,
        "fallback_used":        True,
        "fallback_data":        fallback_steps,
        "disclaimer":           _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test get_application_steps() with representative queries.

    Run from the project root:
        python -m tools.application_steps_tool
    """
    import textwrap

    TEST_CASES = [
        "how do I apply for a doctoral program at CSULB?",
        "what documents do I need to submit my application?",
        "what is the supplemental application for doctoral programs?",
        "",
    ]

    print("=" * 60)
    print("application_steps_tool — CLI smoke test")
    print("=" * 60)

    for query in TEST_CASES:
        result = get_application_steps(query)
        status  = "✓" if result["found"] else ("—" if not query else "✗")
        fb_tag  = "  [JSON fallback]" if result["fallback_used"] else ""
        sup_tag = f"  [supplemental: {len(result['supplemental_results'])}]" if result["has_supplemental"] else ""
        print(
            f"\n  {status}  found={result['found']}  "
            f"top_score={result['top_score']:.4f}{fb_tag}{sup_tag}"
        )
        print(f"     query: {query!r}")

        if result["error"]:
            print(f"     error: {result['error']}")

        if result["results"]:
            for i, r in enumerate(result["results"][:2], 1):
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"     [{i}] score={r['score']:.4f}  {snippet}")
            if len(result["results"]) > 2:
                print(f"     … {len(result['results']) - 2} more main result(s)")

        if result["supplemental_results"]:
            print(f"     supplemental ({len(result['supplemental_results'])} chunks):")
            for r in result["supplemental_results"][:1]:
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"       score={r['score']:.4f}  {snippet}")

        if result["fallback_data"]:
            steps = result["fallback_data"]
            print(f"     fallback: {len(steps)} steps loaded from admissions.json")
            if steps:
                s = steps[0]
                print(f"       step 1: {s.get('title')} — {str(s.get('details',''))[:60]}…")

        print(f"     disclaimer: {result['disclaimer'][:70]}…")

    print(f"\n{'='*60}")
    print("application_steps_tool smoke test complete.")


if __name__ == "__main__":
    run_cli_test()
