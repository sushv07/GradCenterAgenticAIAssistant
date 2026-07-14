"""
ingestion/masters/snapshots.py
Immutable source-snapshot storage keyed by content hash.

Every fetched source is written once under
    <base_dir>/<program_id>/<hexhash>.<ext>
and never overwritten. Re-fetching identical content is a no-op that returns the
existing snapshot. Snapshots are the evidence base for provenance, validation,
reproducibility, and future freshness experiments.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from domain.programs.enums import ExtractionMethod, SourceType
from domain.programs.sources import Source
from ingestion.masters.fetching import FetchResult, is_official_csulb_host
from ingestion.masters.hashing import content_hash, hash_hex


class SnapshotRecord(BaseModel):
    source_id: str
    source_url: str
    source_type: SourceType
    official: bool
    content_hash: str
    fetched_at: datetime
    path: str
    was_newly_written: bool


class SnapshotStore:
    """Content-addressed, append-only snapshot storage."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def save(
        self,
        *,
        program_id: str,
        source_id: str,
        source_type: SourceType,
        fetch: FetchResult,
        ext: str = "html",
    ) -> SnapshotRecord:
        digest = hash_hex(fetch.content)
        program_dir = self.base_dir / program_id
        program_dir.mkdir(parents=True, exist_ok=True)
        path = program_dir / f"{digest}.{ext}"
        newly = not path.exists()
        if newly:  # never overwrite an existing snapshot
            path.write_bytes(fetch.content)
        return SnapshotRecord(
            source_id=source_id,
            source_url=fetch.url,
            source_type=source_type,
            official=is_official_csulb_host(fetch.url),
            content_hash=content_hash(fetch.content),
            fetched_at=fetch.fetched_at,
            path=str(path),
            was_newly_written=newly,
        )


def snapshot_to_source(
    snapshot: SnapshotRecord,
    *,
    extraction_method: ExtractionMethod,
    last_verified: Optional[date] = None,
) -> Source:
    """Build a domain provenance Source from a snapshot record."""
    return Source(
        source_id=snapshot.source_id,
        source_url=snapshot.source_url,
        source_type=snapshot.source_type,
        official=snapshot.official,
        fetched_at=snapshot.fetched_at,
        last_verified=last_verified or snapshot.fetched_at.date(),
        content_hash=snapshot.content_hash,
        extraction_method=extraction_method,
    )
