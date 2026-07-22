"""
experiments/rag_vs_finetuning/training/mlx/convert.py
Deterministic derived MLX-LM dataset (Phase P8.1).

Converts the FROZEN SFT records into MLX-LM's chat schema, written as train.jsonl
+ valid.jsonl in a data directory. It preserves every example, the exact seed-42
train/validation membership, and ordering. The frozen source dataset is never
modified; this is a reproducible derived view. Pure stdlib + experiment models
(no MLX import here, so it runs under the repo's Python 3.13).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from experiments.rag_vs_finetuning.training.export import dataset_checksum
from experiments.rag_vs_finetuning.training.models import SYSTEM_PROMPT, TrainingExample
from experiments.rag_vs_finetuning.training.split import (
    SPLIT_RATIO, SPLIT_SEED, deterministic_split,
)

DATA_ROOT = Path("experiments/rag_vs_finetuning/data")
RECORDS = DATA_ROOT / "training" / "ft_records.jsonl"
MLX_DIR = DATA_ROOT / "training" / "mlx"


def _load_records() -> list[TrainingExample]:
    return [TrainingExample.model_validate_json(l)
            for l in RECORDS.read_text("utf-8").splitlines() if l.strip()]


def _chat(ex: TrainingExample) -> dict:
    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ex.instruction},
        {"role": "assistant", "content": ex.output},
    ]}


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_mlx_dataset(*, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    records = _load_records()
    by_id = {e.id: e for e in records}
    train_ids, val_ids = deterministic_split(records, seed=SPLIT_SEED, ratio=SPLIT_RATIO)

    MLX_DIR.mkdir(parents=True, exist_ok=True)
    train_rows = [_chat(by_id[i]) for i in sorted(train_ids)]
    valid_rows = [_chat(by_id[i]) for i in sorted(val_ids)]
    (MLX_DIR / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in train_rows) + "\n", "utf-8")
    (MLX_DIR / "valid.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in valid_rows) + "\n", "utf-8")

    manifest = {
        "derived_from": "experiments/rag_vs_finetuning/data/training/ft_records.jsonl",
        "source_dataset_checksum": dataset_checksum(records),
        "schema": "mlx-lm chat ({\"messages\": [...]})",
        "split_seed": SPLIT_SEED,
        "split_ratio": SPLIT_RATIO,
        "total_examples": len(records),
        "train_count": len(train_ids),
        "valid_count": len(val_ids),
        "train_checksum": _sha256_file(MLX_DIR / "train.jsonl"),
        "valid_checksum": _sha256_file(MLX_DIR / "valid.jsonl"),
        "generated_at": now.isoformat(),
    }
    (MLX_DIR / "mlx_dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return manifest
