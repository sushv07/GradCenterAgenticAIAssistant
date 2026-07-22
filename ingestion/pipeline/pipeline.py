"""
ingestion/pipeline/pipeline.py
The KnowledgePipeline — source-agnostic orchestration + IngestionSummary.

Flow (all stages behind ports; no infra here):

    KnowledgeDocument(s)
        → validate_document        (skip empty/broken docs)
        → Chunker.chunk            (deterministic chunks)
        → validate_chunks          (empty / oversized / missing url / duplicates)
        → VectorIndex.build|upsert  (Chroma today; swappable)
        → IngestionSummary

`build` mode fully recreates the collection (production's current behaviour).
`upsert` mode is idempotent (Phase 6): deterministic chunk IDs mean unchanged
chunks overwrite in place; `prune=True` also deletes chunks no longer present, so
new/updated/unchanged/removed documents are handled without a full rebuild.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from ingestion.pipeline.config import PipelineConfig
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.ports import Chunk, Chunker, VectorIndex
from ingestion.pipeline.validator import (
    ValidationIssue, error_ids, validate_chunks, validate_document,
)


@dataclass
class IngestionSummary:
    """Human- and machine-readable outcome of one ingestion run."""

    mode: str = "build"
    documents_processed: int = 0
    documents_indexed: int = 0
    documents_skipped: int = 0
    chunks_created: int = 0
    chunks_indexed: int = 0
    validation_failures: int = 0      # count of ERROR-severity issues
    validation_warnings: int = 0
    duplicates_detected: int = 0
    deleted_chunks: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join([
            f"Ingestion summary (mode={self.mode})",
            f"  Documents processed : {self.documents_processed}",
            f"  Documents indexed   : {self.documents_indexed}",
            f"  Documents skipped   : {self.documents_skipped}",
            f"  Chunks created      : {self.chunks_created}",
            f"  Chunks indexed      : {self.chunks_indexed}",
            f"  Validation failures : {self.validation_failures}",
            f"  Validation warnings : {self.validation_warnings}",
            f"  Duplicates detected : {self.duplicates_detected}",
            f"  Chunks deleted      : {self.deleted_chunks}",
        ])


class KnowledgePipeline:
    """Wires a Chunker + VectorIndex + config into one reusable write path."""

    def __init__(
        self,
        chunker: Chunker,
        indexer: VectorIndex,
        config: Optional[PipelineConfig] = None,
    ) -> None:
        self.chunker = chunker
        self.indexer = indexer
        self.config = config or PipelineConfig()

    def run(
        self,
        documents: Iterable[KnowledgeDocument],
        *,
        mode: str = "build",
        prune: bool = False,
    ) -> tuple[Any, IngestionSummary]:
        """Validate → chunk → validate → index. Returns (index_handle, summary)."""
        summary = IngestionSummary(mode=mode)
        all_chunks: list[Chunk] = []
        indexed_doc_ids: set[str] = set()

        for doc in documents:
            summary.documents_processed += 1
            doc_issues = validate_document(doc)
            summary.issues.extend(doc_issues)
            if any(i.is_error for i in doc_issues):
                summary.documents_skipped += 1
                continue
            chunks = self.chunker.chunk(doc)
            if not chunks:
                summary.documents_skipped += 1
                continue
            all_chunks.extend(chunks)
            indexed_doc_ids.add(doc.document_id)

        summary.chunks_created = len(all_chunks)

        chunk_issues = validate_chunks(all_chunks, self.config)
        summary.issues.extend(chunk_issues)
        summary.validation_failures = sum(1 for i in summary.issues if i.is_error)
        summary.validation_warnings = sum(1 for i in summary.issues if not i.is_error)
        summary.duplicates_detected = sum(
            1 for i in chunk_issues if i.code == "duplicate_chunk_id")

        bad_ids = error_ids(chunk_issues) if self.config.drop_invalid else set()
        valid_chunks = [c for c in all_chunks if c.chunk_id not in bad_ids]
        summary.chunks_indexed = len(valid_chunks)
        summary.documents_indexed = len({c.document_id for c in valid_chunks})

        handle: Any = None
        if mode == "upsert":
            if prune:
                current = {c.chunk_id for c in valid_chunks}
                stale = self.indexer.existing_ids() - current
                summary.deleted_chunks = self.indexer.delete(sorted(stale)) if stale else 0
            self.indexer.upsert(valid_chunks)
            handle = getattr(self.indexer, "handle", None)
        else:  # "build" — full (re)create, production's current behaviour
            handle = self.indexer.build(valid_chunks)

        return handle, summary
