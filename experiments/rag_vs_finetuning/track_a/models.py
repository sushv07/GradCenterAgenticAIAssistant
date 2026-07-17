"""
experiments/rag_vs_finetuning/track_a/models.py
Track A (Pure RAG baseline) result + trace models (Phase P7).

Engine-independent Pydantic. No LangChain, no Chroma objects, no production RAG.
These records are the persisted evidence of each run and the future evaluation
input.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from experiments.rag_vs_finetuning.projection.models import SourceReference


class RetrievedChunkRef(BaseModel):
    chunk_id: str
    document_id: str
    program_id: str
    section: str
    similarity_score: float
    source_references: list[SourceReference] = Field(default_factory=list)
    content: str


class RetrievalResult(BaseModel):
    query: str
    query_embedding_model: str
    retrieved_chunks: list[RetrievedChunkRef] = Field(default_factory=list)
    similarity_scores: list[float] = Field(default_factory=list)
    retrieval_latency_ms: float
    top_k: int
    threshold: float
    distance_metric: str
    retrieval_version: str


class Citation(BaseModel):
    chunk_id: str
    program_id: str
    section: str
    source_ids: list[str] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)


class GenerationConfig(BaseModel):
    model: str
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 512
    stop: list[str] = Field(default_factory=list)
    seed: Optional[int] = 0


class RunTrace(BaseModel):
    question: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    similarity_scores: list[float] = Field(default_factory=list)
    prompt_version: str
    prompt_text: str
    model: str
    generation_config: GenerationConfig
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    insufficient_evidence: bool = False
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    prompt_char_count: int = 0
    answer_char_count: int = 0
    retrieval_version: str = ""
    track: str = "track_a_pure_rag"
