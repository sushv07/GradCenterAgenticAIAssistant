"""
experiments/rag_vs_finetuning/evaluation/dataset.py
Load + validate the frozen evaluation dataset (Phase P7.1).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.models import EvalDataset

DATASET_PATH = Path(
    "experiments/rag_vs_finetuning/data/evaluation/eval_dataset.json")


def load_dataset(path: Path = DATASET_PATH) -> EvalDataset:
    return EvalDataset.model_validate_json(Path(path).read_text(encoding="utf-8"))


def compute_checksum(dataset: EvalDataset) -> str:
    serial = json.dumps(
        sorted((c.model_dump() for c in dataset.cases), key=lambda c: c["id"]),
        sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serial.encode("utf-8")).hexdigest()


def load_chunk_ids(chunks_jsonl: Path) -> set[str]:
    lines = Path(chunks_jsonl).read_text(encoding="utf-8").strip().splitlines()
    return {json.loads(l)["chunk_id"] for l in lines if l.strip()}


def validate_dataset(dataset: EvalDataset, known_chunk_ids: set[str]) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []

    # checksum + count
    if compute_checksum(dataset) != dataset.dataset_checksum:
        errors.append("dataset_checksum mismatch (dataset was modified)")
    if len(dataset.cases) != dataset.case_count:
        errors.append(f"case_count {dataset.case_count} != actual {len(dataset.cases)}")

    # unique ids + questions
    ids = [c.id for c in dataset.cases]
    if len(set(ids)) != len(ids):
        errors.append("duplicate case ids")
    qs = [c.question.strip().lower() for c in dataset.cases]
    dups = [q for q, n in Counter(qs).items() if n > 1]
    if dups:
        errors.append(f"duplicate questions: {dups[:3]}")

    for c in dataset.cases:
        if c.answerable:
            if not c.expected_citation_targets:
                errors.append(f"{c.id}: answerable but no supporting chunks")
            for t in c.expected_citation_targets:
                if t not in known_chunk_ids:
                    errors.append(f"{c.id}: citation target does not exist: {t}")
            if c.expected_answer is None:
                errors.append(f"{c.id}: answerable but expected_answer is null")
        else:  # unknown / source_missing
            if c.expected_answer is not None:
                errors.append(f"{c.id}: non-answerable but has an expected_answer")
            if c.expected_citation_targets:
                errors.append(f"{c.id}: non-answerable but has citation targets")

    # every program represented
    programs = {c.program for c in dataset.cases}
    if len(programs) < 12:
        errors.append(f"only {len(programs)} programs represented (expected 12)")

    return errors
