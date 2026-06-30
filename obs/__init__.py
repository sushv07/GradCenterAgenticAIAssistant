"""
obs — internal observability layer.

Problem this solves:
    Phase 8A's evaluation framework can determine WHETHER retrieval
    returned the correct results. It cannot explain WHY a particular
    retrieval behaved the way it did — rag/retriever.py emitted exactly
    one event ("retrieval.result") capturing only the final outcome, with
    no visibility into intermediate stages: how many candidates the vector
    search returned before filtering, how many were filtered out and why,
    what the score distribution looked like.

What this package does:
    retrieval_events.py adds five structured, stage-level events
    (retrieval.started / .vector_search / .filtering / .completed /
    .failed) layered on top of rag/retriever.py's existing logging — never
    replacing it. retrieval_summary.py reads those events back out of
    logs/gradcenter.log to compute aggregate stats (average latency,
    average candidate count, filtering percentage, etc.) without touching
    retrieval itself.

What this package deliberately does NOT do (Phase 8B non-goals):
    - It never changes what retrieve() returns, in what order, or how
      candidates are scored/filtered/ranked — purely additive logging
      around the existing, unmodified control flow.
    - It does not log retrieved chunk TEXT — only metadata (counts,
      scores, ids, page_types, elapsed time).
    - It does not integrate LangSmith, OpenTelemetry, or any external
      tracing system — see retrieval_events.py's docstring for why the
      ContextVar-based design is forward-compatible with that anyway.
    - It is not the same thing as Phase 8A's retrieval evaluation: an eval
      run asks "was this retrieval CORRECT" against a known-answer
      dataset; this package answers "what actually HAPPENED inside any
      given retrieval call," correct or not, on real traffic. See
      ARCHITECTURE_ANALYSIS.md's Phase 8B section for the full distinction.

  retrieval_events.py  — emit_retrieval_*() structured event helpers
  retrieval_summary.py — summarize_retrieval_events(): reads logs/gradcenter.log
"""
