"""
domain/programs/
Canonical program data foundation (Phase P1).

A production-side, engine-agnostic model layer for program records
(masters | doctoral | certificate | other). It is isolated from routing,
orchestration, recommendation, prompts, the RAG pipeline, the existing
doctoral taxonomy, and the frontend — nothing in app.py imports this package.

Only master's records are authored in this phase; the doctoral taxonomy is
not migrated. No fetching, crawling, retrieval projection, or Chroma
integration lives here.
"""
from __future__ import annotations

from domain.programs.enums import (
    Audience,
    CompletenessTier,
    DataStatus,
    DeadlineKind,
    DegreeType,
    DeliveryMode,
    ExtractionMethod,
    LifecycleState,
    PortalKind,
    ProgramLevel,
    ReviewStatus,
    SourceType,
    UpdateKind,
    ValidationSeverity,
    ValidationStatus,
    Volatility,
)
from domain.programs.facts import Fact
from domain.programs.models import (
    CURRENT_SCHEMA_VERSION,
    Admissions,
    Application,
    ApplicationTerm,
    CanonicalProgram,
    Contact,
    ContactSection,
    Enrichment,
    Identity,
    Overview,
    Portal,
    Prerequisite,
    QualityMetadata,
    RecommendationLetterRequirement,
    RevisionEvent,
    TestRequirement,
)
from domain.programs.sources import Source
from domain.programs.validation import (
    ValidationFinding,
    validate_corpus,
    validate_program,
)

__all__ = [
    "Audience", "CompletenessTier", "DataStatus", "DeadlineKind", "DegreeType",
    "DeliveryMode", "ExtractionMethod", "LifecycleState", "PortalKind",
    "ProgramLevel", "ReviewStatus", "SourceType", "UpdateKind",
    "ValidationSeverity", "ValidationStatus", "Volatility",
    "Fact", "Source",
    "CURRENT_SCHEMA_VERSION", "CanonicalProgram", "Identity", "Overview",
    "Admissions", "Application", "ApplicationTerm", "Contact", "ContactSection",
    "Enrichment", "Portal", "Prerequisite", "QualityMetadata",
    "RecommendationLetterRequirement", "RevisionEvent", "TestRequirement",
    "ValidationFinding", "validate_program", "validate_corpus",
]
