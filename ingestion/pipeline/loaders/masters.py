"""
ingestion/pipeline/loaders/masters.py
Adapter: an extracted master's page record → KnowledgeDocument.

Pure (stdlib + pipeline models only) — the source-agnostic pipeline stays
unchanged; this is just another loader (sibling of pages.py). It maps an
already-extracted page record (title + cleaned text + discovery/classification
metadata) into a KnowledgeDocument using the production ChunkMetadata schema,
plus the legacy-compatible keys the retriever already reads (`url`, `page_type`,
`program_name`, `content_category`, `workflow_priority`, `parent_program_url`).

Fetching, HTML parsing, and classification happen upstream (in rag/, which owns
the crawler); this loader performs no I/O and never fabricates values — unknown
fields are simply omitted.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.ids import document_id_from_url

# A shared department page belongs to several programs; ChromaDB metadata is flat
# (no lists), so program_name is set only for single-program pages and the full
# set is preserved as a comma-joined string under `associated_programs`.
_ASSOCIATED_SEP = ", "


def masters_page_to_document(record: dict[str, Any]) -> KnowledgeDocument:
    """Map one extracted master's page record to a KnowledgeDocument."""
    url = record["source_url"]
    document_id = document_id_from_url(url)
    associated = list(record.get("associated_programs", []) or [])
    program_name = record.get("program_name", "")
    # Single-program page → tag it; shared page → generic (program_name empty).
    if not program_name and len(associated) == 1:
        program_name = associated[0]

    metadata: dict[str, Any] = {
        # legacy-compatible keys (retriever reads these)
        "title": record.get("title", ""),
        "url": url,
        "page_type": "masters_program",
        "program_name": program_name,
        "content_category": record.get("content_type", ""),
        "workflow_priority": record.get("workflow_priority", 6),
        "parent_program_url": record.get("parent_program_url", ""),
        # production ChunkMetadata schema (Phase 5)
        "degree_level": record.get("degree_level", "Masters"),
        "degree": record.get("degree", ""),
        "department": record.get("department", ""),
        "college": record.get("college", ""),
        "content_type": record.get("content_type", ""),
        "source_url": url,
        "document_id": document_id,
        "canonical_document_id": document_id,
        "page_title": record.get("title", ""),
        "crawl_depth": record.get("crawl_depth", 0),
        "associated_programs": _ASSOCIATED_SEP.join(associated),
    }
    # Keep metadata lean and honest: drop empty optional values (primitives only).
    metadata = {k: v for k, v in metadata.items() if v not in ("", None)}

    return KnowledgeDocument(
        text=record.get("text", ""),
        source_url=url,
        content_type=record.get("content_type", ""),
        document_id=document_id,
        metadata=metadata,
    )


class MastersPageLoader:
    """KnowledgeLoader over already-extracted master's page records."""

    def __init__(self, records: Sequence[dict[str, Any]]) -> None:
        self._records = records

    def load(self) -> Iterable[KnowledgeDocument]:
        for record in self._records:
            yield masters_page_to_document(record)
