"""
experiments/rag_vs_finetuning/training/models.py
Frozen supervised fine-tuning (SFT) dataset models (Phase P8.0).

Engine-independent Pydantic. The dataset is derived ONLY from the frozen P5
corpus (canonical records + projected documents) — never from Track A responses,
evaluation outputs, or benchmark questions. It is frozen after this phase and is
the sole training dataset for Track B.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

SYSTEM_PROMPT = (
    "You are the CSULB Graduate Center assistant. Answer using only the Graduate "
    "Center program data. If the data does not contain the answer, say you don't "
    "have enough information. Never fabricate facts; preserve published wording."
)


class TrainingExample(BaseModel):
    id: str
    program: str
    category: str          # overview|admissions|application|contact|multi_field|refusal
    instruction: str
    input: str = ""
    output: str
    answerable: bool
    grounded_in: list[str] = Field(default_factory=list)   # projected doc ids / canonical:field


class DatasetManifest(BaseModel):
    corpus_version: str
    generation_version: str
    schema_version: str
    dataset_checksum: str
    total_examples: int
    train_count: int
    val_count: int
    split_seed: int
    split_ratio: float
    generated_at: str
    system_prompt: str
    source: str
    notes: str = ""
