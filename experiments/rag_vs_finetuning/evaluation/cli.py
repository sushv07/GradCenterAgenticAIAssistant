"""
experiments/rag_vs_finetuning/evaluation/cli.py
Evaluation CLI (Phase P7.1).

    python -m experiments.rag_vs_finetuning.evaluation.cli validate
    python -m experiments.rag_vs_finetuning.evaluation.cli summary

`evaluate` scores a track's persisted responses; no benchmark run is performed
in this phase.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from experiments.rag_vs_finetuning.evaluation.dataset import (
    DATASET_PATH, load_chunk_ids, load_dataset, validate_dataset,
)

_CHUNKS = Path("experiments/rag_vs_finetuning/data/chunks/chunks.jsonl")


def cmd_validate() -> int:
    ds = load_dataset(Path.cwd() / DATASET_PATH)
    errors = validate_dataset(ds, load_chunk_ids(Path.cwd() / _CHUNKS))
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  -", e)
        return 1
    print(f"VALID: {len(ds.cases)} cases, checksum {ds.dataset_checksum[:20]}…, frozen={ds.frozen}")
    return 0


def cmd_summary() -> int:
    ds = load_dataset(Path.cwd() / DATASET_PATH)
    print(f"dataset_version: {ds.dataset_version} | frozen: {ds.frozen} | cases: {len(ds.cases)}")
    print("by category:", dict(sorted(Counter(c.category for c in ds.cases).items())))
    print("by program:", dict(sorted(Counter(c.program for c in ds.cases).items())))
    print("by difficulty:", dict(sorted(Counter(c.difficulty for c in ds.cases).items())))
    print("answerable:", sum(c.answerable for c in ds.cases),
          "| source_missing:", sum(c.source_missing for c in ds.cases))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    if argv[0] == "validate":
        return cmd_validate()
    if argv[0] == "summary":
        return cmd_summary()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
