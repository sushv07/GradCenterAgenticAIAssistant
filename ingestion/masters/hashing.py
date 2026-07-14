"""
ingestion/masters/hashing.py
Content-hash generation — the authoritative identity of fetched source content.

sha256 over the raw bytes; change detection and snapshot identity rely on this,
never on URLs or timestamps.
"""
from __future__ import annotations

import hashlib


def content_hash(content: bytes) -> str:
    """Return 'sha256:<hexdigest>' for raw fetched content."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


def hash_hex(content: bytes) -> str:
    """The bare hex digest (used for snapshot filenames)."""
    return hashlib.sha256(content).hexdigest()
