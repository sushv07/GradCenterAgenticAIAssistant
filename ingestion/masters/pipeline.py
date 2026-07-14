"""
ingestion/masters/pipeline.py
Field-driven orchestration: discovery (Stage 1) -> enrichment (Stage 2).

Flow per run:
  1. Fetch the Graduate Studies index -> snapshot -> DiscoveryManifest.
  2. For each discovered program that has an official link (link-less programs
     are recorded as warnings, never fabricated):
       a. Fetch the official program page (priority tier 2) -> snapshot -> extract.
       b. Normalize index + page facts into ONE CanonicalProgram.
       c. Validate deterministically (domain validator).
       d. Persist file-per-program.
  Traversal is field-driven and stops once no further approved source is wired;
  consulting tiers 3-7 (catalog, international, CPaCE, PDFs) plugs into the same
  loop and is a documented extension point, not a crawler.

The pipeline depends only on the injected Fetcher, so it runs fully offline in
tests. It performs no retrieval, embedding, or vector-store work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from domain.programs.config import FreshnessPolicy
from domain.programs.enums import ExtractionMethod, ValidationStatus
from domain.programs.models import CanonicalProgram
from domain.programs.sources import Source
from domain.programs.validation import ValidationFinding, validate_program
from ingestion.masters.discovery import discover_from_html
from ingestion.masters.extraction import extract_program_page
from ingestion.masters.fetching import FetchError, Fetcher
from ingestion.masters.manifest import DiscoveredProgram, DiscoveryManifest
from ingestion.masters.normalization import normalize_program
from ingestion.masters.persistence import persist_program
from ingestion.masters.snapshots import SnapshotStore, snapshot_to_source
from ingestion.masters.sources_policy import (
    GRADUATE_STUDIES_MASTERS_INDEX_URL, SourceType,
)

_INDEX_SOURCE_ID = "src-index"
_PROGRAM_SOURCE_ID = "src-program"


@dataclass
class ProgramResult:
    program_id: Optional[str]
    listing_name: str
    canonical_path: Optional[str] = None
    validation_status: Optional[ValidationStatus] = None
    findings: list[ValidationFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None


@dataclass
class PipelineResult:
    manifest: DiscoveryManifest
    results: list[ProgramResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _errors(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    return [f for f in findings if f.severity.value == "error"]


def _status(findings: list[ValidationFinding]) -> ValidationStatus:
    if _errors(findings):
        return ValidationStatus.INVALID
    if findings:
        return ValidationStatus.VALID_WITH_WARNINGS
    return ValidationStatus.VALID


def _enrich_one(
    discovered: DiscoveredProgram,
    *,
    fetcher: Fetcher,
    snapshots: SnapshotStore,
    programs_dir: Path,
    index_source: Source,
    freshness_policy: Optional[FreshnessPolicy],
    now: datetime,
) -> ProgramResult:
    listing = discovered.normalized_program_name
    if not discovered.official_program_url:
        return ProgramResult(program_id=None, listing_name=listing, skipped=True,
                             skip_reason="missing official program link",
                             warnings=list(discovered.warnings))

    from ingestion.masters.normalization import slugify
    program_id = slugify(listing)

    # priority tier 2 — official program page
    program_facts = None
    program_source = None
    page_warnings: list[str] = []
    try:
        fetched = fetcher.fetch(discovered.official_program_url)
        snap = snapshots.save(program_id=program_id, source_id=_PROGRAM_SOURCE_ID,
                              source_type=SourceType.PROGRAM_PAGE, fetch=fetched)
        program_source = snapshot_to_source(snap, extraction_method=ExtractionMethod.HTML_PARSE)
        program_facts = extract_program_page(fetched.content, source_id=_PROGRAM_SOURCE_ID)
    except FetchError as exc:
        page_warnings.append(f"program page fetch failed: {exc}")

    # index source is re-scoped to this record's id namespace
    record_index_source = index_source.model_copy(update={"source_id": _INDEX_SOURCE_ID})
    sources = [record_index_source]
    if program_source is not None:
        sources.append(program_source.model_copy(update={"source_id": _PROGRAM_SOURCE_ID}))

    program, norm_warnings = normalize_program(
        discovered,
        index_source_id=_INDEX_SOURCE_ID,
        program_facts=program_facts,
        program_source_id=_PROGRAM_SOURCE_ID if program_source else None,
        sources=sources,
        now=now,
    )

    findings = validate_program(program, freshness_policy=freshness_policy, now=now)
    status = _status(findings)
    program = program.model_copy(update={
        "quality": program.quality.model_copy(update={"validation_status": status})
    })

    path = persist_program(program, programs_dir)
    return ProgramResult(
        program_id=program_id, listing_name=listing, canonical_path=str(path),
        validation_status=status, findings=findings,
        warnings=norm_warnings + page_warnings,
    )


def run_pipeline(
    *,
    fetcher: Fetcher,
    snapshot_store: SnapshotStore,
    programs_dir: Path,
    index_url: str = GRADUATE_STUDIES_MASTERS_INDEX_URL,
    freshness_policy: Optional[FreshnessPolicy] = None,
    now: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> PipelineResult:
    now = now or datetime.now(timezone.utc)

    # Stage 1 — discovery
    index_fetch = fetcher.fetch(index_url)
    index_snap = snapshot_store.save(program_id="_index", source_id=_INDEX_SOURCE_ID,
                                     source_type=SourceType.DEADLINE_TABLE, fetch=index_fetch)
    index_source = snapshot_to_source(index_snap, extraction_method=ExtractionMethod.TABLE_PARSE)
    manifest = discover_from_html(index_fetch.content, source_url=index_url, discovered_at=now)

    result = PipelineResult(manifest=manifest)

    # Stage 2 — enrichment (bounded by limit for the representative scope)
    to_process = manifest.programs if limit is None else manifest.programs[:limit]
    for discovered in to_process:
        result.results.append(_enrich_one(
            discovered, fetcher=fetcher, snapshots=snapshot_store, programs_dir=programs_dir,
            index_source=index_source, freshness_policy=freshness_policy, now=now,
        ))
    return result
