"""
domain/programs/validation.py
Deterministic validation for CanonicalProgram records (Phase P1).

Returns a list of structured ValidationFinding objects (error | warning |
informational) rather than throwing — the validator is the reachable gate for
cross-field, source-resolution, and policy rules. Pure Fact-envelope rules are
enforced at construction time (domain.programs.facts); this module does NOT duplicate
them. It focuses on:
  - identity + corpus-level rules (ids, urls, aliases, schema version),
  - source-reference RESOLUTION against the record's sources[],
  - empty-string scanning across nested plain models,
  - freshness (via an injected FreshnessPolicy — no hardcoded windows),
  - completeness / review / degree / domestic-international consistency,
  - informational lifecycle + optional-data notes.

No internet, embeddings, Chroma, or model access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Iterator, Optional
from urllib.parse import urlparse

from domain.programs.config import FreshnessPolicy
from domain.programs.enums import (
    Audience,
    CompletenessTier,
    DataStatus,
    DeadlineKind,
    DegreeType,
    LifecycleState,
    ReviewStatus,
    ValidationSeverity,
)
from domain.programs.facts import Fact
from domain.programs.models import CanonicalProgram, Contact

_PROGRAM_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DEFAULT_SUPPORTED_SCHEMAS = ("masters-1.0",)
_ALLOWED_OFFICIAL_HOST_SUFFIX = "csulb.edu"
# Placeholder tokens that must never stand in for missing identity data.
# (Empty strings are handled separately by CP-E009.)
_FORBIDDEN_PLACEHOLDERS = {"unspecified", "unknown", "n/a", "na", "tbd", "none", "null", "-"}


@dataclass(frozen=True)
class ValidationFinding:
    rule_id: str
    severity: ValidationSeverity
    field_path: str
    message: str


def _err(rule_id: str, path: str, msg: str) -> ValidationFinding:
    return ValidationFinding(rule_id, ValidationSeverity.ERROR, path, msg)


def _warn(rule_id: str, path: str, msg: str) -> ValidationFinding:
    return ValidationFinding(rule_id, ValidationSeverity.WARNING, path, msg)


def _info(rule_id: str, path: str, msg: str) -> ValidationFinding:
    return ValidationFinding(rule_id, ValidationSeverity.INFORMATIONAL, path, msg)


# ---------------------------------------------------------------------------
# Structure walkers
# ---------------------------------------------------------------------------

def _iter_facts(program: CanonicalProgram) -> Iterator[tuple[str, Fact]]:
    """Yield (field_path, Fact) for every populated Fact in the record."""
    sections = {
        "identity": program.identity,   # college / department are Facts
        "overview": program.overview,
        "admissions": program.admissions,
        "application": program.application,
        "contact": program.contact,
    }
    if program.enrichment is not None:
        sections["enrichment"] = program.enrichment
    for section_name, section in sections.items():
        for field_name, value in section.__dict__.items():
            if isinstance(value, Fact):
                yield f"{section_name}.{field_name}", value


def _iter_contacts(program: CanonicalProgram) -> Iterator[tuple[str, Contact]]:
    """Yield (field_path, Contact) for contact-bearing facts."""
    candidates = [
        ("contact.department_contact", program.contact.department_contact),
        ("contact.coordinator_or_advisor", program.contact.coordinator_or_advisor),
    ]
    if program.enrichment is not None:
        candidates.append(("enrichment.advisor", program.enrichment.advisor))
    for path, fact in candidates:
        if isinstance(fact, Fact) and isinstance(fact.value, Contact):
            yield path, fact


def _walk_strings(obj: object, path: str) -> Iterator[tuple[str, str]]:
    """Yield (path, str) for every string leaf in a model_dump(json) tree."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, val in obj.items():
            yield from _walk_strings(val, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _walk_strings(val, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_program(
    program: CanonicalProgram,
    *,
    corpus_program_ids: Optional[Iterable[str]] = None,
    freshness_policy: Optional[FreshnessPolicy] = None,
    supported_schema_versions: Iterable[str] = _DEFAULT_SUPPORTED_SCHEMAS,
    now: Optional[datetime] = None,
) -> list[ValidationFinding]:
    """Validate one record; returns findings ordered error → warning → info."""
    now = now or datetime.now(timezone.utc)
    findings: list[ValidationFinding] = []
    ident = program.identity

    # ── ERRORS ────────────────────────────────────────────────────────────

    # CP-E001 program_id format
    if not _PROGRAM_ID_RE.match(ident.program_id or ""):
        findings.append(_err("CP-E001", "identity.program_id",
                             "program_id must be lowercase kebab-case"))

    # CP-E002 duplicate program_id within the supplied corpus
    if corpus_program_ids is not None:
        others = list(corpus_program_ids)
        if others.count(ident.program_id) > 1:
            findings.append(_err("CP-E002", "identity.program_id",
                                 f"duplicate program_id '{ident.program_id}' in corpus"))

    # CP-E003 canonical_name present
    if not ident.canonical_name or ident.canonical_name.strip() == "":
        findings.append(_err("CP-E003", "identity.canonical_name",
                             "canonical_name is required and must be non-empty"))

    # CP-E004 official_program_url valid http(s)
    if not _is_http_url(ident.official_program_url):
        findings.append(_err("CP-E004", "identity.official_program_url",
                             "official_program_url must be an http(s) URL"))

    # CP-E005 duplicate aliases
    if len(set(ident.aliases)) != len(ident.aliases):
        findings.append(_err("CP-E005", "identity.aliases",
                             "aliases must not contain duplicates"))

    # CP-E006 alias equals canonical_name
    if ident.canonical_name in ident.aliases:
        findings.append(_err("CP-E006", "identity.aliases",
                             "an alias must not equal canonical_name"))

    # CP-E007 unresolved source references (fact-level + contact-level)
    known_ids = {s.source_id for s in program.sources}
    for path, fact in _iter_facts(program):
        for ref in fact.all_source_refs():
            if ref not in known_ids:
                findings.append(_err("CP-E007", path,
                                     f"source_ref '{ref}' does not resolve to any sources[] entry"))
    for path, fact in _iter_contacts(program):
        c = fact.value
        if c.source_ref is not None and c.source_ref not in known_ids:
            findings.append(_err("CP-E007", f"{path}.value.source_ref",
                                 f"contact source_ref '{c.source_ref}' does not resolve"))

    # CP-E008 unrecognized schema version
    if program.schema_version not in set(supported_schema_versions):
        findings.append(_err("CP-E008", "schema_version",
                             f"unrecognized schema_version '{program.schema_version}'"))

    # CP-E009 empty-string missing value anywhere in the record
    for path, text in _walk_strings(program.model_dump(mode="json"), ""):
        if text.strip() == "":
            findings.append(_err("CP-E009", path,
                                 "empty/whitespace string is not a valid value; use null"))

    # CP-E010 available contact whose meaningful fields are all null
    for path, fact in _iter_contacts(program):
        if fact.data_status == DataStatus.AVAILABLE and not fact.value.has_meaningful_value():
            findings.append(_err("CP-E010", f"{path}.value",
                                 "contact marked available but name/email/phone/office are all null"))

    # CP-E011 placeholder token used as an identity value (never a stand-in for
    # missing data — use null + data_status instead)
    identity_strings: list[tuple[str, object]] = [
        ("identity.program_id", ident.program_id),
        ("identity.canonical_name", ident.canonical_name),
        ("identity.degree_type_official", ident.degree_type_official),
        ("identity.college.value", ident.college.value),
        ("identity.department.value", ident.department.value),
    ]
    for path, value in identity_strings:
        if isinstance(value, str) and value.strip().lower() in _FORBIDDEN_PLACEHOLDERS:
            findings.append(_err("CP-E011", path,
                                 f"'{value}' is a placeholder, not a value; use null + data_status"))

    # ── WARNINGS ──────────────────────────────────────────────────────────

    # CP-W001 official source outside allowed CSULB host
    for i, src in enumerate(program.sources):
        if src.official and not _host_allowed(src.source_url):
            findings.append(_warn("CP-W001", f"sources[{i}].source_url",
                                  "official source URL is outside the allowed csulb.edu host"))

    # CP-W002 stale fact per injected freshness policy
    if freshness_policy is not None:
        now_date = now.date()
        for path, fact in _iter_facts(program):
            if fact.data_status != DataStatus.AVAILABLE:
                continue
            verified = _fact_reference_date(fact, program)
            if verified is None:
                continue
            window = freshness_policy.window_days(fact.volatility)
            if (now_date - verified).days > window:
                findings.append(_warn("CP-W002", path,
                                      f"available fact is older than the {fact.volatility.value} "
                                      f"freshness window ({window}d); should be re-verified/marked stale"))

    # CP-W003 sparse completeness
    if program.quality.record_completeness == CompletenessTier.MINIMAL:
        findings.append(_warn("CP-W003", "quality.record_completeness",
                              "record completeness is 'minimal' — sparse record"))

    # CP-W004 inconsistent domestic/international terms
    findings.extend(_check_term_consistency(program))

    # CP-W005 unreviewed record
    if program.quality.manual_review_status == ReviewStatus.NOT_REVIEWED:
        findings.append(_warn("CP-W005", "quality.manual_review_status",
                              "record has not been human-reviewed"))

    # CP-W006 ambiguous degree mapped to Other
    if ident.degree_type == DegreeType.OTHER:
        preserved = ident.degree_type_official and ident.degree_type_official.strip() != ""
        msg = ("degree_type mapped to 'Other'; official value preserved in degree_type_official"
               if preserved else
               "degree_type is 'Other' but degree_type_official does not preserve the official value")
        findings.append(_warn("CP-W006", "identity.degree_type", msg))

    # CP-W007 enriched tier without enrichment data
    if program.quality.record_completeness == CompletenessTier.ENRICHED and program.enrichment is None:
        findings.append(_warn("CP-W007", "enrichment",
                              "record marked 'enriched' but no enrichment data is present"))

    # ── INFORMATIONAL ─────────────────────────────────────────────────────

    if program.enrichment is None:
        findings.append(_info("CP-I001", "enrichment", "no optional enrichment present"))
    if _has_no_deadlines(program):
        findings.append(_info("CP-I002", "application.terms", "no deadlines currently available"))
    if program.quality.lifecycle_state == LifecycleState.ARCHIVED:
        findings.append(_info("CP-I003", "quality.lifecycle_state", "record lifecycle is archived"))
    if not ident.aliases:
        findings.append(_info("CP-I004", "identity.aliases", "no aliases recorded"))
    if program.quality.manual_review_status == ReviewStatus.REVIEWED:
        findings.append(_info("CP-I005", "quality.manual_review_status",
                              "manual review completed"))

    return findings


def validate_corpus(
    programs: list[CanonicalProgram],
    *,
    freshness_policy: Optional[FreshnessPolicy] = None,
    supported_schema_versions: Iterable[str] = _DEFAULT_SUPPORTED_SCHEMAS,
    now: Optional[datetime] = None,
) -> dict[str, list[ValidationFinding]]:
    """Validate many records; program_id-collision detection spans the corpus."""
    ids = [p.identity.program_id for p in programs]
    return {
        p.identity.program_id: validate_program(
            p,
            corpus_program_ids=ids,
            freshness_policy=freshness_policy,
            supported_schema_versions=supported_schema_versions,
            now=now,
        )
        for p in programs
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _host_allowed(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    return host == _ALLOWED_OFFICIAL_HOST_SUFFIX or host.endswith("." + _ALLOWED_OFFICIAL_HOST_SUFFIX)


def _fact_reference_date(fact: Fact, program: CanonicalProgram) -> Optional[date]:
    """The date used to judge a fact's freshness: its primary source's
    last_verified, else that source's fetched_at date."""
    if fact.primary_source_ref is None:
        return None
    for src in program.sources:
        if src.source_id == fact.primary_source_ref:
            if src.last_verified is not None:
                return src.last_verified
            return src.fetched_at.date()
    return None


def _check_term_consistency(program: CanonicalProgram) -> list[ValidationFinding]:
    fact = program.application.terms
    if not isinstance(fact, Fact) or not isinstance(fact.value, list):
        return []
    audiences = {t.audience for t in fact.value}
    if Audience.INTERNATIONAL in audiences and not (
        Audience.DOMESTIC in audiences or Audience.ALL in audiences
    ):
        return [_warn("CP-W004", "application.terms",
                      "international application term has no domestic/all counterpart")]
    return []


def _has_no_deadlines(program: CanonicalProgram) -> bool:
    fact = program.application.terms
    if not isinstance(fact, Fact):
        return True
    if fact.data_status != DataStatus.AVAILABLE or not isinstance(fact.value, list):
        return True
    return all(t.deadline_kind == DeadlineKind.NOT_ACCEPTING or t.deadline is None
               for t in fact.value)
