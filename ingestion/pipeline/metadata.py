"""
ingestion/pipeline/metadata.py
The production-ready metadata schema for indexed chunks.

Vector-store constraint: ChromaDB metadata must be flat primitives (str/int/
float/bool) — no lists or dicts. `to_flat_dict()` enforces that and drops
empty/None values so a source only carries the fields it actually has.

Backward compatibility: this schema is a SUPERSET of the historical production
keys. The production page loader keeps emitting exactly its legacy keys
(`title, url, page_type, program_name, content_category, discovered_from,
parent_program_url, workflow_priority, links_json`), so migrating production
changes no stored metadata. Richer sources (doctoral programs, policies, …)
opt into the additional fields below.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Canonical field names (Phase 5). Kept as constants so loaders/validators refer
# to one source of truth rather than stringly-typed keys.
PROGRAM_NAME = "program_name"
DEGREE_LEVEL = "degree_level"
DEPARTMENT = "department"
COLLEGE = "college"
CONTENT_TYPE = "content_type"
SOURCE_URL = "source_url"
DOCUMENT_ID = "document_id"
CHUNK_ID = "chunk_id"
CHUNK_INDEX = "chunk_index"
INGESTION_TIMESTAMP = "ingestion_timestamp"
LAST_UPDATED = "last_updated"


@dataclass
class ChunkMetadata:
    """Recommended production metadata for a chunk (all fields optional).

    Loaders populate what a source knows; unknown fields stay empty and are
    dropped by `to_flat_dict()`. `chunk_id`/`chunk_index`/`document_id` are set
    by the chunker, not the loader.
    """

    program_name: str = ""
    degree_level: str = ""          # e.g. "Masters", "Doctoral"
    department: str = ""
    college: str = ""
    content_type: str = ""          # e.g. "program_application", "faq", "policy"
    source_url: str = ""
    document_id: str = ""
    chunk_id: str = ""
    chunk_index: int = -1
    ingestion_timestamp: str = ""   # RFC3339 UTC; informational (non-deterministic)
    last_updated: str = ""          # source's own last-updated, when known

    def to_flat_dict(self) -> dict[str, Any]:
        """Flat, primitive-only dict with empty/negative-index fields removed."""
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if key == CHUNK_INDEX:
                if isinstance(value, int) and value >= 0:
                    out[key] = value
                continue
            if value not in ("", None):
                out[key] = value
        return out


# Metadata keys under which a source URL may appear. Kept as a tuple (not a
# single required key) so the legacy production schema ("url") and the canonical
# schema ("source_url") both satisfy validation. The validator consults this.
URL_METADATA_KEYS: tuple[str, ...] = (SOURCE_URL, "url")
