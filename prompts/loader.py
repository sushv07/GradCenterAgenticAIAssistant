"""
prompts/loader.py
Phase 7E — lightweight prompt loader.

Requirements (Step 3): load by name, cache loaded prompts, raise a clear
error for a missing prompt, no external dependencies, simple implementation.
"""
from __future__ import annotations

from functools import lru_cache

from config.settings import PROMPTS_DIR
from prompts.registry import PromptMetadata, get_prompt_metadata


class PromptNotFoundError(KeyError):
    """Raised when a prompt name isn't registered, or its file is missing."""


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """
    Return the raw text content of the prompt registered under `name`.

    Cached after the first successful load — calling this repeatedly for
    the same name does not re-read the file. Raises PromptNotFoundError
    (a KeyError subclass) for an unregistered name or a missing file, with
    a message naming every valid prompt so the caller can self-correct.
    """
    try:
        meta = get_prompt_metadata(name)
    except KeyError as exc:
        raise PromptNotFoundError(str(exc)) from None

    path = PROMPTS_DIR / meta.relative_path
    if not path.exists():
        raise PromptNotFoundError(
            f"Prompt file missing for {name!r} (version {meta.version}): {path}"
        )
    return path.read_text(encoding="utf-8")


def get_prompt_version(name: str) -> str:
    """Return the registered version string for a prompt name (e.g. "v1")."""
    return get_prompt_metadata(name).version


def get_prompt_info(name: str) -> PromptMetadata:
    """Return the full PromptMetadata record for a prompt name."""
    return get_prompt_metadata(name)
