"""
rag/masters_catalog_metrics.py
Measurement concerns for the full-catalog build (Phase 8): the stats record,
stage timing, and instrumented fetch wrappers.

Pure bookkeeping — nothing here fetches, extracts, chunks, or indexes. The
orchestrator (rag/masters_catalog.py) threads these wrappers through the
EXISTING injection seams (`fetch_fn` / `fetch_final_fn`), so instrumentation
wraps the acquisition stages without modifying any of them.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class CatalogBuildStats:
    """Everything measured during one full-catalog acquisition + build."""

    # directory discovery
    programs_discovered: int = 0
    unique_seed_urls: int = 0
    seed_hosts: dict[str, int] = field(default_factory=dict)
    programs_with_warnings: int = 0
    index_content_hash: str = ""
    # Phase 9B: {program label: replacement url} remapped via seed_overrides.json
    seed_overrides_applied: dict[str, str] = field(default_factory=dict)

    # nested page discovery
    unique_pages: int = 0
    seed_pages: int = 0
    nested_pages: int = 0
    shared_pages: int = 0
    skipped_no_seed: int = 0
    pages_by_category: dict[str, int] = field(default_factory=dict)
    fetch_attempts: int = 0
    fetch_failures: int = 0
    # Phase 9A hygiene guards: {url: reason} for every excluded nested page
    skipped_pages: dict[str, str] = field(default_factory=dict)

    # extraction / conversion
    pages_processed: int = 0
    documents_accepted: int = 0
    documents_rejected: int = 0
    empty_pages: int = 0
    duplicate_document_ids: int = 0
    redirects_followed: int = 0
    redirect_map: dict[str, str] = field(default_factory=dict)
    # Phase 9B: {final_url: [requested…]} — cross-host redirect magnets (see
    # dead_seed_candidates); reporting only, never auto-excluded
    dead_seeds: dict[str, list[str]] = field(default_factory=dict)
    rejections_by_reason: dict[str, int] = field(default_factory=dict)
    missing_metadata: dict[str, int] = field(default_factory=dict)
    directory_card_documents: int = 0

    # program coverage (page documents, cards excluded)
    programs_with_page_content: list[str] = field(default_factory=list)
    programs_without_page_content: list[str] = field(default_factory=list)

    # chunks / vectors
    masters_chunks: int = 0
    base_chunks: int = 0
    total_chunks: int = 0
    indexed_vectors: int = 0
    chunks_per_program: dict[str, int] = field(default_factory=dict)

    # stage timings (seconds)
    timings_s: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


class StageTimer:
    """Accumulates named stage durations; `total` sums non-derived stages."""

    # derived entries are computed FROM other stages, so they are excluded
    # from the total to avoid double counting
    _DERIVED = ("indexing_derived",)

    def __init__(self) -> None:
        self.raw: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        yield
        self.raw[name] = time.perf_counter() - t0

    def finalize(self) -> dict[str, float]:
        out = dict(self.raw)
        out["total"] = sum(v for k, v in out.items() if k not in self._DERIVED)
        return {k: round(v, 2) for k, v in out.items()}


def counting_fetch(
    fetch_fn: Callable[[str], Optional[str]], stats: CatalogBuildStats,
) -> Callable[[str], Optional[str]]:
    """Wrap a fetch function to count attempts and failures."""
    def _fetch(url: str) -> Optional[str]:
        stats.fetch_attempts += 1
        html = fetch_fn(url)
        if html is None:
            stats.fetch_failures += 1
        return html
    return _fetch


def recording_fetch_final(
    fetch_final_fn: Callable[[str], tuple[Optional[str], str]],
    stats: CatalogBuildStats,
) -> Callable[[str], tuple[Optional[str], str]]:
    """Wrap a redirect-aware fetch to record requested→final URL divergences."""
    from rag.masters_discovery import canonical_url

    def _fetch(url: str) -> tuple[Optional[str], str]:
        html, final = fetch_final_fn(url)
        if html is not None and canonical_url(final) != canonical_url(url):
            stats.redirects_followed += 1
            stats.redirect_map[url] = final
        return html, final
    return _fetch


def dead_seed_candidates(redirect_map: dict[str, str]) -> dict[str, list[str]]:
    """Detect the 'homepage magnet' signature in a requested→final URL map.

    A final URL that (a) is reached from >= 2 distinct requested URLs and
    (b) sits on a different host than those requests is almost certainly a
    college/landing page swallowing dead department links (Phase 9B evidence:
    14 decommissioned CLA seeds all collapsed onto the CLA homepage). Returns
    {final_url: sorted requested urls} for review — detection and reporting
    only, never an automatic exclusion.
    """
    from urllib.parse import urlparse

    by_final: dict[str, list[str]] = {}
    for requested, final in redirect_map.items():
        req_host = (urlparse(requested).netloc or "").lower()
        fin_host = (urlparse(final).netloc or "").lower()
        if req_host and fin_host and req_host != fin_host:
            by_final.setdefault(final, []).append(requested)
    return {final: sorted(reqs)
            for final, reqs in by_final.items() if len(reqs) >= 2}


def rejection_reason_class(reason: str) -> str:
    """Collapse raw rejection reasons into stable audit classes."""
    if reason == "fetch_failed":
        return "fetch_failed"
    if reason.startswith("redirect_duplicate"):
        return "redirect_duplicate"
    return f"validation:{reason}"


def split_associated_programs(
    assoc: str, known_labels: Optional[set[str]] = None,
) -> list[str]:
    """Recover program labels from the loader's comma-joined metadata string.

    The masters loader joins `associated_programs` with ", " (ChromaDB metadata
    is flat), but several REAL directory labels contain ", " themselves
    (e.g. "Curriculum and Instruction, Elementary Education (MA)"), so a naive
    split fragments them. Given the known label set, fragments are greedily
    re-merged left-to-right until they form a known label; unknown remainders
    are kept verbatim rather than dropped, so the audit never hides data.
    """
    parts = [p.strip() for p in assoc.split(",") if p.strip()] if assoc else []
    if not known_labels:
        return parts
    labels: list[str] = []
    acc = ""
    for part in parts:
        acc = f"{acc}, {part}" if acc else part
        if acc in known_labels:
            labels.append(acc)
            acc = ""
    if acc:                       # unknown remainder — surface, don't hide
        labels.append(acc)
    return labels


def program_chunk_counts(
    chunks: list, known_labels: Optional[set[str]] = None,
) -> dict[str, int]:
    """Chunks attributed to each program label via `associated_programs`.

    Shared pages count toward every associated program (that is what sharing
    means for coverage); chunks with no association are grouped as
    '(unattributed)' so nothing silently disappears from the audit.
    """
    counts: Counter = Counter()
    for doc in chunks:
        assoc = (doc.metadata or {}).get("associated_programs", "")
        labels = split_associated_programs(assoc, known_labels)
        if not labels:
            counts["(unattributed)"] += 1
        for label in labels:
            counts[label] += 1
    return dict(counts)
