"""
ingestion/masters/manifest.py
Stage 1 output models — the Discovery Manifest.

A DiscoveryManifest is NOT a CanonicalProgram. Its sole responsibility is to
record the master's inventory discovered from the Graduate Studies index, with
raw-but-structured fields and discovery-time warnings. Enrichment (Stage 2)
consumes it; discovery never performs normalization.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DiscoveredProgram(BaseModel):
    raw_listing_name: str
    normalized_program_name: str
    degree_label: Optional[str] = None
    official_program_url: Optional[str] = None
    advisor_office: Optional[str] = None
    advisor_url: Optional[str] = None
    advisor_email: Optional[str] = None
    phone: Optional[str] = None
    spring_application_deadline: Optional[str] = None
    spring_accept_decline_deadline: Optional[str] = None
    fall_application_deadline: Optional[str] = None
    fall_accept_decline_deadline: Optional[str] = None
    term_availability: list[str] = Field(default_factory=list)  # e.g. ["fall"]
    stem_designated: Optional[bool] = None
    warnings: list[str] = Field(default_factory=list)


class DiscoveryManifest(BaseModel):
    discovery_source_url: str
    discovery_source_hash: str
    discovered_at: datetime
    programs: list[DiscoveredProgram] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
