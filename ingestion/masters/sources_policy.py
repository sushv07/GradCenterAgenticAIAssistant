"""
ingestion/masters/sources_policy.py
The official-source priority policy (data acquisition ordering only).

Traversal is FIELD-DRIVEN, not crawler-driven: start at the Graduate Studies
index, then consult lower-priority official sources ONLY while required canonical
fields remain unresolved. This module encodes the ordering and which fields each
source tier is authoritative for; it performs no fetching itself.
"""
from __future__ import annotations

from enum import Enum

from domain.programs.enums import SourceType

# The authoritative master's discovery index.
GRADUATE_STUDIES_MASTERS_INDEX_URL = (
    "https://www.csulb.edu/graduate-studies-csulb/article/"
    "programs-advisors-and-deadlines-masters"
)


class SourceTier(int, Enum):
    GRAD_STUDIES_INDEX = 1
    DEPARTMENT_PROGRAM_PAGE = 2
    UNIVERSITY_CATALOG = 3
    GRAD_STUDIES_ENROLLMENT = 4
    INTERNATIONAL_EDUCATION = 5
    CPACE = 6
    OFFICIAL_PDF = 7


# Ordered priority for field-driven traversal.
SOURCE_PRIORITY: tuple[SourceTier, ...] = (
    SourceTier.GRAD_STUDIES_INDEX,
    SourceTier.DEPARTMENT_PROGRAM_PAGE,
    SourceTier.UNIVERSITY_CATALOG,
    SourceTier.GRAD_STUDIES_ENROLLMENT,
    SourceTier.INTERNATIONAL_EDUCATION,
    SourceTier.CPACE,
    SourceTier.OFFICIAL_PDF,
)

# Which SourceType each tier maps to when building provenance.
TIER_SOURCE_TYPE: dict[SourceTier, SourceType] = {
    SourceTier.GRAD_STUDIES_INDEX: SourceType.DEADLINE_TABLE,
    SourceTier.DEPARTMENT_PROGRAM_PAGE: SourceType.PROGRAM_PAGE,
    SourceTier.UNIVERSITY_CATALOG: SourceType.CATALOG,
    SourceTier.GRAD_STUDIES_ENROLLMENT: SourceType.ADMISSIONS_PAGE,
    SourceTier.INTERNATIONAL_EDUCATION: SourceType.ADMISSIONS_PAGE,
    SourceTier.CPACE: SourceType.PROGRAM_PAGE,
    SourceTier.OFFICIAL_PDF: SourceType.PDF,
}

# Sources never permitted, for documentation and guard tests.
FORBIDDEN_SOURCE_MARKERS: tuple[str, ...] = (
    "wikipedia.org", "reddit.com", "webcache.googleusercontent.com",
    "google.com/search", "usnews.com", "niche.com",
)
