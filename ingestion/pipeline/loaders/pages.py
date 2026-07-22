"""
ingestion/pipeline/loaders/pages.py
Adapter: production "page dicts" → KnowledgeDocument.

This is the loader for the CURRENT production source — the page dicts produced by
`rag.ingestion.ingest_pages()`. It maps each page's fields into KnowledgeDocument
metadata using the EXACT legacy keys (`title, url, page_type, program_name,
content_category, discovered_from, parent_program_url, workflow_priority,
links_json`), so that after chunking the stored metadata is byte-identical to
what `rag/chunking.py` has always produced. Backward compatibility by construction.

Future sources provide their own loaders (richer metadata via
`ingestion.pipeline.metadata.ChunkMetadata`); the pipeline itself is unchanged.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from ingestion.pipeline.documents import KnowledgeDocument


def page_to_document(page: dict[str, Any]) -> KnowledgeDocument:
    """Map one production page dict to a KnowledgeDocument (legacy-key parity)."""
    url = page.get("url", "")
    # links are serialised to a JSON string here — ChromaDB metadata is flat, and
    # this matches rag/chunking.py exactly (same value on every chunk of a page).
    links_json = json.dumps(page.get("links", []), ensure_ascii=False)
    metadata: dict[str, Any] = {
        "title":              page.get("title", ""),
        "url":                url,
        "page_type":          page.get("page_type", "unknown"),
        "program_name":       page.get("program_name", ""),
        "content_category":   page.get("content_category", ""),
        "discovered_from":    page.get("discovered_from", ""),
        "parent_program_url": page.get("parent_program_url", ""),
        "workflow_priority":  page.get("workflow_priority", 6),
        "links_json":         links_json,
    }
    return KnowledgeDocument(
        text=page.get("text", ""),
        source_url=url,
        content_type=page.get("page_type", "unknown"),
        metadata=metadata,
    )


class PageDictLoader:
    """KnowledgeLoader over an in-memory list of production page dicts."""

    def __init__(self, pages: Sequence[dict[str, Any]]) -> None:
        self._pages = pages

    def load(self) -> Iterable[KnowledgeDocument]:
        for page in self._pages:
            yield page_to_document(page)
