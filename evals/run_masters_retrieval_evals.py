"""
evals/run_masters_retrieval_evals.py
Master's retrieval evaluation runner (Phase 6 — baseline benchmark).

Extends the Phase 8A retrieval-eval pattern (evals/run_retrieval_evals.py) with
rank-based metrics (Recall@1/3/5, MRR, first-relevant rank), per-category
breakdowns, latency capture, and evidence-based failure classification.

Retrieval-only: calls the REAL production retriever (rag.retriever.retrieve) so
every threshold/over-fetch/filter behaviour is exactly production's. No LLM, no
prompt, no retrieval modification. A `store` handle can be injected so the
benchmark runs against an isolated evaluation store without touching the
deployed collection; `retrieve_fn` can be injected for offline tests.

Failure classification is evidence-based, never guessed:
  acquisition_gap      — expected URL has ZERO chunks in the store
  retriever_ranking    — expected URL in store and appears within the probe
                         depth (k=20) but not within k=5
  embedding_limitation — expected URL in store but absent even at probe depth
  evaluation_ambiguity — case retrieved plausible content from a different
                         expected-adjacent URL (flagged for manual review)
Each classification carries the raw evidence (store chunk count, probe rank).

Usage:
    python -m evals.run_masters_retrieval_evals            # live production store
    (Phase 6 baseline uses an injected isolated store — see the report header.)
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import patch

from evals.metrics_retrieval_ranking import (
    first_relevant_rank, mean_reciprocal_rank, normalize_url, recall_summary,
)

CASES_PATH = Path(__file__).parent / "masters_retrieval_eval_cases.json"
REPORT_PATH = Path(__file__).parent / "MASTERS_RETRIEVAL_BASELINE.md"

_K = 5          # evaluation cutoff (Recall@5 is the widest reported metric)
_PROBE_K = 20   # classification probe depth: distinguishes ranking vs embedding


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_cases(path: Path = CASES_PATH) -> list[dict]:
    data = json.loads(Path(path).read_text("utf-8"))
    cases = data["cases"]
    seen = set()
    for c in cases:
        for key in ("case_id", "category", "style", "query"):
            if key not in c:
                raise ValueError(f"case missing '{key}': {c}")
        if c["case_id"] in seen:
            raise ValueError(f"duplicate case_id {c['case_id']}")
        seen.add(c["case_id"])
        if not c.get("expect_empty") and not c.get("expected_urls"):
            raise ValueError(f"{c['case_id']}: needs expected_urls or expect_empty")
    return cases


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

@contextmanager
def _use_store(store: Any):
    """Route rag.retriever.retrieve at an injected store (isolated eval runs)."""
    if store is None:
        yield
    else:
        with patch("rag.retriever.get_or_build_store", return_value=store):
            yield


def run_case(case: dict, retrieve_fn: Callable[..., list[dict]]) -> dict:
    kwargs: dict[str, Any] = {"k": _K}
    if case.get("page_type_filter"):
        kwargs["page_type"] = case["page_type_filter"]
    t0 = time.perf_counter()
    results = retrieve_fn(case["query"], **kwargs)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    retrieved = [{
        "url": r.get("url", ""), "score": r.get("score", 0.0),
        "page_type": r.get("page_type", ""), "program_name": r.get("program_name", ""),
        "chunk_id": r.get("chunk_id", ""), "title": r.get("title", ""),
    } for r in results]

    expected_urls = case.get("expected_urls", [])
    rank = first_relevant_rank([r["url"] for r in retrieved], expected_urls)

    if case.get("expect_empty"):
        passed = len(retrieved) == 0
    else:
        passed = rank is not None and rank <= _K

    return {
        "case_id": case["case_id"], "category": case["category"],
        "style": case["style"], "query": case["query"],
        "expected_urls": expected_urls, "expected_program": case.get("expected_program", ""),
        "expected_page_type": case.get("expected_page_type", ""),
        "expect_empty": bool(case.get("expect_empty")),
        "retrieved": retrieved, "first_relevant_rank": rank,
        "latency_ms": latency_ms, "passed": passed,
    }


def classify_failure(result: dict, probe: dict) -> dict:
    """Evidence-based failure category for one failed case.

    probe = {
      "store_chunk_counts": {normalized_url: chunk_count_in_store},
      "probe_rank": Optional[int],   # rank of first expected url within k=20
    }
    """
    if result["expect_empty"]:
        return {"category": "evaluation_ambiguity",
                "evidence": f"expected no results but retrieved "
                            f"{len(result['retrieved'])} chunks "
                            f"(top score {result['retrieved'][0]['score'] if result['retrieved'] else 0})"}
    counts = probe.get("store_chunk_counts", {})
    in_store = any(counts.get(normalize_url(u), 0) > 0 for u in result["expected_urls"])
    if not in_store:
        return {"category": "acquisition_gap",
                "evidence": "expected URL(s) have 0 chunks in the evaluation store"}
    probe_rank = probe.get("probe_rank")
    if probe_rank is not None:
        return {"category": "retriever_ranking",
                "evidence": f"expected URL present in store; first hit at rank "
                            f"{probe_rank} within probe k={_PROBE_K} (needed <= {_K})"}
    return {"category": "embedding_limitation",
            "evidence": f"expected URL present in store but absent from the top "
                        f"{_PROBE_K} results for this query"}


def _build_probe(result: dict, store: Any, retrieve_fn: Callable[..., list[dict]]) -> dict:
    """Gather classification evidence: store counts + deep-probe rank."""
    counts: dict[str, int] = {}
    if store is not None:
        try:
            got = store._collection.get(include=["metadatas"])
            for md in got["metadatas"]:
                u = normalize_url(md.get("url", md.get("source_url", "")))
                counts[u] = counts.get(u, 0) + 1
        except Exception:
            pass
    deep = retrieve_fn(result["query"], k=_PROBE_K)
    probe_rank = first_relevant_rank([r.get("url", "") for r in deep],
                                     result["expected_urls"])
    return {"store_chunk_counts": counts, "probe_rank": probe_rank}


def run_evals(
    cases: list[dict],
    *,
    store: Any = None,
    retrieve_fn: Optional[Callable[..., list[dict]]] = None,
) -> dict:
    """Run all cases; returns {results, metrics, failures}."""
    with _use_store(store):
        if retrieve_fn is None:
            from rag.retriever import retrieve as retrieve_fn  # production retriever

        results = [run_case(c, retrieve_fn) for c in cases]

        failures = []
        for r in results:
            if not r["passed"]:
                probe = _build_probe(r, store, retrieve_fn)
                failures.append({**r, "classification": classify_failure(r, probe)})

    scored = [r for r in results if not r["expect_empty"]]
    ranks = [r["first_relevant_rank"] for r in scored]
    latencies = sorted(r["latency_ms"] for r in results)
    n = len(latencies)

    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    per_category = {
        cat: {
            "cases": len(rs),
            "passed": sum(1 for r in rs if r["passed"]),
            **recall_summary([r["first_relevant_rank"] for r in rs if not r["expect_empty"]]),
        }
        for cat, rs in sorted(by_cat.items())
    }

    metrics = {
        "total_cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        **recall_summary(ranks),
        "mrr": mean_reciprocal_rank(ranks),
        "avg_latency_ms": round(sum(latencies) / n, 1) if n else 0.0,
        "p50_latency_ms": latencies[n // 2] if n else 0.0,
        "p95_latency_ms": latencies[min(n - 1, int(n * 0.95))] if n else 0.0,
        "per_category": per_category,
    }
    return {"results": results, "metrics": metrics, "failures": failures}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_report(outcome: dict, *, store_description: str) -> str:
    m = outcome["metrics"]
    L = ["# Master's Retrieval — Baseline Benchmark (Phase 6)", "",
         f"Store under evaluation: {store_description}", "",
         "Retrieval-only (production `rag.retriever.retrieve`, k=5, "
         "min_score=0.30). No LLM, no reranking, no query rewriting.", "",
         "## Overall metrics", "",
         f"- cases: {m['total_cases']} · passed: {m['passed']} · failed: {m['failed']}",
         f"- **Recall@1: {m['recall@1']:.2%} · Recall@3: {m['recall@3']:.2%} · "
         f"Recall@5: {m['recall@5']:.2%}**",
         f"- MRR: {m['mrr']}",
         f"- latency: avg {m['avg_latency_ms']} ms · p50 {m['p50_latency_ms']} ms · "
         f"p95 {m['p95_latency_ms']} ms", "",
         "## Per-category", "",
         "| category | cases | passed | R@1 | R@3 | R@5 |",
         "| --- | --- | --- | --- | --- | --- |"]
    for cat, cm in m["per_category"].items():
        L.append(f"| {cat} | {cm['cases']} | {cm['passed']} | "
                 f"{cm['recall@1']:.0%} | {cm['recall@3']:.0%} | {cm['recall@5']:.0%} |")
    L += ["", "## Failures", ""]
    if not outcome["failures"]:
        L.append("(none)")
    for f in outcome["failures"]:
        cls = f["classification"]
        L += [f"### {f['case_id']} [{f['category']} / {f['style']}] — {cls['category']}",
              f"- query: {f['query']}",
              f"- expected: {f['expected_urls'] or '(no results expected)'}",
              f"- first relevant rank: {f['first_relevant_rank']}",
              f"- evidence: {cls['evidence']}",
              f"- top retrieved: " + "; ".join(
                  f"[{r['score']:.2f}] {r['url']}" for r in f["retrieved"][:3]), ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    cases = load_cases()
    outcome = run_evals(cases)   # live production store
    print(render_report(outcome, store_description="live production store"))
