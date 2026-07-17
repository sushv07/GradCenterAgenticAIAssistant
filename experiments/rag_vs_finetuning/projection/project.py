"""
experiments/rag_vs_finetuning/projection/project.py
Deterministic CanonicalProgram -> list[RetrievalDocument] projection (Phase P5).

Template-based transformation only — no LLM, no timestamps, no network. Sections
(overview / admissions / application / contact) are projected only from AVAILABLE
facts; unknown / source_missing / manual_required / conflicting_sources facts are
omitted (conflicting emits a warning); stale facts are included with a caveat.
Published deadline text is preserved exactly; no ISO date is invented.

Imports only the standard library, Pydantic, and domain.programs — no ingestion,
LangChain, Chroma, embeddings, vector store, or production-RAG code.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterator, Optional

from domain.programs.enums import DataStatus, Volatility
from domain.programs.facts import Fact
from domain.programs.models import CanonicalProgram, Contact
from experiments.rag_vs_finetuning.projection.models import (
    RetrievalDocument, SourceReference,
)

_STALE_CAVEAT = " (as of last verification; may be outdated)"


@dataclass
class ProjectionResult:
    documents: list[RetrievalDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    omitted_unknown: int = 0
    omitted_source_missing: int = 0


def _usable(fact: Optional[Fact]) -> tuple[bool, str, Optional[str]]:
    """(usable, caveat, warning) for a fact under the missing-value policy."""
    if fact is None:
        return False, "", None
    st = fact.data_status
    if st == DataStatus.AVAILABLE:
        return True, "", None
    if st == DataStatus.STALE:
        return True, _STALE_CAVEAT, None
    if st == DataStatus.CONFLICTING_SOURCES:
        return False, "", "conflicting_sources"
    return False, "", None  # unknown / source_missing / manual_required / not_applicable


def _src_refs(program: CanonicalProgram, refs: list[str]) -> list[SourceReference]:
    by_id = {s.source_id: s for s in program.sources}
    out: list[SourceReference] = []
    seen: set[str] = set()
    for rid in sorted(set(refs)):
        s = by_id.get(rid)
        if s and rid not in seen:
            out.append(SourceReference(source_id=s.source_id, source_url=s.source_url,
                                       content_hash=s.content_hash))
            seen.add(rid)
    return out


def _freshness(facts: list[Fact]) -> str:
    return "stale" if any(f.data_status == DataStatus.STALE for f in facts) else "fresh"


def _doc(program: CanonicalProgram, *, section: str, title: str, content: str,
         facts: list[Fact], volatility: str, record_hash: str,
         projection_version: str) -> RetrievalDocument:
    refs: list[str] = []
    for f in facts:
        refs.extend(f.all_source_refs())
    freshness = _freshness(facts)
    return RetrievalDocument(
        document_id=f"{program.identity.program_id}::{section}",
        program_id=program.identity.program_id,
        program_level=program.program_level.value,
        title=title, section=section, content=content,
        source_references=_src_refs(program, refs),
        volatility=volatility, freshness_status=freshness,
        metadata={
            "program_id": program.identity.program_id,
            "canonical_name": program.identity.canonical_name,
            "degree_type": program.identity.degree_type.value,
            "program_level": program.program_level.value,
            "section": section,
            "page_type": "masters_program",
            "review_status": "freeze_approved",
            "validation_status": program.quality.validation_status.value,
            "source_count": len(program.sources),
            "freshness_status": freshness,
        },
        canonical_record_hash=record_hash,
        projection_version=projection_version,
    )


def project_program(program: CanonicalProgram, *, record_hash: str,
                    projection_version: str) -> ProjectionResult:
    result = ProjectionResult()
    ident = program.identity

    # count omissions (for the report)
    for _p, fact in _iter_facts(program):
        if fact.data_status == DataStatus.UNKNOWN:
            result.omitted_unknown += 1
        elif fact.data_status == DataStatus.SOURCE_MISSING:
            result.omitted_source_missing += 1
        elif fact.data_status == DataStatus.CONFLICTING_SOURCES:
            result.warnings.append(f"{program.identity.program_id}: conflicting_sources fact omitted")

    # ── overview ─────────────────────────────────────────────────────────
    ov = program.overview.official_summary
    ov_ok, ov_caveat, _ = _usable(ov)
    if ov_ok and ov.value:
        degree = ident.degree_type_official or ident.degree_type.value
        parts = [f"{ident.canonical_name} ({degree}).", ov.value + ov_caveat]
        facts = [ov]
        stem = program.overview.stem_designated
        stem_ok, _, _ = _usable(stem)
        if stem_ok and stem.value is not None:
            parts.append("STEM-designated program." if stem.value else "Not STEM-designated.")
            facts.append(stem)
        result.documents.append(_doc(
            program, section="overview", title=ident.canonical_name,
            content=" ".join(parts), facts=facts, volatility=Volatility.STABLE.value,
            record_hash=record_hash, projection_version=projection_version))

    # ── admissions ───────────────────────────────────────────────────────
    adm_lines: list[str] = []
    adm_facts: list[Fact] = []
    gpa = program.admissions.minimum_gpa
    ok, cav, _ = _usable(gpa)
    if ok and gpa.value is not None:
        adm_lines.append(f"Minimum GPA: {gpa.value}{cav}."); adm_facts.append(gpa)
    tests = program.admissions.tests
    ok, cav, _ = _usable(tests)
    if ok and tests.value:
        for t in tests.value:
            req = "required" if t.required else "not required"
            line = f"{t.test}: {req}"
            if t.waiver_conditions:
                line += f" ({t.waiver_conditions})"
            adm_lines.append(line + cav + ".");
        adm_facts.append(tests)
    for label, fact in (("Prerequisites", program.admissions.prerequisites),
                        ("Supplemental materials", program.admissions.supplemental_materials),
                        ("International applicants", program.admissions.intl_distinctions)):
        ok, cav, _ = _usable(fact)
        if ok and fact.value:
            items = fact.value if isinstance(fact.value, list) else [fact.value]
            rendered = "; ".join(str(getattr(i, "description", i)) for i in items)
            adm_lines.append(f"{label}: {rendered}{cav}."); adm_facts.append(fact)
    if adm_lines:
        result.documents.append(_doc(
            program, section="admissions", title=f"{ident.canonical_name} — Admissions",
            content=" ".join(adm_lines), facts=adm_facts, volatility=Volatility.MODERATE.value,
            record_hash=record_hash, projection_version=projection_version))

    # ── application ──────────────────────────────────────────────────────
    terms = program.application.terms
    ok, cav, _ = _usable(terms)
    app_lines: list[str] = []
    app_facts: list[Fact] = []
    if ok and terms.value:
        app_facts.append(terms)
        for t in terms.value:
            season = t.term.capitalize()
            if t.deadline_kind.value == "not_accepting":
                app_lines.append(f"{season}: Not Accepting.")
                continue
            # prefer published text; fall back to a verified structured date if present
            dl = t.deadline_text or (t.deadline.isoformat() if t.deadline else None)
            if dl is None:
                continue
            line = f"{season} application deadline: {dl}"
            ad = t.accept_decline_deadline_text or (
                t.accept_decline_deadline.isoformat() if t.accept_decline_deadline else None)
            if ad:
                line += f"; accept/decline deadline: {ad}"
            app_lines.append(line + cav + ".")
    portal = program.application.application_portal
    ok, cav, _ = _usable(portal)
    if ok and portal.value:
        app_lines.append(f"Application portal: {portal.value.name}{cav}.")
        app_facts.append(portal)
    instr = program.application.application_instructions
    ok, cav, _ = _usable(instr)
    if ok and instr.value:
        app_lines.append(f"Instructions: {instr.value}{cav}.")
        app_facts.append(instr)
    if app_lines:
        result.documents.append(_doc(
            program, section="application", title=f"{ident.canonical_name} — Application",
            content=" ".join(app_lines), facts=app_facts,
            volatility=Volatility.TIME_SENSITIVE.value,
            record_hash=record_hash, projection_version=projection_version))

    # ── contact ──────────────────────────────────────────────────────────
    for fact in (program.contact.department_contact, program.contact.coordinator_or_advisor):
        ok, cav, _ = _usable(fact)
        if ok and isinstance(fact.value, Contact) and fact.value.has_meaningful_value():
            c = fact.value
            bits = []
            if c.name: bits.append(f"Program office/advisor: {c.name}")
            if c.email: bits.append(f"Email: {c.email}")
            if c.phone: bits.append(f"Phone: {c.phone}")
            if c.office: bits.append(f"Office: {c.office}")
            result.documents.append(_doc(
                program, section="contact", title=f"{ident.canonical_name} — Contact",
                content=". ".join(bits) + cav + ".", facts=[fact],
                volatility=Volatility.MODERATE.value,
                record_hash=record_hash, projection_version=projection_version))
            break  # one contact document per program

    result.documents.sort(key=lambda d: d.document_id)
    return result


def _iter_facts(program: CanonicalProgram) -> Iterator[tuple[str, Fact]]:
    sections = {"identity": program.identity, "overview": program.overview,
                "admissions": program.admissions, "application": program.application,
                "contact": program.contact}
    if program.enrichment is not None:
        sections["enrichment"] = program.enrichment
    for name, section in sections.items():
        for fname, value in section.__dict__.items():
            if isinstance(value, Fact):
                yield f"{name}.{fname}", value


def projection_checksum(documents: list[RetrievalDocument]) -> str:
    payload = "\n".join(
        json.dumps(d.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for d in sorted(documents, key=lambda d: d.document_id)
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
