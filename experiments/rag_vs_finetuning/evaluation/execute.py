"""
experiments/rag_vs_finetuning/evaluation/execute.py
Execute the frozen Track A pipeline on the frozen benchmark (Phase P7.2).

Runs the EXISTING Track A pipeline (no changes to retrieval/prompt/model/params)
on all 84 frozen cases, persists an immutable official response record per case,
and returns them. Also appends full RunTraces to the git-ignored traces path.
Nothing is rebuilt, tuned, or regenerated.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from experiments.rag_vs_finetuning.evaluation.models import EvalDataset, ResponseRecord
from experiments.rag_vs_finetuning.track_a.pipeline import ask
from experiments.rag_vs_finetuning.track_a.prompt import PROMPT_VERSION
from experiments.rag_vs_finetuning.track_a.retriever import RETRIEVAL_VERSION
from experiments.rag_vs_finetuning.track_a.trace import persist_trace

RESULTS_PATH = Path(
    "experiments/rag_vs_finetuning/data/evaluation/results/track_a_responses.jsonl")


class OfficialResponse(BaseModel):
    question_id: str
    question: str
    category: str
    program: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    similarity_scores: list[float] = Field(default_factory=list)
    prompt_version: str
    model: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    retrieval_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    answer_char_count: int = 0
    timestamp: str
    versions: dict = Field(default_factory=dict)


def to_response_record(off: OfficialResponse) -> ResponseRecord:
    return ResponseRecord(
        question=off.question, answer=off.answer,
        insufficient_evidence=off.insufficient_evidence,
        citation_chunk_ids=off.citations, retrieved_chunk_ids=off.retrieved_chunk_ids,
        retrieval_latency_ms=off.retrieval_latency_ms,
        generation_latency_ms=off.generation_latency_ms,
        answer_char_count=off.answer_char_count, track="track_a_pure_rag")


def run_track_a(dataset: EvalDataset, *, embedder, collection, llm, top_k: int,
                threshold: float, now: Optional[datetime] = None,
                persist_traces: bool = True) -> list[OfficialResponse]:
    now = now or datetime.now(timezone.utc)
    versions = {"retrieval_version": RETRIEVAL_VERSION, "prompt_version": PROMPT_VERSION,
                "embedding_model": embedder.info.model_id}
    out: list[OfficialResponse] = []
    for case in dataset.cases:
        trace = ask(case.question, embedder=embedder, collection=collection, llm=llm,
                    top_k=top_k, threshold=threshold)
        if persist_traces:
            persist_trace(trace)
        out.append(OfficialResponse(
            question_id=case.id, question=case.question, category=case.category,
            program=case.program, retrieved_chunk_ids=trace.retrieved_chunk_ids,
            similarity_scores=trace.similarity_scores, prompt_version=trace.prompt_version,
            model=trace.model, answer=trace.answer,
            citations=[c.chunk_id for c in trace.citations],
            insufficient_evidence=trace.insufficient_evidence,
            retrieval_latency_ms=trace.retrieval_latency_ms,
            generation_latency_ms=trace.generation_latency_ms,
            total_latency_ms=round(trace.retrieval_latency_ms + trace.generation_latency_ms, 3),
            answer_char_count=trace.answer_char_count,
            timestamp=now.isoformat(), versions=versions))
    return out


def persist_responses(responses: list[OfficialResponse], path: Path = RESULTS_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
             for r in sorted(responses, key=lambda r: r.question_id)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_responses(path: Path = RESULTS_PATH) -> list[OfficialResponse]:
    path = Path(path)
    if not path.exists():
        return []
    return [OfficialResponse.model_validate_json(l)
            for l in path.read_text("utf-8").splitlines() if l.strip()]
