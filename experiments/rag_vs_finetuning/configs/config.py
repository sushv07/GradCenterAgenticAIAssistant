"""
experiments/rag_vs_finetuning/configs/config.py
Typed, validated loader for the experiment configuration (Phase P6).

Settings live in experiment.yaml, not scattered code constants. Loading validates
the shape via Pydantic and normalizes the chunking unit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

_CONFIG_PATH = Path(__file__).resolve().parent / "experiment.yaml"


class ChunkingCfg(BaseModel):
    version: str
    unit: str
    size: int
    overlap: int


class EmbeddingCfg(BaseModel):
    model: str
    normalize: bool
    batch_size: int
    device: str
    dimension: int


class VectorStoreCfg(BaseModel):
    provider: str
    collection_name: str
    persistence_path: str
    distance_metric: str
    index_version: str


class CorpusCfg(BaseModel):
    freeze_id: str
    corpus_version: str
    schema_version: str
    data_root: str
    record_count: int


class ProjectionCfg(BaseModel):
    version: str


class TrackALLMCfg(BaseModel):
    provider: str
    base_url: str
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    seed: int


class TrackACfg(BaseModel):
    retrieval_version: str
    top_k: int
    similarity_threshold: float
    prompt_version: str
    llm: TrackALLMCfg
    traces_path: str


class ExperimentConfig(BaseModel):
    experiment_id: str
    code_baseline_commit: str
    corpus: CorpusCfg
    projection: ProjectionCfg
    chunking: ChunkingCfg
    embedding: EmbeddingCfg
    vector_store: VectorStoreCfg
    track_a: Optional[TrackACfg] = None

    def validate_units(self) -> "ExperimentConfig":
        if self.chunking.unit != "characters":
            raise ValueError(f"unsupported chunking unit: {self.chunking.unit}")
        return self


def load_config(path: Path = _CONFIG_PATH) -> ExperimentConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ExperimentConfig.model_validate(data).validate_units()
