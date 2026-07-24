"""
rag/masters_catalog.py
Full-catalog master's acquisition + isolated build orchestration (Phase 8).

Scale, not redesign: runs the SAME acquisition stages as
`rag.masters_ingest.acquire_masters_documents` (directory discovery → nested
discovery → extraction/conversion → directory cards), in the same order with
the same parameters. There is no parallel acquisition path — every stage call
below is the Phase 1–7 code, reused unchanged via its existing injection
points (`fetch_fn` / `fetch_final_fn`).

This module is orchestration ONLY. Concerns are split (Phase 8 refactor):
  - measurement/instrumentation  → rag/masters_catalog_metrics.py
  - markdown report rendering    → rag/masters_catalog_report.py
  - command-line entry point     → rag/masters_catalog_cli.py

The build target is always an ISOLATED store directory (never the production
`chroma_db/` — guarded below): base sources + full master's catalog are
indexed through the shared `ChromaVectorIndex` adapter, mirroring the
Phase 6/7 evaluation-store recipe with the full live directory instead of the
5-seed pilot HTML.

Instrumentation is opt-in via CatalogBuildConfig. `measure_embedding` is a
BENCHMARK-ONLY knob (an explicit `embed_documents` timing pass before the
fused Chroma build, doubling embedding cost for the run); it defaults to off
and is never part of a normal build.

Deterministic given fixed fetch functions; offline tests inject fixture-backed
fetchers and a fake index (tests/test_masters_full_catalog.py). No retriever,
embedding-model, chunking, prompt, or evaluation-framework change anywhere.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from rag.masters_catalog_metrics import (
    CatalogBuildStats, StageTimer, counting_fetch, dead_seed_candidates,
    program_chunk_counts, recording_fetch_final, rejection_reason_class,
    split_associated_programs,
)

# Sanity floor for the live directory: the committed live snapshot fixture
# yields 67 programs. A live parse far below this means the page layout
# changed or the fetch silently degraded — fail loudly, do not build.
MIN_EXPECTED_PROGRAMS = 50


@dataclass(frozen=True)
class CatalogBuildConfig:
    """Behavioral knobs for one full-catalog build.

    `measure_embedding` is benchmark-only instrumentation (see module
    docstring) — keep it False outside explicit measurement runs.
    """

    depth: int = 1
    include_base_sources: bool = True
    measure_embedding: bool = False


def build_full_catalog(
    scratch_dir: str,
    *,
    config: CatalogBuildConfig = CatalogBuildConfig(),
    index_html: Any = None,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
    fetch_final_fn: Optional[Callable[[str], tuple[Optional[str], str]]] = None,
    indexer: Any = None,
) -> tuple[Any, CatalogBuildStats]:
    """Acquire the full master's catalog and build an isolated store.

    Returns (chroma_handle, CatalogBuildStats). `scratch_dir` must NOT be the
    production CHROMA_DIR — guarded below. All fetchers are injectable, and an
    `indexer` (satisfying `build_from_langchain_documents`) may be injected —
    the same seam `ingest_masters_documents` exposes via `pipeline=` — so the
    whole run is deterministic and offline under test fixtures.
    """
    from pathlib import Path

    from config.settings import CHROMA_DIR
    from ingestion.masters.discovery import discover_from_html
    from rag.masters_discovery import (
        MASTERS_INDEX_URL, apply_seed_overrides, discover_masters_program_pages,
    )
    from rag.masters_extraction import (
        build_masters_documents, directory_card_documents, fetch_page_final,
    )
    from rag.pipeline_adapters.chroma_indexer import ChromaVectorIndex
    from rag.pipeline_adapters.hf_embedder import HuggingFaceEmbeddingBackend
    from rag.pipeline_adapters.recursive_chunker import RecursiveCharacterChunker
    from rag.pipeline_adapters.wiring import production_config

    if Path(scratch_dir).resolve() == Path(CHROMA_DIR).resolve():
        raise RuntimeError(
            "full-catalog build must target an isolated directory, "
            f"not the production store ({CHROMA_DIR})")

    stats = CatalogBuildStats()
    timer = StageTimer()

    # -- instrumented fetchers (wrap, never replace, the existing ones) -----
    injected_fetch = fetch_fn is not None
    if fetch_fn is None:
        from rag.ingestion import fetch_page as fetch_fn
    fetch = counting_fetch(fetch_fn, stats)

    if fetch_final_fn is None:
        if injected_fetch:
            # offline injection: final URL == requested (build_masters_documents idiom)
            def fetch_final_fn(u, _f=fetch_fn):
                return _f(u), u
        else:
            fetch_final_fn = fetch_page_final
    fetch_final = recording_fetch_final(fetch_final_fn, stats)

    # -- stage 1: directory discovery ---------------------------------------
    with timer.stage("directory_discovery"):
        html = index_html if index_html is not None else fetch(MASTERS_INDEX_URL)
        if not html:
            raise RuntimeError("master's directory index could not be fetched")
        manifest = discover_from_html(html, source_url=MASTERS_INDEX_URL)

    # Phase 9B: same seed remapping as the production acquire path (verified
    # replacements for rotten directory links; no-op when config is absent).
    programs, applied = apply_seed_overrides(manifest.programs)
    stats.seed_overrides_applied = applied

    stats.programs_discovered = len(manifest.programs)
    seeds = {p.official_program_url for p in programs if p.official_program_url}
    stats.unique_seed_urls = len(seeds)
    stats.seed_hosts = dict(Counter((urlparse(u).netloc or "").lower() for u in seeds))
    stats.programs_with_warnings = sum(1 for p in manifest.programs if p.warnings)
    stats.index_content_hash = manifest.discovery_source_hash

    if stats.programs_discovered < MIN_EXPECTED_PROGRAMS:
        raise RuntimeError(
            f"directory parse found only {stats.programs_discovered} programs "
            f"(expected >= {MIN_EXPECTED_PROGRAMS}) — index layout may have changed")

    # -- stage 2: nested page discovery (full catalog, no program list) -----
    with timer.stage("nested_discovery"):
        result = discover_masters_program_pages(
            programs, depth=config.depth, fetch_fn=fetch)

    agg = result.aggregate()
    stats.unique_pages = agg["total_unique_pages"]
    stats.seed_pages = agg["seed_pages"]
    stats.nested_pages = agg["nested_pages"]
    stats.shared_pages = agg["shared_pages"]
    stats.skipped_no_seed = agg["skipped_no_seed"]
    stats.pages_by_category = agg["by_category"]
    stats.skipped_pages = dict(result.skipped_pages)

    # -- stage 3: extraction → validated KnowledgeDocuments ------------------
    with timer.stage("extraction_conversion"):
        docs, conv = build_masters_documents(
            result.pages, programs, fetch_final_fn=fetch_final)
        cards = directory_card_documents(programs, MASTERS_INDEX_URL)

    stats.pages_processed = conv.total_pages
    stats.documents_accepted = len(docs)
    stats.documents_rejected = conv.documents_rejected
    stats.empty_pages = conv.empty_pages
    stats.duplicate_document_ids = conv.duplicate_document_ids
    stats.missing_metadata = conv.missing_metadata
    stats.directory_card_documents = len(cards)
    stats.rejections_by_reason = dict(Counter(
        rejection_reason_class(r) for _, r in conv.rejections))
    # Phase 9B: cross-host redirect magnets (rotten-seed signature) — reported
    # for review so future directory rot is self-detecting, never auto-dropped.
    stats.dead_seeds = dead_seed_candidates(stats.redirect_map)

    if not docs:
        raise RuntimeError("full-catalog acquisition produced 0 accepted documents")
    if conv.duplicate_document_ids:
        raise RuntimeError(
            f"{conv.duplicate_document_ids} duplicate document IDs after "
            "redirect canonicalization — deduplication invariant broken")

    # program coverage: which programs have at least one accepted PAGE document.
    # Labels may contain ", " (the loader's join separator), so association
    # strings are re-parsed against the known label set — see
    # split_associated_programs.
    labels = [f"{p.normalized_program_name} ({p.degree_label})"
              if p.degree_label else p.normalized_program_name
              for p in programs]
    label_set = set(labels)
    covered: set[str] = set()
    for d in docs:
        covered.update(split_associated_programs(
            d.metadata.get("associated_programs", ""), label_set))
    stats.programs_with_page_content = sorted(l for l in labels if l in covered)
    stats.programs_without_page_content = sorted(l for l in labels if l not in covered)

    # -- stage 4: chunking (same production chunker as every source) ---------
    from langchain_core.documents import Document

    with timer.stage("chunking"):
        chunker = RecursiveCharacterChunker(production_config())
        masters_chunks = [
            Document(page_content=c.text, metadata=dict(c.metadata))
            for kd in list(docs) + cards
            for c in chunker.chunk(kd)
        ]

    stats.masters_chunks = len(masters_chunks)
    stats.chunks_per_program = program_chunk_counts(masters_chunks, label_set)
    if not masters_chunks:
        raise RuntimeError("chunking produced 0 master's chunks")

    # -- stage 5: base sources (Phase 6/7 recipe, unchanged) -----------------
    base_chunks: list = []
    if config.include_base_sources:
        from rag.chunking import chunk_documents
        from rag.ingestion import ingest_pages

        with timer.stage("base_sources"):
            base_chunks = chunk_documents(ingest_pages(use_discovery=False))
    stats.base_chunks = len(base_chunks)

    all_chunks = base_chunks + masters_chunks
    stats.total_chunks = len(all_chunks)

    # -- stage 6: embed + index into the ISOLATED store ----------------------
    if indexer is None:
        cfg = production_config()
        backend = HuggingFaceEmbeddingBackend(cfg)
        if config.measure_embedding:   # benchmark-only timing pass
            with timer.stage("embedding_measured"):
                backend.langchain_embeddings.embed_documents(
                    [d.page_content for d in all_chunks])
        indexer = ChromaVectorIndex(
            persist_directory=str(scratch_dir),
            collection_name=cfg.collection_name,
            embedding_backend=backend,
            distance=cfg.distance,
        )

    with timer.stage("index_fused_embed_and_index"):
        handle = indexer.build_from_langchain_documents(all_chunks)
    if "embedding_measured" in timer.raw:
        timer.raw["indexing_derived"] = max(
            0.0, timer.raw["index_fused_embed_and_index"]
            - timer.raw["embedding_measured"])

    stats.indexed_vectors = handle._collection.count()
    stats.timings_s = timer.finalize()
    return handle, stats
