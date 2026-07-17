"""
experiments/rag_vs_finetuning/track_a/pipeline.py
Track A Pure RAG pipeline: question -> retrieve -> prompt -> base LLM -> grounded
answer -> citations -> full trace (Phase P7).

Never fabricates: when nothing is retrieved (empty or all below threshold) it
returns the insufficient-evidence answer WITHOUT calling the model; citations are
always drawn from the actually-retrieved evidence chunks (never invented). No
fine-tuning, hybrid retrieval, reranking, tool-calling, or evaluation.
"""
from __future__ import annotations

import time

from experiments.rag_vs_finetuning.track_a.models import Citation, RunTrace
from experiments.rag_vs_finetuning.track_a.prompt import (
    PROMPT_VERSION, _INSUFFICIENT_ANSWER, build_prompt,
)
from experiments.rag_vs_finetuning.track_a.retriever import retrieve


def _citations(result) -> list[Citation]:
    out = []
    for c in result.retrieved_chunks:
        out.append(Citation(
            chunk_id=c.chunk_id, program_id=c.program_id, section=c.section,
            source_ids=[s.source_id for s in c.source_references],
            source_hashes=[s.content_hash for s in c.source_references]))
    return out


def ask(question: str, *, embedder, collection, llm, top_k: int = 4,
        threshold: float = 0.0) -> RunTrace:
    result = retrieve(question, embedder=embedder, collection=collection,
                      top_k=top_k, threshold=threshold)

    # Failure mode: no usable evidence -> refuse, do not call the model.
    if not result.retrieved_chunks:
        return RunTrace(
            question=question, retrieved_chunk_ids=[], similarity_scores=[],
            prompt_version=PROMPT_VERSION, prompt_text="(no retrieval; refused)",
            model=llm.config.model, generation_config=llm.config,
            answer=_INSUFFICIENT_ANSWER, citations=[], insufficient_evidence=True,
            retrieval_latency_ms=result.retrieval_latency_ms,
            retrieval_version=result.retrieval_version,
            prompt_char_count=0, answer_char_count=len(_INSUFFICIENT_ANSWER))

    system, user, full = build_prompt(question, result)
    gen_start = time.perf_counter()
    answer = llm.generate(system, user)
    gen_latency = round((time.perf_counter() - gen_start) * 1000, 3)

    insufficient = answer.strip() == _INSUFFICIENT_ANSWER
    citations = [] if insufficient else _citations(result)
    return RunTrace(
        question=question,
        retrieved_chunk_ids=[c.chunk_id for c in result.retrieved_chunks],
        similarity_scores=result.similarity_scores,
        prompt_version=PROMPT_VERSION, prompt_text=full,
        model=llm.config.model, generation_config=llm.config,
        answer=answer, citations=citations, insufficient_evidence=insufficient,
        retrieval_latency_ms=result.retrieval_latency_ms,
        generation_latency_ms=gen_latency,
        prompt_char_count=len(full), answer_char_count=len(answer),
        retrieval_version=result.retrieval_version)
