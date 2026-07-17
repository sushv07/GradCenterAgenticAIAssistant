"""
experiments/rag_vs_finetuning/evaluation/metrics.py
Deterministic (non-LLM) scoring for the frozen benchmark (Phase P7.1).

Per-case scoring compares a track response against frozen ground truth using
substring containment (case-insensitive) and set overlap. No LLM judge, no
benchmark numbers are produced here — only the metric machinery.
"""
from __future__ import annotations

from typing import Optional

from experiments.rag_vs_finetuning.evaluation.models import (
    CaseResult, EvalCase, ResponseRecord,
)

_ABSTAIN_PHRASES = (
    "don't have that information", "do not have that information",
    "no information", "not available", "cannot find", "unable to find",
    "not in the provided sources", "insufficient",
)


def abstained(resp: ResponseRecord) -> bool:
    if resp.insufficient_evidence:
        return True
    low = resp.answer.lower()
    return any(p in low for p in _ABSTAIN_PHRASES)


def _answer_correct(case: EvalCase, resp: ResponseRecord) -> bool:
    if abstained(resp):
        return False
    low = resp.answer.lower()
    keys = [case.expected_answer, *case.acceptable_alternatives]
    return any(k and k.lower() in low for k in keys)


def _overlap(expected: set[str], got: set[str]) -> tuple[Optional[float], Optional[float]]:
    if not expected:
        return None, None
    inter = expected & got
    precision = (len(inter) / len(got)) if got else 0.0
    recall = len(inter) / len(expected)
    return round(precision, 4), round(recall, 4)


def score_case(case: EvalCase, resp: Optional[ResponseRecord]) -> CaseResult:
    if resp is None:
        return CaseResult(id=case.id, category=case.category, answerable=case.answerable,
                          responded=False, abstained=False, answer_correct=False,
                          hallucinated=False)
    abst = abstained(resp)
    if case.answerable:
        answer_correct = _answer_correct(case, resp)
        hallucinated = False
        cp, cr = _overlap(set(case.expected_citation_targets), set(resp.citation_chunk_ids))
        rr_p, rr_r = _overlap(set(case.expected_citation_targets), set(resp.retrieved_chunk_ids))
    else:
        answer_correct = abst                # correct = abstained
        hallucinated = not abst              # fabricated a substantive answer
        cp = cr = rr_p = rr_r = None
    return CaseResult(
        id=case.id, category=case.category, answerable=case.answerable, responded=True,
        abstained=abst, answer_correct=answer_correct, hallucinated=hallucinated,
        citation_precision=cp, citation_recall=cr,
        retrieval_precision=rr_p, retrieval_recall=rr_r)


def _mean(xs: list[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def aggregate(results: list[CaseResult], responses: dict[str, ResponseRecord]) -> dict:
    answerable = [r for r in results if r.answerable and r.responded]
    non_answerable = [r for r in results if not r.answerable and r.responded]
    resp_list = list(responses.values())
    return {
        "answer_accuracy": _mean([1.0 if r.answer_correct else 0.0 for r in answerable]),
        "abstention_accuracy": _mean([1.0 if r.abstained else 0.0 for r in non_answerable]),
        "hallucination_rate": _mean([1.0 if r.hallucinated else 0.0 for r in non_answerable]),
        "citation_precision": _mean([r.citation_precision for r in answerable if r.citation_precision is not None]),
        "citation_recall": _mean([r.citation_recall for r in answerable if r.citation_recall is not None]),
        "retrieval_recall_at_k": _mean([r.retrieval_recall for r in answerable if r.retrieval_recall is not None]),
        "retrieval_precision_at_k": _mean([r.retrieval_precision for r in answerable if r.retrieval_precision is not None]),
        "avg_retrieval_latency_ms": _mean([x.retrieval_latency_ms for x in resp_list]),
        "avg_generation_latency_ms": _mean([x.generation_latency_ms for x in resp_list]),
        "avg_end_to_end_latency_ms": _mean([x.retrieval_latency_ms + x.generation_latency_ms for x in resp_list]),
        "avg_answer_chars": _mean([float(x.answer_char_count) for x in resp_list]),
    }
