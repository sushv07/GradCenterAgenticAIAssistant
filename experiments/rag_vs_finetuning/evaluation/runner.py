"""
experiments/rag_vs_finetuning/evaluation/runner.py
Evaluation runner (Phase P7.1).

Scores a track's responses against the FROZEN ground-truth dataset and produces
an EvalReport. Track-agnostic: any track (A/B/C) supplies ResponseRecords keyed
by question. No LLM judge; no benchmark numbers are computed as part of this
phase (the runner is exercised with synthetic responses in tests only).
"""
from __future__ import annotations

from collections import defaultdict

from experiments.rag_vs_finetuning.evaluation.metrics import aggregate, score_case
from experiments.rag_vs_finetuning.evaluation.models import (
    EvalDataset, EvalReport, ResponseRecord,
)


def run_evaluation(dataset: EvalDataset, responses: list[ResponseRecord],
                   *, track: str = "") -> EvalReport:
    by_question = {r.question.strip(): r for r in responses}
    results = []
    used: dict[str, ResponseRecord] = {}
    failures = 0
    for case in dataset.cases:
        resp = by_question.get(case.question.strip())
        if resp is None:
            failures += 1
        else:
            used[case.id] = resp
        results.append(score_case(case, resp))

    metrics = aggregate(results, used)

    by_cat = defaultdict(list)
    for r in results:
        by_cat[r.category].append(r)
    metrics_by_category = {}
    for cat, rs in sorted(by_cat.items()):
        responded = [r for r in rs if r.responded]
        correct = [1.0 if r.answer_correct else 0.0 for r in responded]
        metrics_by_category[cat] = {
            "count": len(rs),
            "responded": len(responded),
            "accuracy": round(sum(correct) / len(correct), 4) if correct else None,
        }

    return EvalReport(
        track=track, dataset_version=dataset.dataset_version,
        dataset_checksum=dataset.dataset_checksum, case_count=len(dataset.cases),
        responded_count=len(used), metrics=metrics,
        metrics_by_category=metrics_by_category, failure_count=failures)
