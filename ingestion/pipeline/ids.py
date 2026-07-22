"""
ingestion/pipeline/ids.py
Deterministic identifiers and content hashes for idempotent ingestion.

Determinism is the foundation of idempotent indexing (Phase 6): the same source
content must always produce the same document/chunk IDs so repeated runs upsert
in place instead of appending duplicates.

Backward compatibility: `chunk_id(document_id_from_url(url), i)` reproduces the
EXACT id `rag/chunking.py` has always produced (`md5(url)[:8]` + `_{i:04d}`), so
migrating production changes no stored id.
"""
from __future__ import annotations

import hashlib

# Length of the hex prefix used for short, filesystem-safe document IDs.
_DOC_ID_LEN = 8


def document_id_from_url(source_url: str) -> str:
    """Stable 8-char document id derived from a source URL (md5 prefix).

    Matches the prefix `rag/chunking.py` uses for chunk ids, so a page's chunks
    keep their historical identifiers after migration.
    """
    return hashlib.md5(source_url.encode("utf-8")).hexdigest()[:_DOC_ID_LEN]


def chunk_id(document_id: str, index: int) -> str:
    """Deterministic chunk id: ``"{document_id}_{index:04d}"``.

    Zero-padded index preserves sort order and supports up to 9999 chunks/doc.
    With ``document_id == md5(url)[:8]`` this equals the legacy production id.
    """
    return f"{document_id}_{index:04d}"


def content_hash(text: str) -> str:
    """Deterministic content fingerprint, used to detect unchanged vs updated.

    Returned as ``"sha256:<hex>"`` so callers can store it in metadata and skip
    re-embedding a chunk whose text has not changed.
    """
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
