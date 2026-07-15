"""
ingestion/masters/review_corpus.py
Deterministic builder for the reviewed master's experiment corpus (Phase P4).

Given a curated selection of program names, it runs the existing ingestion
pipeline for each, computes per-program review facts and aggregate corpus
metrics, and writes canonical records to a caller-provided directory (a temporary
review directory in P4 — never the production corpus). It fabricates nothing:
every field is either source-backed or an honest unknown/source_missing.

Selection is by exact normalized program name. If a selected name matches zero
or more than one discovered listing, it is reported as ambiguous/missing rather
than guessed — the caller decides what to do.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from domain.programs.enums import DataStatus, DegreeType, ExtractionMethod, SourceType
from domain.programs.facts import Fact
from domain.programs.models import CanonicalProgram, CompletenessTier
from domain.programs.validation import ValidationFinding, validate_program
from ingestion.masters.discovery import discover_from_html
from ingestion.masters.fetching import Fetcher
from ingestion.masters.pipeline import _enrich_one, _INDEX_SOURCE_ID
from ingestion.masters.persistence import load_program
from ingestion.masters.snapshots import SnapshotStore, snapshot_to_source
from ingestion.masters.sources_policy import GRADUATE_STUDIES_MASTERS_INDEX_URL

# Curated P4 selection — diverse colleges, degree types, and page layouts/hosts.
# All names are unique in the index and map to a single program page.
SELECTED_PROGRAMS: tuple[str, ...] = (
    "Accountancy",                              # MS  · cob-graduate-programs
    "Athletic Training",                        # MS  · kinesiology
    "Social Work",                              # MSW · school-of-social-work
    "Public Health - Community Health Education",  # MPH · health-science
    "Creative Writing",                         # MFA · cla/english
    "English",                                  # MA  · cla/english
    "Geography",                                # MA  · cla/geography
    "Music",                                     # MM  · web.csulb.edu (distinct host)
    "International Affairs",                     # MA  · cpace.csulb.edu (CPaCE)
    "Philosophy",                               # MA  · www.cla.csulb.edu (distinct subdomain)
    "History",                                  # MA  · cla/history
    "Speech-Language Pathology",                # MA  · health-human-services
    "Economics",                                # MA  · cla/economics (http)
)


@dataclass
class FactStats:
    available: int = 0
    unknown: int = 0
    source_missing: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return self.available + self.unknown + self.source_missing + self.other


@dataclass
class ProgramReview:
    program_id: Optional[str]
    canonical_name: str
    degree_official: Optional[str]
    url: Optional[str]
    validation_status: Optional[str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    fact_stats: FactStats = field(default_factory=FactStats)
    missing_fields: list[str] = field(default_factory=list)
    snapshots: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    canonical_path: Optional[str] = None


@dataclass
class CorpusReviewReport:
    reviews: list[ProgramReview] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def iter_record_facts(program: CanonicalProgram):
    """Yield (field_path, Fact) for every populated Fact across the record."""
    sections = {
        "identity": program.identity, "overview": program.overview,
        "admissions": program.admissions, "application": program.application,
        "contact": program.contact,
    }
    if program.enrichment is not None:
        sections["enrichment"] = program.enrichment
    for section_name, section in sections.items():
        for field_name, value in section.__dict__.items():
            if isinstance(value, Fact):
                yield f"{section_name}.{field_name}", value


def _fact_stats(program: CanonicalProgram) -> tuple[FactStats, list[str]]:
    stats = FactStats()
    missing: list[str] = []
    for path, fact in iter_record_facts(program):
        if fact.data_status == DataStatus.AVAILABLE:
            stats.available += 1
        elif fact.data_status == DataStatus.UNKNOWN:
            stats.unknown += 1
            missing.append(path)
        elif fact.data_status == DataStatus.SOURCE_MISSING:
            stats.source_missing += 1
            missing.append(path)
        else:
            stats.other += 1
    return stats, missing


def _count_fabricated(program: CanonicalProgram) -> int:
    """Fabricated values must be zero: the pipeline never sets a structured ISO
    deadline (it preserves text) and never stores a placeholder identity value."""
    fabricated = 0
    terms = program.application.terms.value if program.application.terms else None
    for term in terms or []:
        if term.deadline is not None or term.accept_decline_deadline is not None:
            fabricated += 1
    # CP-E011 findings (placeholder identity values) also count as fabricated
    fabricated += sum(1 for f in validate_program(program) if f.rule_id == "CP-E011")
    return fabricated


# Widget/boilerplate phrases that indicate an extracted "overview" is not real
# program prose (surfaced by cla.csulb.edu carousel layouts during P4 review).
_BOILERPLATE_OVERVIEW_MARKERS = (
    "this is a carousel", "use next and previous", "skip to main content",
    "go to slide", "javascript is required", "cookie",
)


def _overview_looks_boilerplate(text: Optional[str]) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _BOILERPLATE_OVERVIEW_MARKERS)


def _needs_review(program: CanonicalProgram, review: ProgramReview,
                  page_fetched: bool) -> list[str]:
    flags: list[str] = []
    if not page_fetched:
        flags.append("program page not fetched")
    if program.overview.official_summary.data_status != DataStatus.AVAILABLE:
        flags.append("overview not source-backed")
    elif _overview_looks_boilerplate(program.overview.official_summary.value):
        flags.append("overview likely boilerplate/widget text (extraction work needed)")
    if program.quality.record_completeness == CompletenessTier.MINIMAL:
        flags.append("sparse record (minimal completeness)")
    if program.identity.degree_type == DegreeType.OTHER:
        flags.append("non-standard degree label mapped to Other")
    if program.application.terms.data_status != DataStatus.AVAILABLE:
        flags.append("no published deadlines")
    return flags


def build_review_corpus(
    *,
    fetcher: Fetcher,
    snapshot_store: SnapshotStore,
    out_dir: Path,
    selection: tuple[str, ...] = SELECTED_PROGRAMS,
    index_url: str = GRADUATE_STUDIES_MASTERS_INDEX_URL,
    now: Optional[datetime] = None,
) -> CorpusReviewReport:
    now = now or datetime.now(timezone.utc)
    report = CorpusReviewReport()

    index_fetch = fetcher.fetch(index_url)
    index_snap = snapshot_store.save(program_id="_index", source_id=_INDEX_SOURCE_ID,
                                     source_type=SourceType.DEADLINE_TABLE, fetch=index_fetch)
    index_source = snapshot_to_source(index_snap, extraction_method=ExtractionMethod.TABLE_PARSE)
    manifest = discover_from_html(index_fetch.content, source_url=index_url, discovered_at=now)

    by_name: dict[str, list] = {}
    for prog in manifest.programs:
        by_name.setdefault(prog.normalized_program_name, []).append(prog)

    for name in selection:
        matches = by_name.get(name, [])
        if len(matches) != 1:  # ambiguity guard — never guess
            report.ambiguous.append(f"{name} (matched {len(matches)} listings)")
            continue
        discovered = matches[0]
        result = _enrich_one(discovered, fetcher=fetcher, snapshots=snapshot_store,
                             programs_dir=out_dir, index_source=index_source,
                             freshness_policy=None, now=now)
        review = ProgramReview(
            program_id=result.program_id, canonical_name=name,
            degree_official=discovered.degree_label, url=discovered.official_program_url,
            validation_status=result.validation_status.value if result.validation_status else None,
            errors=[f.rule_id for f in result.findings if f.severity.value == "error"],
            warnings=[f.rule_id for f in result.findings if f.severity.value == "warning"],
            infos=[f.rule_id for f in result.findings if f.severity.value == "informational"],
            canonical_path=result.canonical_path,
        )
        if result.canonical_path:
            program = load_program(Path(result.canonical_path))
            review.fact_stats, review.missing_fields = _fact_stats(program)
            page_fetched = any(s.source_id == "src-program" for s in program.sources)
            review.snapshots = [s.content_hash for s in program.sources]
            review.needs_review = _needs_review(program, review, page_fetched)
            review.needs_review += [f"fabricated values: {_count_fabricated(program)}"] \
                if _count_fabricated(program) else []
        report.reviews.append(review)

    report.metrics = _aggregate(report)
    return report


def _aggregate(report: CorpusReviewReport) -> dict:
    reviews = report.reviews
    n = len(reviews)
    totals = FactStats()
    fabricated = 0
    with_page = 0
    for r in reviews:
        totals.available += r.fact_stats.available
        totals.unknown += r.fact_stats.unknown
        totals.source_missing += r.fact_stats.source_missing
        totals.other += r.fact_stats.other
        if not any("program page not fetched" in f for f in r.needs_review):
            with_page += 1
        fabricated += sum(int(f.split(":")[1]) for f in r.needs_review if f.startswith("fabricated values:"))
    tot = totals.total or 1
    return {
        "programs_processed": n,
        "ambiguous_skipped": len(report.ambiguous),
        "validation_errors": sum(len(r.errors) for r in reviews),
        "validation_warnings": sum(len(r.warnings) for r in reviews),
        "validation_informational": sum(len(r.infos) for r in reviews),
        "facts_total": totals.total,
        "pct_source_backed": round(100 * totals.available / tot, 1),
        "pct_unknown": round(100 * totals.unknown / tot, 1),
        "pct_source_missing": round(100 * totals.source_missing / tot, 1),
        "snapshot_coverage_pct": round(100 * with_page / (n or 1), 1),
        "fabricated_values": fabricated,
    }
