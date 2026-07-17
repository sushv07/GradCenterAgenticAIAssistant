"""
experiments/rag_vs_finetuning/chunking/models.py
RetrievalChunk — the experiment-neutral chunk artifact (Phase P6).

Engine-independent: plain JSON-serializable Pydantic. Imports no LangChain, no
Chroma, no vector object, and no LLM provider. It is traceable to its parent
RetrievalDocument, the canonical record, and the exact source snapshots.

Note on token_count: it is an approximate WHITESPACE word count, not model
subword tokens. Chunking DECISIONS use characters (see chunk.py); token_count is
informational metadata only.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from experiments.rag_vs_finetuning.projection.models import SourceReference


class RetrievalChunk(BaseModel):
    chunk_id: str                          # "<document_id>::chunk::<zero-padded-index>"
    document_id: str
    program_id: str
    program_level: str
    title: str
    section: str
    content: str
    chunk_index: int
    character_start: int
    character_end: int
    token_count: int                       # whitespace word count (not subword tokens)
    source_references: list[SourceReference] = Field(default_factory=list)
    volatility: str
    freshness_status: str
    metadata: dict = Field(default_factory=dict)   # flat primitives only
    canonical_record_hash: str
    projection_version: str
    chunking_version: str
    content_hash: str                      # sha256 of content
