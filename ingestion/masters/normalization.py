"""
ingestion/masters/normalization.py
Stage 2b — normalize discovered + extracted facts into ONE CanonicalProgram.

Every program, regardless of page layout, produces the same canonical structure.
Missing values use the established null + data_status contract:
  - source consulted but field absent   -> source_missing
  - source not consulted for this field  -> unknown
Deadlines preserve published distinctions exactly: "Not Accepting" becomes a
not_accepting term (never unknown), and accept/decline deadlines are kept
separate from application deadlines. International deadlines are never inferred
from domestic ones — absent an international source they remain unknown.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from domain.programs.enums import (
    Audience, CompletenessTier, DataStatus, DeadlineKind, DegreeType,
    LifecycleState, ProgramLevel, ReviewStatus, UpdateKind, ValidationStatus,
    Volatility,
)
from domain.programs.facts import Fact
from domain.programs.models import (
    Admissions, Application, ApplicationTerm, CanonicalProgram, Contact,
    ContactSection, CURRENT_SCHEMA_VERSION, Identity, Overview, QualityMetadata,
    RevisionEvent, TestRequirement,
)
from domain.programs.sources import Source
from ingestion.masters.extraction import ExtractedFacts
from ingestion.masters.manifest import DiscoveredProgram

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
_MONTH_DAY = re.compile(r"([A-Za-z]+)\s+(\d{1,2})")
_GPA_NUM = re.compile(r"(\d(?:\.\d{1,2})?)")
_NOT_ACCEPTING = re.compile(r"not\s+accept", re.IGNORECASE)
_DEGREE_MAP = {d.value.upper(): d for d in DegreeType if d != DegreeType.OTHER}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _map_degree(label: Optional[str]) -> tuple[DegreeType, Optional[str]]:
    """Map the published degree label to an enum; preserve the official label
    verbatim (None when no label was published — never a placeholder string)."""
    official = (label or "").strip() or None
    if label:
        key = label.strip().upper().replace(".", "")
        if key in _DEGREE_MAP:
            return _DEGREE_MAP[key], official
    return DegreeType.OTHER, official


def _identity_fact(value: Optional[str], *, page_fetched: bool, program_ref: Optional[str]) -> Fact[str]:
    """Represent a provenance-sensitive identity field honestly:
      value present         -> available (source-backed)
      page consulted, absent -> source_missing
      page not consulted     -> unknown
    """
    if value and value.strip():
        return Fact[str](value=value.strip(), data_status=DataStatus.AVAILABLE,
                         volatility=Volatility.STABLE, primary_source_ref=program_ref)
    if page_fetched:
        return Fact[str](value=None, data_status=DataStatus.SOURCE_MISSING,
                         volatility=Volatility.STABLE, primary_source_ref=program_ref)
    return Fact[str](value=None, data_status=DataStatus.UNKNOWN, volatility=Volatility.STABLE)


def parse_gpa(statement: Optional[str]) -> Optional[float]:
    if not statement:
        return None
    for m in _GPA_NUM.finditer(statement):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if 2.0 <= val <= 4.0:
            return val
    return None


def parse_gre(statement: Optional[str]) -> Optional[TestRequirement]:
    if not statement:
        return None
    s = statement.lower()
    if any(k in s for k in ("not required", "waived", "optional", "no gre")):
        return TestRequirement(test="GRE", required=False, waiver_conditions=statement.strip())
    if "required" in s:
        return TestRequirement(test="GRE", required=True, waiver_conditions=None)
    return None


def parse_month_day(text: Optional[str], year: int) -> Optional[date]:
    if not text:
        return None
    m = _MONTH_DAY.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    try:
        return date(year, month, int(m.group(2)))
    except ValueError:
        return None


def _build_terms(
    discovered: DiscoveredProgram, *, fall_year: int, spring_year: int,
) -> tuple[list[ApplicationTerm], list[str]]:
    terms: list[ApplicationTerm] = []
    warnings: list[str] = []

    def add(season: str, year: int, app_raw: Optional[str], ad_raw: Optional[str]) -> None:
        if not app_raw:
            return
        if _NOT_ACCEPTING.search(app_raw):
            terms.append(ApplicationTerm(
                term=f"{season}_{year}", audience=Audience.DOMESTIC,
                deadline_kind=DeadlineKind.NOT_ACCEPTING, deadline=None,
                accept_decline_deadline=None, notes="Not Accepting (as published)"))
            return
        deadline = parse_month_day(app_raw, year)
        ad = parse_month_day(ad_raw, year) if ad_raw and not _NOT_ACCEPTING.search(ad_raw) else None
        if deadline is None:
            warnings.append(f"{season} application deadline unparseable: '{app_raw}'")
        terms.append(ApplicationTerm(
            term=f"{season}_{year}", audience=Audience.DOMESTIC,
            deadline_kind=DeadlineKind.FINAL, deadline=deadline,
            accept_decline_deadline=ad,
            notes=None if deadline else f"raw: {app_raw}"))

    add("fall", fall_year, discovered.fall_application_deadline, discovered.fall_accept_decline_deadline)
    add("spring", spring_year, discovered.spring_application_deadline, discovered.spring_accept_decline_deadline)
    return terms, warnings


def normalize_program(
    discovered: DiscoveredProgram,
    *,
    index_source_id: str,
    program_facts: Optional[ExtractedFacts],
    program_source_id: Optional[str],
    sources: list[Source],
    fall_year: int,
    spring_year: int,
    now: datetime,
) -> tuple[CanonicalProgram, list[str]]:
    if not discovered.official_program_url:
        raise ValueError("normalize_program requires an official_program_url; "
                         "the pipeline must skip link-less programs")
    warnings: list[str] = list(discovered.warnings)
    page = program_facts if (program_facts and program_facts.page_fetched) else None
    prog_ref = program_source_id if page else None
    degree_type, degree_official = _map_degree(discovered.degree_label)

    # ── overview ──────────────────────────────────────────────────────────
    if page and page.overview_text:
        summary = Fact[str](value=page.overview_text, data_status=DataStatus.AVAILABLE,
                            volatility=Volatility.STABLE, primary_source_ref=prog_ref)
    elif page:
        summary = Fact[str](value=None, data_status=DataStatus.SOURCE_MISSING,
                            volatility=Volatility.STABLE, primary_source_ref=prog_ref)
    else:
        summary = Fact[str](value=None, data_status=DataStatus.UNKNOWN, volatility=Volatility.STABLE)

    stem = (Fact[bool](value=discovered.stem_designated, data_status=DataStatus.AVAILABLE,
                       volatility=Volatility.STABLE, primary_source_ref=index_source_id)
            if discovered.stem_designated is not None
            else Fact[bool](value=None, data_status=DataStatus.UNKNOWN, volatility=Volatility.STABLE))

    overview = Overview(official_summary=summary, stem_designated=stem)

    # ── admissions ────────────────────────────────────────────────────────
    gpa_val = parse_gpa(page.gpa_statement) if page else None
    if gpa_val is not None:
        minimum_gpa = Fact[float](value=gpa_val, data_status=DataStatus.AVAILABLE,
                                  volatility=Volatility.MODERATE, primary_source_ref=prog_ref)
    elif page:
        minimum_gpa = Fact[float](value=None, data_status=DataStatus.SOURCE_MISSING,
                                  volatility=Volatility.MODERATE, primary_source_ref=prog_ref)
    else:
        minimum_gpa = Fact[float](value=None, data_status=DataStatus.UNKNOWN, volatility=Volatility.MODERATE)

    gre = parse_gre(page.gre_statement) if page else None
    if gre is not None:
        tests = Fact[list[TestRequirement]](value=[gre], data_status=DataStatus.AVAILABLE,
                                            volatility=Volatility.MODERATE, primary_source_ref=prog_ref)
    elif page:
        tests = Fact[list[TestRequirement]](value=None, data_status=DataStatus.SOURCE_MISSING,
                                            volatility=Volatility.MODERATE, primary_source_ref=prog_ref)
    else:
        tests = Fact[list[TestRequirement]](value=None, data_status=DataStatus.UNKNOWN,
                                            volatility=Volatility.MODERATE)

    # International distinctions are NEVER inferred from domestic data.
    intl = Fact[list[str]](value=None, data_status=DataStatus.UNKNOWN, volatility=Volatility.MODERATE)

    admissions = Admissions(minimum_gpa=minimum_gpa, tests=tests, intl_distinctions=intl)

    # ── application terms (domestic, from the index) ──────────────────────
    terms_list, term_warnings = _build_terms(discovered, fall_year=fall_year, spring_year=spring_year)
    warnings.extend(term_warnings)
    if terms_list:
        terms = Fact[list[ApplicationTerm]](value=terms_list, data_status=DataStatus.AVAILABLE,
                                            volatility=Volatility.TIME_SENSITIVE,
                                            primary_source_ref=index_source_id)
    else:
        terms = Fact[list[ApplicationTerm]](value=None, data_status=DataStatus.SOURCE_MISSING,
                                            volatility=Volatility.TIME_SENSITIVE,
                                            primary_source_ref=index_source_id)
    application = Application(terms=terms)

    # ── contact (advisor/program office from the index) ───────────────────
    if discovered.advisor_office or discovered.phone:
        contact_val = Contact(name=discovered.advisor_office, phone=discovered.phone,
                              source_ref=index_source_id)
        dept_contact = Fact[Contact](value=contact_val, data_status=DataStatus.AVAILABLE,
                                     volatility=Volatility.MODERATE, primary_source_ref=index_source_id)
    else:
        dept_contact = Fact[Contact](value=None, data_status=DataStatus.SOURCE_MISSING,
                                     volatility=Volatility.MODERATE, primary_source_ref=index_source_id)
    contact = ContactSection(department_contact=dept_contact)

    # ── completeness heuristic ────────────────────────────────────────────
    have_core = (summary.data_status == DataStatus.AVAILABLE
                 and terms.data_status == DataStatus.AVAILABLE
                 and (minimum_gpa.data_status == DataStatus.AVAILABLE
                      or tests.data_status == DataStatus.AVAILABLE))
    completeness = CompletenessTier.CORE if have_core else CompletenessTier.MINIMAL

    program = CanonicalProgram(
        schema_version=CURRENT_SCHEMA_VERSION,
        record_id=f"rec-{slugify(discovered.normalized_program_name)}",
        program_level=ProgramLevel.MASTERS,
        identity=Identity(
            program_id=slugify(discovered.normalized_program_name),
            canonical_name=discovered.normalized_program_name,
            aliases=[],
            degree_type=degree_type,
            degree_type_official=degree_official,
            college=_identity_fact(page.college if page else None,
                                   page_fetched=bool(page), program_ref=prog_ref),
            department=_identity_fact(page.department if page else None,
                                      page_fetched=bool(page), program_ref=prog_ref),
            official_program_url=discovered.official_program_url,
        ),
        overview=overview,
        admissions=admissions,
        application=application,
        contact=contact,
        sources=sources,
        quality=QualityMetadata(
            record_completeness=completeness,
            validation_status=ValidationStatus.UNVALIDATED,
            manual_review_status=ReviewStatus.NOT_REVIEWED,
            lifecycle_state=LifecycleState.ACTIVE,
            last_verified=now.date(),
            revision_history=[RevisionEvent(at=now, kind=UpdateKind.CREATED,
                                            fields_changed=[], note="ingested via masters pipeline")],
        ),
    )
    return program, warnings
