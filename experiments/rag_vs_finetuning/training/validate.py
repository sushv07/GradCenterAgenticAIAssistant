"""
experiments/rag_vs_finetuning/training/validate.py
Validation for the frozen SFT dataset (Phase P8.0).

Confirms every answerable answer is supported by the frozen corpus, refusals use
the exact refusal text, there are no duplicates / malformed / empty records, and
NO instruction overlaps an evaluation-benchmark question (leakage guard).
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.training.generate import DATA_ROOT, REFUSAL
from experiments.rag_vs_finetuning.training.models import TrainingExample


def _projected_by_id() -> dict[str, str]:
    lines = (DATA_ROOT / "projected_documents" / "documents.jsonl").read_text("utf-8").splitlines()
    return {json.loads(l)["document_id"]: json.loads(l)["content"]
            for l in lines if l.strip()}


def _benchmark_questions() -> set[str]:
    ds = json.loads((DATA_ROOT / "evaluation" / "eval_dataset.json").read_text("utf-8"))
    return {c["question"].strip().lower() for c in ds["cases"]}


def validate_examples(examples: list[TrainingExample]) -> tuple[list[str], dict]:
    errors: list[str] = []
    proj = _projected_by_id()
    bench = _benchmark_questions()

    seen: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for ex in examples:
        if not ex.instruction.strip() or not ex.output.strip():
            errors.append(f"{ex.id}: empty instruction/output")
        if ex.id in ids:
            errors.append(f"duplicate id {ex.id}")
        ids.add(ex.id)
        key = (ex.instruction.strip().lower(), ex.output.strip())
        if key in seen:
            errors.append(f"{ex.id}: duplicate (instruction, output)")
        seen.add(key)
        if ex.instruction.strip().lower() in bench:
            errors.append(f"{ex.id}: instruction overlaps an evaluation-benchmark question")
        if ex.answerable:
            # the output must be EXACTLY the grounded projected content(s) — no
            # invented or paraphrased facts beyond the frozen corpus text.
            expected = " ".join(proj[g] for g in ex.grounded_in if g in proj)
            if ex.output.strip() != expected.strip() or not expected.strip():
                errors.append(f"{ex.id}: answer not exactly supported by the frozen corpus")
        else:
            if ex.output != REFUSAL:
                errors.append(f"{ex.id}: refusal output does not match the canonical refusal text")
            if ex.grounded_in and not all(g.startswith("canonical:") for g in ex.grounded_in):
                errors.append(f"{ex.id}: refusal grounded_in must reference source_missing fields")

    stats = {
        "total": len(examples),
        "answerable": sum(e.answerable for e in examples),
        "refusals": sum(not e.answerable for e in examples),
        "unique_instructions": len({e.instruction.strip().lower() for e in examples}),
        "benchmark_overlap": sum(1 for e in examples if e.instruction.strip().lower() in bench),
    }
    return errors, stats
