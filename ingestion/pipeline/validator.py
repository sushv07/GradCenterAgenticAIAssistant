"""
ingestion/pipeline/validator.py
Pre-index validation (Phase 7).

Validation runs BEFORE anything is embedded or written, so bad records never
reach the vector store. It is pure and deterministic: given chunks + config it
returns a list of `ValidationIssue`s. The pipeline decides what to do with them
(drop errors when `config.drop_invalid`, always surface them in the summary).

Rules are intentionally conservative so they do not reject the legacy production
schema: a chunk is valid if it has non-empty text, a `chunk_id`, a URL under any
`url_metadata_keys` entry, is not oversized, and is not a duplicate `chunk_id`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ingestion.pipeline.config import PipelineConfig
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.ports import Chunk

# Issue severities.
ERROR = "error"       # record is unindexable; dropped when config.drop_invalid
WARNING = "warning"   # reported only; does not block indexing


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    target_id: str        # document_id or chunk_id the issue is about
    detail: str

    @property
    def is_error(self) -> bool:
        return self.severity == ERROR


def validate_document(doc: KnowledgeDocument) -> list[ValidationIssue]:
    """Document-level checks (run before chunking)."""
    issues: list[ValidationIssue] = []
    if doc.is_empty:
        issues.append(ValidationIssue(
            "empty_document", ERROR, doc.document_id, f"empty text: {doc.source_url}"))
    if not doc.source_url or not str(doc.source_url).strip():
        issues.append(ValidationIssue(
            "missing_source_url", WARNING, doc.document_id, "document has no source_url"))
    elif not str(doc.source_url).lower().startswith(("http://", "https://", "file://")):
        issues.append(ValidationIssue(
            "suspicious_source_url", WARNING, doc.document_id,
            f"source_url has no http(s)/file scheme: {doc.source_url}"))
    return issues


def _has_url(chunk: Chunk, url_keys: Sequence[str]) -> bool:
    return any(str(chunk.metadata.get(k, "")).strip() for k in url_keys)


def validate_chunks(
    chunks: Sequence[Chunk], config: PipelineConfig
) -> list[ValidationIssue]:
    """Chunk-level + batch-level checks (run before indexing)."""
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        cid = chunk.chunk_id or "<no-id>"

        if not chunk.text or not chunk.text.strip():
            issues.append(ValidationIssue("empty_chunk", ERROR, cid, "empty chunk text"))
        if not chunk.chunk_id:
            issues.append(ValidationIssue("missing_chunk_id", ERROR, cid, "chunk has no id"))
        if config.max_chunk_chars and len(chunk.text) > config.max_chunk_chars:
            issues.append(ValidationIssue(
                "oversized_chunk", ERROR, cid,
                f"{len(chunk.text)} chars > max {config.max_chunk_chars}"))
        if not _has_url(chunk, config.url_metadata_keys):
            issues.append(ValidationIssue(
                "missing_url", WARNING, cid,
                f"no url under {list(config.url_metadata_keys)}"))
        for key in config.required_metadata_keys:
            if not str(chunk.metadata.get(key, "")).strip():
                issues.append(ValidationIssue(
                    "missing_required_metadata", ERROR, cid, f"missing '{key}'"))

        if chunk.chunk_id:
            if chunk.chunk_id in seen_ids:
                issues.append(ValidationIssue(
                    "duplicate_chunk_id", ERROR, cid, "duplicate chunk_id in batch"))
            seen_ids.add(chunk.chunk_id)

    return issues


def error_ids(issues: Iterable[ValidationIssue]) -> set[str]:
    """Target IDs that carry at least one ERROR-severity issue."""
    return {i.target_id for i in issues if i.is_error}
