"""
domain/programs/facts.py
The evidence-bearing field wrapper for the CanonicalProgram model (Phase P1).

Two-tier envelope rule (documented, fixed):
    PLAIN values  — structural identity that is validated + sourced at the
                    record level (program_id, canonical_name, aliases,
                    degree_type, degree_type_official, college, department,
                    official_program_url, delivery_mode, campus_location).
    Fact[T]       — every fact that needs status, provenance, volatility,
                    preserved official wording, freshness, or curator notes
                    (overview prose, admissions, application, contact,
                    enrichment tags).

Fact enforces its consistency rules at CONSTRUCTION time (Pydantic
model_validator). It deliberately does NOT resolve source_ref ids against a
program's sources[] — that is cross-record resolution and belongs to
domain.programs.validation at the CanonicalProgram level.
"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

from domain.programs.enums import DataStatus, Volatility

T = TypeVar("T")

# Statuses that require BOTH a retained non-null value and a primary source.
_REQUIRE_VALUE_AND_PRIMARY = {DataStatus.AVAILABLE, DataStatus.STALE}
# Statuses that forbid any source reference at all.
_FORBID_SOURCES = {DataStatus.UNKNOWN, DataStatus.NOT_APPLICABLE}


def _is_blank(text: object) -> bool:
    """True for a string that is empty or whitespace-only."""
    return isinstance(text, str) and text.strip() == ""


class Fact(BaseModel, Generic[T]):
    """One evidence-bearing fact plus its provenance and lifecycle status."""

    value: Optional[T] = None
    data_status: DataStatus
    volatility: Volatility
    primary_source_ref: Optional[str] = None
    supporting_source_refs: list[str] = Field(default_factory=list)
    official_text: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "Fact[T]":
        # ── empty-string substitutes are never allowed ────────────────────
        for name in ("primary_source_ref", "official_text", "notes"):
            if _is_blank(getattr(self, name)):
                raise ValueError(
                    f"{name} must not be an empty/whitespace string; use null"
                )
        if _is_blank(self.value):
            raise ValueError(
                "value must not be an empty string; use null with a data_status"
            )
        for ref in self.supporting_source_refs:
            if not isinstance(ref, str) or _is_blank(ref):
                raise ValueError("supporting_source_refs must not contain empty strings")

        # ── empty list is only a meaningful (confirmed) value ─────────────
        if isinstance(self.value, list) and len(self.value) == 0:
            if self.data_status != DataStatus.AVAILABLE:
                raise ValueError(
                    "an empty list is only valid with data_status=available; "
                    "an unknown/missing list fact must use value=null, not []"
                )

        # ── no duplicate source references ────────────────────────────────
        if (
            self.primary_source_ref is not None
            and self.primary_source_ref in self.supporting_source_refs
        ):
            raise ValueError(
                "primary_source_ref must not also appear in supporting_source_refs"
            )
        if len(set(self.supporting_source_refs)) != len(self.supporting_source_refs):
            raise ValueError("supporting_source_refs must not contain duplicates")

        # ── per-status invariants ─────────────────────────────────────────
        st = self.data_status
        if st in _REQUIRE_VALUE_AND_PRIMARY:
            if self.value is None:
                raise ValueError(f"data_status={st.value} requires a non-null value")
            if self.primary_source_ref is None:
                raise ValueError(f"data_status={st.value} requires a primary_source_ref")
        if st in _FORBID_SOURCES:
            if self.primary_source_ref is not None or self.supporting_source_refs:
                raise ValueError(f"data_status={st.value} forbids source references")
        if st == DataStatus.MANUAL_CURATED and self.notes is None:
            raise ValueError("data_status=manual_curated requires notes")
        if st == DataStatus.CONFLICTING_SOURCES:
            total_refs = (1 if self.primary_source_ref else 0) + len(
                self.supporting_source_refs
            )
            if self.value is not None:
                raise ValueError("data_status=conflicting_sources requires value=null")
            if total_refs < 2:
                raise ValueError(
                    "data_status=conflicting_sources requires at least two source references"
                )
            if self.notes is None:
                raise ValueError(
                    "data_status=conflicting_sources requires explanatory notes"
                )
        return self

    def all_source_refs(self) -> list[str]:
        """Primary (if any) followed by supporting references, in order."""
        refs: list[str] = []
        if self.primary_source_ref is not None:
            refs.append(self.primary_source_ref)
        refs.extend(self.supporting_source_refs)
        return refs
