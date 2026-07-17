"""
experiments/rag_vs_finetuning/evaluation/models.py
Frozen evaluation benchmark models (Phase P7.1).

Engine-independent Pydantic. The dataset is FROZEN: after this phase no case is
added, removed, or modified. It is reused UNCHANGED by Tracks A, B, and C.
Responses are scored deterministically (no LLM judge).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    question: str
    program: str
    category: str
    difficulty: str
    expected_answer: Optional[str] = None
    acceptable_alternatives: list[str] = Field(default_factory=list)
    required_program: Optional[str] = None
    required_section: Optional[str] = None
    expected_citation_targets: list[str] = Field(default_factory=list)
    answerable: bool
    source_missing: bool = False
    notes: str = ""


class EvalDataset(BaseModel):
    dataset_version: str
    frozen: bool
    generated_from: str
    case_count: int
    dataset_checksum: str
    cases: list[EvalCase]


class ResponseRecord(BaseModel):
    """A track's response to one question (track-agnostic: Track A/B/C)."""
    question: str
    answer: str
    insufficient_evidence: bool = False
    citation_chunk_ids: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    answer_char_count: int = 0
    track: str = ""


class CaseResult(BaseModel):
    id: str
    category: str
    answerable: bool
    responded: bool
    abstained: bool
    answer_correct: bool
    hallucinated: bool
    citation_precision: Optional[float] = None
    citation_recall: Optional[float] = None
    retrieval_recall: Optional[float] = None
    retrieval_precision: Optional[float] = None


class EvalReport(BaseModel):
    track: str
    dataset_version: str
    dataset_checksum: str
    case_count: int
    responded_count: int
    metrics: dict
    metrics_by_category: dict
    failure_count: int
