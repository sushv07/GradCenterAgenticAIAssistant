"""
experiments/rag_vs_finetuning/training/split.py
Deterministic train/validation split (Phase P8.0).

Fixed seed; reproducible. The evaluation benchmark questions are never part of
this dataset (enforced in generation + validation), so the split cannot leak
benchmark cases.
"""
from __future__ import annotations

import random

from experiments.rag_vs_finetuning.training.models import TrainingExample

SPLIT_SEED = 42
SPLIT_RATIO = 0.9


def deterministic_split(examples: list[TrainingExample], *, seed: int = SPLIT_SEED,
                        ratio: float = SPLIT_RATIO) -> tuple[list[str], list[str]]:
    ordered = sorted(examples, key=lambda e: e.id)
    ids = [e.id for e in ordered]
    rng = random.Random(seed)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    n_train = int(round(len(shuffled) * ratio))
    train = sorted(shuffled[:n_train])
    val = sorted(shuffled[n_train:])
    return train, val
