"""
rag/masters_discovery.py
Master's nested page discovery — orchestration over the existing crawler.

Reuses rag.discovery UNCHANGED for the actual crawl of each program
(`discover_program_pages`: bounded depth, same-domain, per-program dedup,
overview-only discard, workflow-priority classification via `classify_page` /
`score_link_relevance`). This module only ADDS the master's-specific layer:

  1. drive the crawl from a Phase-1 DiscoveryManifest (seed = official_program_url),
  2. CROSS-PROGRAM deduplication — a department page shared by several programs
     (e.g. the 4 Linguistics tracks) is crawled once and associated with every
     program that points at it,
  3. a discovery summary (per-program + aggregate) for review.

It lives in rag/ (not ingestion/) because the reused crawler is under rag/ and
`ingestion/` is guarded to stay infra-free — so ingestion cannot import it. The
orchestrator is pure composition: no new crawl algorithm, no fetching of its own
(a `fetch_fn` is threaded straight through for deterministic, fixture-based tests).

Scope: discovery + classification ONLY. No content extraction, normalization,
CanonicalProgram, or KnowledgeDocument work happens here.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from ingestion.masters.manifest import DiscoveredProgram
from rag.discovery import discover_program_pages


def canonical_url(url: str) -> str:
    """Deterministic canonical form: drop the fragment and utm_* tracking params.

    Phase 7 evidence: the same shared international page was crawled as
    `…/international/?utm_source=…&utm_campaign=JumboMenu`, defeating URL-level
    deduplication. Non-tracking query params are preserved.
    """
    p = urlparse(url or "")
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunparse((p.scheme, p.netloc, p.path, p.params,
                       urlencode(query), ""))


def _nested_host_allowed(seed_url: str, url: str) -> bool:
    """Nav-bleed guard: a nested page must be on the seed's host or www.csulb.edu.

    Phase 6/7 evidence: department nav menus leak links to other subdomains'
    marketing pages (cpace.csulb.edu / www.ccpe.csulb.edu degree ads — 208 chunks
    of noise attributed to Linguistics/Political Science). Keeping the seed's own
    host preserves all legitimate department subpages; keeping www.csulb.edu
    preserves shared central resources (admissions, graduate center). Host-level
    policy — no individual program is hardcoded.
    """
    seed_host = (urlparse(seed_url).netloc or "").lower()
    host = (urlparse(url).netloc or "").lower()
    return host == seed_host or host == "www.csulb.edu"

# Phase 9A — corpus hygiene guards (deterministic, URL-based, no fetching).

# Binary/office formats the extractor cannot parse (it is an HTML extractor;
# feeding it a PDF byte stream produced 512 garbled chunks in the Phase 8
# audit). Extend only alongside a dedicated extraction pipeline.
_UNSUPPORTED_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx")

# A URL whose FINAL path segment is exactly a term-year slug (e.g. `fall-2021`)
# is a term-scoped announcement/archive page, not an evergreen program page.
# Phase 8 evidence: `…/college-of-health-human-services/fall-2021` (67 chunks
# of stale COVID-era content, top hit for a negative eval case). The rule is
# static and narrow: segments that merely CONTAIN a term-year (e.g.
# `fall-2026-deadlines`) are untouched, so legitimate deadline pages survive.
_OBSOLETE_TERM_SLUG = re.compile(r"^(fall|spring|summer|winter)-(19|20)\d{2}$")


def is_supported_resource(url: str) -> bool:
    """False for URLs whose (decoded) path ends in a non-HTML document type."""
    path = unquote(urlparse(url or "").path or "").lower().rstrip("/")
    return not path.endswith(_UNSUPPORTED_EXTENSIONS)


def is_obsolete_term_page(url: str) -> bool:
    """True when the last path segment is exactly a term-year archive slug."""
    segments = [s for s in unquote(urlparse(url or "").path or "").split("/") if s]
    return bool(segments) and bool(_OBSOLETE_TERM_SLUG.match(segments[-1].lower()))


# The master's directory the seeds were discovered from (provenance only).
MASTERS_INDEX_URL = (
    "https://www.csulb.edu/graduate-studies-csulb/article/"
    "programs-advisors-and-deadlines-masters"
)


def _program_label(p: DiscoveredProgram) -> str:
    return f"{p.normalized_program_name} ({p.degree_label})" if p.degree_label \
        else p.normalized_program_name


@dataclass
class DiscoveredPage:
    """One unique page (by URL) and every program associated with it."""

    url: str
    title: str
    content_category: str        # from rag.discovery.classify_page
    workflow_priority: int
    parent_program_url: str      # "" for a program seed page
    discovered_from: str
    depth: int                   # 0 = seed, 1 = nested
    program_family: str = "masters"
    programs: list[str] = field(default_factory=list)  # all associated programs


@dataclass
class ProgramCrawlSummary:
    program_name: str
    degree_label: Optional[str]
    seed_url: str
    reused_shared_seed: bool             # seed already crawled by another program
    pages_accepted: int                  # pages returned by the reused crawler
    max_depth_reached: int
    classifications: dict[str, int] = field(default_factory=dict)


@dataclass
class MastersDiscoveryResult:
    pages: list[DiscoveredPage]          # globally unique by URL
    programs: list[ProgramCrawlSummary]
    skipped_no_seed: list[str] = field(default_factory=list)
    # Phase 9A: nested pages dropped by hygiene guards — {url: reason}, unique
    # by canonical URL, so the audit can report every exclusion with its cause.
    skipped_pages: dict[str, str] = field(default_factory=dict)

    def aggregate(self) -> dict[str, Any]:
        shared = [p for p in self.pages if len(p.programs) > 1]
        cats = Counter(p.content_category for p in self.pages)
        n_prog = len(self.programs) or 1
        return {
            "pilot_programs": len(self.programs),
            "total_unique_pages": len(self.pages),
            "avg_pages_per_program": round(sum(s.pages_accepted for s in self.programs) / n_prog, 2),
            "shared_pages": len(shared),
            "seed_pages": sum(1 for p in self.pages if p.depth == 0),
            "nested_pages": sum(1 for p in self.pages if p.depth == 1),
            "skipped_no_seed": len(self.skipped_no_seed),
            "skipped_pages": dict(Counter(self.skipped_pages.values())),
            "by_category": dict(sorted(cats.items())),
        }


def discover_masters_program_pages(
    programs: Sequence[DiscoveredProgram],
    *,
    depth: int = 1,
    index_url: str = MASTERS_INDEX_URL,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> MastersDiscoveryResult:
    """Crawl + classify nested pages for the given programs, deduped across programs."""
    pages_by_url: dict[str, DiscoveredPage] = {}
    seed_cache: dict[str, list[dict]] = {}     # seed_url -> discover_program_pages output
    summaries: list[ProgramCrawlSummary] = []
    skipped: list[str] = []
    skipped_pages: dict[str, str] = {}

    for prog in programs:
        seed = prog.official_program_url
        label = _program_label(prog)
        if not seed:
            skipped.append(label)
            continue

        reused = seed in seed_cache
        raw_pages = seed_cache[seed] if reused else discover_program_pages(
            program_name=label, seed_url=seed, index_url=index_url,
            depth=depth, fetch_fn=fetch_fn,
        )
        if not reused:
            seed_cache[seed] = raw_pages

        classifications: Counter = Counter()
        max_depth = 0
        for rp in raw_pages:
            url = canonical_url(rp["url"])
            d = 0 if not rp.get("parent_program_url") else 1
            # Guards apply to NESTED pages only — seed pages are always kept
            # (seeds come from the official directory).
            if d == 1:
                # Nav-bleed guard: stay on the seed's host or www.csulb.edu.
                if not _nested_host_allowed(seed, url):
                    continue
                # Phase 9A hygiene: no binary documents, no term archives.
                if not is_supported_resource(url):
                    skipped_pages[url] = "unsupported_resource_type"
                    continue
                if is_obsolete_term_page(url):
                    skipped_pages[url] = "obsolete_term_archive"
                    continue
            max_depth = max(max_depth, d)
            classifications[rp["content_category"]] += 1

            existing = pages_by_url.get(url)
            if existing is None:
                pages_by_url[url] = DiscoveredPage(
                    url=url, title=rp.get("title", ""),
                    content_category=rp["content_category"],
                    workflow_priority=rp["workflow_priority"],
                    parent_program_url=rp.get("parent_program_url", ""),
                    discovered_from=rp.get("discovered_from", ""),
                    depth=d, programs=[label],
                )
            elif label not in existing.programs:
                existing.programs.append(label)   # cross-program association, no re-crawl

        summaries.append(ProgramCrawlSummary(
            program_name=prog.normalized_program_name, degree_label=prog.degree_label,
            seed_url=seed, reused_shared_seed=reused, pages_accepted=len(raw_pages),
            max_depth_reached=max_depth, classifications=dict(classifications),
        ))

    return MastersDiscoveryResult(
        pages=list(pages_by_url.values()), programs=summaries,
        skipped_no_seed=skipped, skipped_pages=skipped_pages)


def render_markdown(result: MastersDiscoveryResult) -> str:
    agg = result.aggregate()
    L = ["# Master's Nested Page Discovery — Pilot Report", "",
         "## Crawl statistics", "",
         f"- pilot programs: {agg['pilot_programs']}",
         f"- total unique pages: {agg['total_unique_pages']} "
         f"(seed {agg['seed_pages']} · nested {agg['nested_pages']})",
         f"- avg pages per program: {agg['avg_pages_per_program']}",
         f"- shared pages (>1 program): {agg['shared_pages']}",
         f"- programs skipped (no seed): {agg['skipped_no_seed']}", "",
         "## Pages by classification", ""]
    for cat, n in agg["by_category"].items():
        L.append(f"- {cat}: {n}")
    L += ["", "## Per-program", ""]
    for s in result.programs:
        L.append(f"### {s.program_name} ({s.degree_label})")
        L.append(f"- seed: {s.seed_url}")
        L.append(f"- reused shared seed: {s.reused_shared_seed}")
        L.append(f"- pages accepted: {s.pages_accepted} · max depth: {s.max_depth_reached}")
        L.append(f"- classifications: {s.classifications}")
        L.append("")
    shared = [p for p in result.pages if len(p.programs) > 1]
    if shared:
        L += ["## Shared pages (crawled once, multiple programs)", ""]
        for p in shared:
            L.append(f"- `{p.url}` [{p.content_category}] → {p.programs}")
    return "\n".join(L) + "\n"
