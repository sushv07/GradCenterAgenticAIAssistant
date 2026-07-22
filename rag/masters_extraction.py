"""
rag/masters_extraction.py
Master's content extraction → KnowledgeDocument conversion (Phase 3).

Composes existing pieces; introduces no new extraction or pipeline logic:

  DiscoveredPage (rag.masters_discovery)
      → fetch HTML (rag.ingestion.fetch_page, injectable for tests)
      → extract (ingestion.masters.extraction.extract_main_content_text — REUSED)
      → build record → KnowledgeDocument (ingestion.pipeline.loaders.masters — REUSED)
      → validate (ingestion.pipeline.validator.validate_document — REUSED)

Lives in rag/ because it consumes the crawler's output (rag.masters_discovery) and
fetches pages; `ingestion/` stays infra-free. Deterministic given a fixed fetch_fn.
Stops at validated KnowledgeDocuments — no chunking, embedding, or indexing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from ingestion.masters.extraction import extract_main_content_text
from ingestion.masters.manifest import DiscoveredProgram
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.loaders.masters import masters_page_to_document
from ingestion.pipeline.validator import ValidationIssue, validate_document
from rag.masters_discovery import DiscoveredPage


def _label(p: DiscoveredProgram) -> str:
    return f"{p.normalized_program_name} ({p.degree_label})" if p.degree_label \
        else p.normalized_program_name


@dataclass
class ConversionSummary:
    total_pages: int = 0
    documents_accepted: int = 0
    documents_rejected: int = 0
    empty_pages: int = 0
    duplicate_document_ids: int = 0
    avg_content_length: float = 0.0
    missing_metadata: dict[str, int] = field(default_factory=dict)
    rejections: list[tuple[str, str]] = field(default_factory=list)   # (url, reason)

    def render(self) -> str:
        L = ["# Master's KnowledgeDocument Conversion — Pilot Summary", "",
             f"- pages processed: {self.total_pages}",
             f"- documents accepted: {self.documents_accepted}",
             f"- documents rejected: {self.documents_rejected}",
             f"- empty pages: {self.empty_pages}",
             f"- duplicate document IDs: {self.duplicate_document_ids}",
             f"- average content length (accepted): {self.avg_content_length} chars", "",
             "## Missing optional metadata (accepted docs)", ""]
        for k, v in sorted(self.missing_metadata.items()):
            L.append(f"- {k}: {v}")
        if self.rejections:
            L += ["", "## Rejections", ""]
            L += [f"- {url}: {reason}" for url, reason in self.rejections]
        return "\n".join(L) + "\n"


def _record_for_page(page: DiscoveredPage, label_index: dict[str, DiscoveredProgram],
                     title: str, text: str) -> dict[str, Any]:
    program_name = degree = ""
    if len(page.programs) == 1:
        prog = label_index.get(page.programs[0])
        if prog is not None:
            program_name = prog.normalized_program_name
            degree = prog.degree_label or ""
    return {
        "source_url": page.url,
        "title": title or page.title,
        "text": text,
        "program_name": program_name,
        "degree": degree,
        "degree_level": "Masters",
        "department": "",              # deferred extraction (never fabricated)
        "college": "",
        "content_type": page.content_category,
        "workflow_priority": page.workflow_priority,
        "parent_program_url": page.parent_program_url,
        "crawl_depth": page.depth,
        "associated_programs": list(page.programs),
    }


def build_masters_documents(
    pages: Sequence[DiscoveredPage],
    programs: Sequence[DiscoveredProgram],
    *,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[list[KnowledgeDocument], ConversionSummary]:
    """Extract + convert discovered pages into validated KnowledgeDocuments."""
    if fetch_fn is None:
        from rag.ingestion import fetch_page
        fetch_fn = fetch_page

    label_index = {_label(p): p for p in programs}
    summary = ConversionSummary(total_pages=len(pages))
    accepted: list[KnowledgeDocument] = []
    seen_ids: set[str] = set()
    optional_fields = ("program_name", "degree", "department", "college")
    missing = {f: 0 for f in optional_fields}
    lengths: list[int] = []

    for page in pages:
        html = fetch_fn(page.url)
        if not html:
            summary.documents_rejected += 1
            summary.rejections.append((page.url, "fetch_failed"))
            continue

        title, text = extract_main_content_text(html, fallback_title=page.title)
        record = _record_for_page(page, label_index, title, text)
        doc = masters_page_to_document(record)

        issues = validate_document(doc)
        errors = [i for i in issues if i.is_error]
        if not text.strip():
            summary.empty_pages += 1
        if errors:
            summary.documents_rejected += 1
            summary.rejections.append((page.url, "; ".join(i.code for i in errors)))
            continue

        if doc.document_id in seen_ids:
            summary.duplicate_document_ids += 1
        seen_ids.add(doc.document_id)

        for f in optional_fields:
            if not doc.metadata.get(f):
                missing[f] += 1
        lengths.append(len(doc.text))
        accepted.append(doc)

    summary.documents_accepted = len(accepted)
    summary.avg_content_length = round(sum(lengths) / len(lengths), 1) if lengths else 0.0
    summary.missing_metadata = missing
    return accepted, summary
