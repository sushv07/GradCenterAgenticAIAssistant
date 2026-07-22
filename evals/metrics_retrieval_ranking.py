"""
evals/metrics_retrieval_ranking.py
Rank-based retrieval metrics (Phase 6 — master's retrieval baseline).

Pure functions, no I/O, no retrieval. Complements evals/metrics_retrieval.py
(Phase 8A), which computes pass/fail-style aggregates but has no notion of rank:
this module adds Recall@k, MRR, and first-relevant-rank, judged by matching
retrieved source URLs against a case's expected URLs.

URL matching is deterministic and normalization-tolerant (scheme and trailing
slash are ignored) because the same CSULB page appears with both http/https and
with/without a trailing slash across the site's own links.
"""
from __future__ import annotations

from typing import Optional, Sequence


def normalize_url(url: str) -> str:
    """Lowercase, drop scheme, query and trailing slash — deterministic identity."""
    u = (url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
            break
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u.rstrip("/")


def url_matches(candidate: str, expected: str) -> bool:
    return normalize_url(candidate) == normalize_url(expected)


def first_relevant_rank(
    retrieved_urls: Sequence[str], expected_urls: Sequence[str]
) -> Optional[int]:
    """1-based rank of the first retrieved URL matching any expected URL.

    Returns None when no retrieved URL matches (or either list is empty).
    """
    if not expected_urls:
        return None
    expected_norm = {normalize_url(u) for u in expected_urls}
    for i, url in enumerate(retrieved_urls, start=1):
        if normalize_url(url) in expected_norm:
            return i
    return None


def recall_at_k(rank: Optional[int], k: int) -> bool:
    """True when the first relevant result appears at rank <= k."""
    return rank is not None and rank <= k


def mean_reciprocal_rank(ranks: Sequence[Optional[int]]) -> float:
    """MRR over cases; a miss (None) contributes 0. Empty input -> 0.0."""
    if not ranks:
        return 0.0
    return round(sum((1.0 / r) if r else 0.0 for r in ranks) / len(ranks), 4)


def recall_summary(ranks: Sequence[Optional[int]], ks: Sequence[int] = (1, 3, 5)) -> dict:
    """{'recall@1': .., 'recall@3': .., 'recall@5': ..} as fractions in [0, 1]."""
    if not ranks:
        return {f"recall@{k}": 0.0 for k in ks}
    return {
        f"recall@{k}": round(sum(1 for r in ranks if recall_at_k(r, k)) / len(ranks), 4)
        for k in ks
    }
