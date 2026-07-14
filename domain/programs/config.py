"""
domain/programs/config.py
Typed configuration models + loaders for the CanonicalProgram foundation
(Phase P1).

Configuration is kept OUTSIDE the canonical records: freshness windows,
schema-version support, controlled-vocabulary version, projection version, and
the reserved experiment vector-store identity all live in committed JSON and are
loaded into these typed models. Nothing here fetches, crawls, embeds, or
initializes a vector store.

Reusability: the typed models are constructable directly (no filesystem needed),
and every loader accepts an injectable `config_dir`. The default location is a
convenience fallback for this repository only — it is never a hard requirement,
so the package carries no hidden dependency on this repo's layout.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from domain.programs.enums import Volatility

# Convenience default only — callers may pass any config_dir to the loaders.
_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "masters"


class SchemaConfig(BaseModel):
    current_schema_version: str
    supported_schema_versions: list[str]


class FreshnessPolicy(BaseModel):
    """Maps a volatility class to a re-verification window in days.

    Values are policy-configurable placeholders; they are intentionally not
    hardcoded inside records or the validator. The validator receives a
    FreshnessPolicy instance (injected in tests) rather than reading day
    values itself.
    """

    stable_days: int
    moderate_days: int
    time_sensitive_days: int

    def window_days(self, volatility: Volatility) -> int:
        if volatility == Volatility.STABLE:
            return self.stable_days
        if volatility == Volatility.MODERATE:
            return self.moderate_days
        return self.time_sensitive_days


class VocabularyManifest(BaseModel):
    """Minimal shared controlled-vocabulary shell. Not populated in P1."""

    vocab_version: str
    interest_tags: list[str] = Field(default_factory=list)
    academic_background_tags: list[str] = Field(default_factory=list)
    career_goal_tags: list[str] = Field(default_factory=list)


class ProjectionConfig(BaseModel):
    projection_version: str


class ExperimentIdentity(BaseModel):
    """Reserved identity for the frozen experiment vector store. Recorded only;
    the store is NOT created or initialized in this phase."""

    collection_name: str
    persist_dir: str


# ---------------------------------------------------------------------------
# Loaders — injectable config_dir; defaults to config/masters/ for convenience.
# ---------------------------------------------------------------------------

def _load_json(name: str, config_dir: Optional[Path]) -> dict:
    base = config_dir if config_dir is not None else _DEFAULT_CONFIG_DIR
    return json.loads((base / name).read_text(encoding="utf-8"))


def load_schema_config(config_dir: Optional[Path] = None) -> SchemaConfig:
    return SchemaConfig.model_validate(_load_json("schema.json", config_dir))


def load_freshness_policy(config_dir: Optional[Path] = None) -> FreshnessPolicy:
    return FreshnessPolicy.model_validate(_load_json("freshness_policy.json", config_dir))


def load_vocabulary_manifest(config_dir: Optional[Path] = None) -> VocabularyManifest:
    return VocabularyManifest.model_validate(_load_json("vocabulary.json", config_dir))


def load_projection_config(config_dir: Optional[Path] = None) -> ProjectionConfig:
    return ProjectionConfig.model_validate(_load_json("projection.json", config_dir))


def load_experiment_identity(config_dir: Optional[Path] = None) -> ExperimentIdentity:
    return ExperimentIdentity.model_validate(_load_json("experiment_identity.json", config_dir))
