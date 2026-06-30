"""
prompts/registry.py
Phase 7E — prompt metadata registry.

Plain Python dict, not a database — adding a new prompt version means
adding a new .md file plus a new (or updated) entry here, the same way
adding a config value means adding a line to config/settings.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptMetadata:
    name:           str   # logical prompt name, used as the load_prompt() key
    version:        str   # e.g. "v1" — bumped whenever wording changes meaningfully
    description:    str
    intended_model: str   # the model this prompt was authored/tuned for
    relative_path:  str   # path under config.settings.PROMPTS_DIR


_REGISTRY: dict[str, PromptMetadata] = {
    "recommendation_explanation": PromptMetadata(
        name="recommendation_explanation",
        version="v1",
        description=(
            "Explains why ONE specific deterministic recommendation matched a "
            "student, using only the structured evidence already computed by "
            "agents/recommendation_engine.py — never decides or ranks."
        ),
        intended_model="qwen2.5:7b-instruct",
        relative_path="recommendation/explanation_v1.md",
    ),
    "grounded_answer_synthesis": PromptMetadata(
        name="grounded_answer_synthesis",
        version="v1",
        description=(
            "Synthesizes a grounded answer for the 'answer' route from "
            "retrieved content only — never from the model's own knowledge."
        ),
        intended_model="qwen2.5:7b-instruct",
        relative_path="grounded_answers/synthesis_v1.md",
    ),
}


def get_prompt_metadata(name: str) -> PromptMetadata:
    """Return the PromptMetadata for a registered prompt name."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown prompt {name!r}. Known prompts: {sorted(_REGISTRY)}"
        ) from None


def list_prompt_names() -> list[str]:
    return sorted(_REGISTRY)
