"""
experiments/rag_vs_finetuning/training/export.py
Export + freeze the SFT dataset (Phase P8.0).

Writes deterministic JSONL in the standard Alpaca instruction format
(instruction/input/output), a separate conversational export, per-split files,
and a checksummed manifest that freezes the dataset. No model is trained here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from experiments.rag_vs_finetuning.training.generate import (
    DATA_ROOT, GENERATION_VERSION, SCHEMA_VERSION,
)
from experiments.rag_vs_finetuning.training.models import (
    DatasetManifest, SYSTEM_PROMPT, TrainingExample,
)
from experiments.rag_vs_finetuning.training.split import SPLIT_RATIO, SPLIT_SEED

TRAIN_DIR = DATA_ROOT / "training"


def dataset_checksum(examples: list[TrainingExample]) -> str:
    serial = "\n".join(
        json.dumps(e.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for e in sorted(examples, key=lambda e: e.id))
    return "sha256:" + hashlib.sha256(serial.encode("utf-8")).hexdigest()


def to_alpaca(ex: TrainingExample) -> dict:
    return {"instruction": ex.instruction, "input": ex.input, "output": ex.output}


def to_conversational(ex: TrainingExample) -> dict:
    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ex.instruction},
        {"role": "assistant", "content": ex.output},
    ]}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")


def export_dataset(examples: list[TrainingExample], train_ids: list[str],
                   val_ids: list[str], *, corpus_version: str = "1.0",
                   now: Optional[datetime] = None) -> DatasetManifest:
    now = now or datetime.now(timezone.utc)
    ordered = sorted(examples, key=lambda e: e.id)
    by_id = {e.id: e for e in ordered}

    _write_jsonl(TRAIN_DIR / "ft_dataset.jsonl", [to_alpaca(e) for e in ordered])
    _write_jsonl(TRAIN_DIR / "ft_train.jsonl", [to_alpaca(by_id[i]) for i in train_ids])
    _write_jsonl(TRAIN_DIR / "ft_val.jsonl", [to_alpaca(by_id[i]) for i in val_ids])
    _write_jsonl(TRAIN_DIR / "ft_conversational.jsonl", [to_conversational(e) for e in ordered])
    # full records (with provenance + category) for audit
    _write_jsonl(TRAIN_DIR / "ft_records.jsonl", [e.model_dump(mode="json") for e in ordered])

    manifest = DatasetManifest(
        corpus_version=corpus_version, generation_version=GENERATION_VERSION,
        schema_version=SCHEMA_VERSION, dataset_checksum=dataset_checksum(examples),
        total_examples=len(examples), train_count=len(train_ids), val_count=len(val_ids),
        split_seed=SPLIT_SEED, split_ratio=SPLIT_RATIO, generated_at=now.isoformat(),
        system_prompt=SYSTEM_PROMPT,
        source="frozen P5 corpus (projected documents + canonical records); "
               "NOT Track A responses, evaluation outputs, or benchmark questions",
        notes="Frozen dataset; sole training dataset for Track B.")
    (TRAIN_DIR / "ft_manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", "utf-8")
    return manifest
