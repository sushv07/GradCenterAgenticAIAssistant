"""
retrieval/utils.py
Shared tokenization utility for the CSULB Grad Center retrieval layer.

Public API
----------
    tokenize(text, stop_words=frozenset()) -> set[str]

        Lowercase, extract [a-z0-9]+ tokens, optionally filter stop_words.

        Each calling module keeps its own stop_words constant and passes it
        as an argument.  The default (no filtering) preserves query_handler
        behavior unchanged.  Do NOT import a shared global stop-word list
        here — intentional divergence between backends is load-bearing.
"""

from __future__ import annotations

import re


def tokenize(text: str, stop_words: frozenset[str] = frozenset()) -> set[str]:
    """
    Return the set of lowercase alphanumeric tokens in text, minus stop_words.

    Args:
        text:       Input string (any case, any punctuation).
        stop_words: Caller-owned set of tokens to exclude.  Pass the calling
                    module's private constant; do not share stop-word sets
                    across modules.  Defaults to no filtering.

    Returns:
        set[str] — lowercase word/digit token strings.
    """
    return set(re.findall(r"[a-z0-9]+", text.lower())) - stop_words
