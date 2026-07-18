"""
experiments/rag_vs_finetuning/training/cli.py
Frozen fine-tuning dataset CLI (Phase P8.0).

    python -m experiments.rag_vs_finetuning.training.cli build-ft-dataset
    python -m experiments.rag_vs_finetuning.training.cli dataset-stats

No model is trained here.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from experiments.rag_vs_finetuning.training.export import TRAIN_DIR, export_dataset
from experiments.rag_vs_finetuning.training.generate import generate_examples
from experiments.rag_vs_finetuning.training.split import deterministic_split
from experiments.rag_vs_finetuning.training.validate import validate_examples


def _stats(examples) -> dict:
    ins = [len(e.instruction) for e in examples]
    outs = [len(e.output) for e in examples]
    vocab = set()
    for e in examples:
        vocab.update((e.instruction + " " + e.output).lower().split())
    return {
        "total": len(examples),
        "by_program": dict(sorted(Counter(e.program for e in examples).items())),
        "by_category": dict(sorted(Counter(e.category for e in examples).items())),
        "avg_instruction_len": round(sum(ins) / len(ins), 1),
        "avg_answer_len": round(sum(outs) / len(outs), 1),
        "longest_answer": max(outs), "shortest_answer": min(outs),
        "vocabulary_size": len(vocab),
    }


def cmd_build() -> int:
    examples = generate_examples()
    errors, vstats = validate_examples(examples)
    if errors:
        print("VALIDATION FAILED:")
        for e in errors[:15]:
            print("  -", e)
        return 1
    train, val = deterministic_split(examples)
    manifest = export_dataset(examples, train, val)
    print(f"built {manifest.total_examples} examples "
          f"(train {manifest.train_count} / val {manifest.val_count}); "
          f"checksum {manifest.dataset_checksum[:20]}…")
    print("validation:", vstats)
    return 0


def cmd_stats() -> int:
    records = Path.cwd() / TRAIN_DIR / "ft_records.jsonl"
    if not records.exists():
        print("no dataset; run build-ft-dataset first"); return 1
    from experiments.rag_vs_finetuning.training.models import TrainingExample
    examples = [TrainingExample.model_validate_json(l)
                for l in records.read_text("utf-8").splitlines() if l.strip()]
    print(json.dumps(_stats(examples), indent=2))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    if argv[0] == "build-ft-dataset":
        return cmd_build()
    if argv[0] == "dataset-stats":
        return cmd_stats()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
