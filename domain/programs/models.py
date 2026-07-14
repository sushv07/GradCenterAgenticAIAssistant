"""
domain/programs/models.py
The CanonicalProgram record and its nested models (Phase P1).

Validation boundary (see domain.programs.validation for the other half):
  - MODEL layer enforces only LOCAL invariants at construction — invalid Fact
    combinations (domain.programs.facts) and malformed Source URLs / ids /
    hashes (domain.programs.sources). Enum membership is enforced by Pydantic.
  - VALIDATOR layer owns everything cross-field and corpus-level: source-ref
    resolution, duplicate program ids, aliases, record-level URL checks,
    freshness policy, completeness/review findings. These rules live ONLY there.
  - The two layers do not overlap: no rule is enforced in both places.

Design rules:
  - Structural identity fields are PLAIN values (checked by the validator, which
    returns findings) so the validator stays the single reachable gate for
    record-level rules rather than raising mid-construction.
  - Evidence-bearing facts use Fact[T] (see domain.programs.facts), which
    self-validates its local invariants at construction.
  - The record contains NO Chroma structures and NO precomputed retrieval
    chunks — retrieval projection is a separate, later layer.
  - program_level supports masters | doctoral | certificate | other, but only
    master's records are authored in this phase. The existing doctoral taxonomy
    is NOT migrated.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from domain.programs.enums import (
    Audience,
    CompletenessTier,
    DeadlineKind,
    DegreeType,
    DeliveryMode,
    LifecycleState,
    PortalKind,
    ProgramLevel,
    ReviewStatus,
    UpdateKind,
    ValidationStatus,
)
from domain.programs.facts import Fact
from domain.programs.sources import Source

CURRENT_SCHEMA_VERSION = "masters-1.0"


# ---------------------------------------------------------------------------
# Small nested value objects
# ---------------------------------------------------------------------------

class Prerequisite(BaseModel):
    description: str
    required: bool
    equivalent_allowed: Optional[bool] = None


class TestRequirement(BaseModel):
    test: str
    required: bool
    waiver_conditions: Optional[str] = None


class RecommendationLetterRequirement(BaseModel):
    count: Optional[int] = None
    from_whom: Optional[str] = None


class Portal(BaseModel):
    name: str
    kind: PortalKind
    url: Optional[str] = None


class Contact(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    office: Optional[str] = None
    source_ref: Optional[str] = None

    def has_meaningful_value(self) -> bool:
        """True if at least one of name/email/phone/office is populated."""
        return any(v not in (None, "") for v in (self.name, self.email, self.phone, self.office))


class ApplicationTerm(BaseModel):
    term: str
    audience: Audience
    deadline_kind: DeadlineKind
    # Structured full date — populated ONLY when a correct calendar year is known
    # (e.g. verified/curated). The ingestion pipeline leaves this None because the
    # index publishes "Month Day" without a year, and the year cannot be inferred
    # correctly for every admission cycle.
    deadline: Optional[date] = None
    # As-published application deadline text (e.g. "November 01") preserved
    # verbatim — the honest representation when no year can be guaranteed.
    deadline_text: Optional[str] = None
    # Accept/decline is a distinct published deadline — kept separate from the
    # application deadline per the deadline-interpretation rules, never merged.
    accept_decline_deadline: Optional[date] = None
    accept_decline_deadline_text: Optional[str] = None
    notes: Optional[str] = None


class RevisionEvent(BaseModel):
    at: datetime
    kind: UpdateKind
    fields_changed: list[str] = Field(default_factory=list)
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level record sections
# ---------------------------------------------------------------------------

class Identity(BaseModel):
    program_id: str                      # required structural key
    canonical_name: str                  # required structural key
    aliases: list[str] = Field(default_factory=list)
    degree_type: DegreeType
    # Preserves the official degree label verbatim; None only when no label was
    # published (never a placeholder string).
    degree_type_official: Optional[str] = None
    official_program_url: str            # required structural key
    # college/department are provenance-sensitive (sourced from a program or
    # catalog page), so they use the Fact envelope: unknown = not yet consulted,
    # source_missing = consulted but absent, available = source-backed value.
    college: Fact[str]
    department: Fact[str]
    # officially-stated optional identity (absence = None; structural, not a Fact)
    delivery_mode: Optional[DeliveryMode] = None
    campus_location: Optional[str] = None


class Overview(BaseModel):
    official_summary: Fact[str]
    program_description: Optional[Fact[str]] = None
    focus_areas: Optional[Fact[list[str]]] = None
    # STEM (F-1 OPT) designation as published on the Graduate Studies index.
    stem_designated: Optional[Fact[bool]] = None


class Admissions(BaseModel):
    admission_requirements: Optional[Fact[list[str]]] = None
    prerequisites: Optional[Fact[list[Prerequisite]]] = None
    minimum_gpa: Optional[Fact[float]] = None
    tests: Optional[Fact[list[TestRequirement]]] = None
    work_experience: Optional[Fact[str]] = None
    supplemental_materials: Optional[Fact[list[str]]] = None
    recommendation_letters: Optional[Fact[RecommendationLetterRequirement]] = None
    statement_requirements: Optional[Fact[str]] = None
    portfolio_or_audition: Optional[Fact[str]] = None
    intl_distinctions: Optional[Fact[list[str]]] = None


class Application(BaseModel):
    terms: Optional[Fact[list[ApplicationTerm]]] = None
    application_portal: Optional[Fact[Portal]] = None
    application_instructions: Optional[Fact[str]] = None
    rolling_admission: Optional[Fact[bool]] = None


class ContactSection(BaseModel):
    department_contact: Optional[Fact[Contact]] = None
    coordinator_or_advisor: Optional[Fact[Contact]] = None


class QualityMetadata(BaseModel):
    record_completeness: CompletenessTier
    validation_status: ValidationStatus
    manual_review_status: ReviewStatus
    lifecycle_state: LifecycleState
    last_verified: Optional[date] = None
    revision_history: list[RevisionEvent] = Field(default_factory=list)


class Enrichment(BaseModel):
    concentrations: Optional[Fact[list[str]]] = None
    interest_tags: Optional[Fact[list[str]]] = None
    academic_background_tags: Optional[Fact[list[str]]] = None
    career_goal_tags: Optional[Fact[list[str]]] = None
    career_outcomes: Optional[Fact[list[str]]] = None
    advisor: Optional[Fact[Contact]] = None


class CanonicalProgram(BaseModel):
    """One canonical program record — engine-agnostic source of truth."""

    schema_version: str
    record_id: str
    program_level: ProgramLevel
    identity: Identity
    overview: Overview
    admissions: Admissions = Field(default_factory=Admissions)
    application: Application = Field(default_factory=Application)
    contact: ContactSection = Field(default_factory=ContactSection)
    sources: list[Source] = Field(default_factory=list)
    quality: QualityMetadata
    enrichment: Optional[Enrichment] = None
