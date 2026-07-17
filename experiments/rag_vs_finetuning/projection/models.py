"""
experiments/rag_vs_finetuning/projection/models.py
Retrieval-neutral projection models (Phase P5).

RetrievalDocument is engine-independent: it imports no LangChain, Chroma,
embedding, or vector-store types, holds no precomputed vectors, and is plain
JSON-serializable Pydantic. It is the input contract for P6 chunking/embedding
and is fully traceable back to a frozen canonical record and its exact source
snapshots.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    source_id: str
    source_url: str
    content_hash: str


class RetrievalDocument(BaseModel):
    document_id: str                       # deterministic: "<program_id>::<section>"
    program_id: str
    program_level: str
    title: str
    section: str                           # overview | admissions | application | contact
    content: str                           # deterministic template text (no LLM, no timestamps)
    source_references: list[SourceReference] = Field(default_factory=list)
    volatility: str                        # dominant volatility of the section's facts
    freshness_status: str                  # fresh | stale
    metadata: dict = Field(default_factory=dict)   # flat primitives only
    canonical_record_hash: str             # ties back to the frozen record
    projection_version: str
