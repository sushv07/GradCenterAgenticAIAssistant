"""
domain/programs/enums.py
Controlled vocabularies for the CanonicalProgram data foundation (Phase P1).

Every enum is a (str, Enum) so it serializes to its string value in JSON and
round-trips cleanly through Pydantic's model_dump(mode="json") /
model_validate.

DataStatus is the load-bearing one: it preserves the EXACT vocabulary already
used by the doctoral taxonomy's `_null_contract` (available, unknown,
source_missing, manual_required, not_applicable, manual_curated) and adds
exactly two additive extensions required by the master's expansion:
`stale` and `conflicting_sources`. No `known` or `manual_review_required`
alternates are introduced — that would fork the existing convention.
"""
from __future__ import annotations

from enum import Enum


class ProgramLevel(str, Enum):
    MASTERS = "masters"
    DOCTORAL = "doctoral"
    CERTIFICATE = "certificate"
    OTHER = "other"


class DataStatus(str, Enum):
    # ── existing doctoral-taxonomy vocabulary (do not rename) ──────────────
    AVAILABLE = "available"
    UNKNOWN = "unknown"
    SOURCE_MISSING = "source_missing"
    MANUAL_REQUIRED = "manual_required"
    NOT_APPLICABLE = "not_applicable"
    MANUAL_CURATED = "manual_curated"
    # ── additive extensions (freshness + source-conflict handling) ─────────
    STALE = "stale"
    CONFLICTING_SOURCES = "conflicting_sources"


class Volatility(str, Enum):
    STABLE = "stable"
    MODERATE = "moderate"
    TIME_SENSITIVE = "time_sensitive"


class DegreeType(str, Enum):
    MS = "MS"
    MA = "MA"
    MBA = "MBA"
    MFA = "MFA"
    MPH = "MPH"
    MSW = "MSW"
    MENG = "MEng"
    MPA = "MPA"
    MM = "MM"
    MSN = "MSN"
    OTHER = "Other"  # fallback; preserve the official value in degree_type_official


class DeliveryMode(str, Enum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    HYBRID = "hybrid"


class CompletenessTier(str, Enum):
    MINIMAL = "minimal"
    CORE = "core"
    ENRICHED = "enriched"


class ValidationStatus(str, Enum):
    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    INVALID = "invalid"
    UNVALIDATED = "unvalidated"


class ReviewStatus(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"
    FLAGGED = "flagged"


class LifecycleState(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class SourceType(str, Enum):
    PROGRAM_PAGE = "program_page"
    ADMISSIONS_PAGE = "admissions_page"
    CATALOG = "catalog"
    DEADLINE_TABLE = "deadline_table"
    PDF = "pdf"
    OTHER = "other"


class ExtractionMethod(str, Enum):
    HTML_PARSE = "html_parse"
    TABLE_PARSE = "table_parse"
    PDF_EXTRACT = "pdf_extract"
    MANUAL = "manual"


class Audience(str, Enum):
    DOMESTIC = "domestic"
    INTERNATIONAL = "international"
    ALL = "all"


class DeadlineKind(str, Enum):
    PRIORITY = "priority"
    FINAL = "final"
    ROLLING = "rolling"
    NOT_ACCEPTING = "not_accepting"


class PortalKind(str, Enum):
    CAL_STATE_APPLY = "cal_state_apply"
    PROGRAM = "program"
    EXTERNAL = "external"


class UpdateKind(str, Enum):
    CREATED = "created"
    SOURCE_REFRESH = "source_refresh"
    FIELD_CHANGE = "field_change"
    MANUAL_CORRECTION = "manual_correction"
    STALE_MARK = "stale_mark"
    LIFECYCLE_CHANGE = "lifecycle_change"


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATIONAL = "informational"
