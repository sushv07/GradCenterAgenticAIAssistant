"""
ingestion/pipeline/config.py
Declarative pipeline configuration.

All tunables live here as data, not logic. Defaults intentionally match the
current production values (`config/settings.py`) so migrating production changes
no behaviour; callers may override per source. This module imports no infra —
adapters read these values when they are constructed.
"""
from __future__ import annotations

from dataclasses import dataclass

# Separator hierarchy used by the recursive character chunker adapter. Kept here
# (as data) so the chunking strategy is configuration, not hard-coded in infra.
# Mirrors rag/chunking.py's historical order exactly.
DEFAULT_SEPARATORS: tuple[str, ...] = (
    "\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", "",
)


@dataclass(frozen=True)
class PipelineConfig:
    """Tunables for one ingestion run.

    Chunking:
        chunk_size / chunk_overlap / separators — character-based splitting.
    Embedding:
        embedding_model / device / normalize — the embedding backend.
    Store:
        collection_name / distance — vector store identity + metric.
    Validation:
        max_chunk_chars — reject chunks larger than this (0 disables).
        required_metadata_keys — keys every chunk must carry (beyond a URL).
        url_metadata_keys — any one of these satisfies the "has a source" check.
        drop_invalid — if True, invalid chunks are skipped; else only reported.
    """

    # Chunking (production defaults: 500 / 75)
    chunk_size: int = 500
    chunk_overlap: int = 75
    separators: tuple[str, ...] = DEFAULT_SEPARATORS

    # Embedding (production defaults)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_normalize: bool = True

    # Vector store
    collection_name: str = "csulb_grad_center"
    distance: str = "cosine"

    # Validation
    max_chunk_chars: int = 2000
    required_metadata_keys: tuple[str, ...] = ()
    url_metadata_keys: tuple[str, ...] = ("source_url", "url")
    drop_invalid: bool = True
