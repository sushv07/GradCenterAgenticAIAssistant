"""
experiments/rag_vs_finetuning/track_c/prompt_builder.py
Track C grounded prompt construction (Phase P10).

Pure standard library so it imports under BOTH the 3.13 retrieval interpreter and
the 3.9 MLX interpreter. Builds a chat prompt that keeps the fine-tuned assistant
persona (matching the Track B adapter) but injects retrieved context as the
authoritative source, per the P9 finding that knowledge must come from retrieval,
not the adapter. Also provides the abstention detector and citation selection used
by the inference harness.
"""
from __future__ import annotations

from typing import Optional

PROMPT_VERSION = "rag_ft_prompt_v1"

# Exact abstention sentence the model should emit when evidence is insufficient.
# Matches the refusal the Track B adapter was fine-tuned to produce, so the
# adapter's learned behaviour and the grounded instruction agree.
INSUFFICIENT_ANSWER = (
    "I don't have enough information in the provided Graduate Center data to answer that.")

SYSTEM_PROMPT = (
    "You are the CSULB Graduate Center assistant. Answer the user's question USING "
    "ONLY the retrieved Graduate Center context provided in the user message. "
    "Follow these rules strictly:\n"
    "1. Use only facts present in the retrieved context. Never invent, infer, or add "
    "outside knowledge, and never make unsupported claims.\n"
    "2. If the retrieved context does not contain the answer, reply exactly: "
    f"\"{INSUFFICIENT_ANSWER}\" Do not guess.\n"
    "3. Preserve published wording verbatim (deadlines, program names, contacts). Do "
    "not convert dates or invent a year.\n"
    "4. Be concise and factual; do not repeat yourself.")

# Abstention patterns (superset of the sentinel) for robust detection of refusals.
_REFUSAL_PATTERNS = (
    "don't have enough information", "do not have enough information",
    "don't have that information", "do not have that information",
    "not in the provided", "no information available", "cannot answer",
    "can't answer", "unable to answer",
)


def format_context(chunks: list[dict]) -> str:
    """Render retrieved chunks as labelled evidence blocks (deterministic)."""
    if not chunks:
        return "(no relevant context was retrieved)"
    blocks = []
    for c in chunks:
        blocks.append(
            f"[chunk_id={c['chunk_id']} | program={c.get('program_id', '')} | "
            f"section={c.get('section', '')} | similarity={c.get('similarity_score', '')}]\n"
            f"{c.get('content', '')}")
    return "\n\n".join(blocks)


def build_messages(question: str, chunks: list[dict]) -> list[dict]:
    """Chat messages for tokenizer.apply_chat_template (system + grounded user)."""
    user = (
        f"Retrieved context:\n{format_context(chunks)}\n\n"
        f"Question: {question}\n\n"
        "Answer using ONLY the retrieved context above. If the context is "
        f"insufficient, reply exactly: \"{INSUFFICIENT_ANSWER}\"")
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def is_insufficient(answer: str) -> bool:
    low = answer.strip().lower()
    return any(p in low for p in _REFUSAL_PATTERNS)


def select_citations(answer: str, retrieved_chunk_ids: list[str],
                     *, insufficient: Optional[bool] = None) -> list[str]:
    """Citations are drawn from the actually-retrieved evidence (never invented).

    Mirrors Track A policy: when the model abstains, cite nothing; otherwise the
    grounded answer is supported by the retrieved chunks. If the answer explicitly
    names retrieved chunk ids, restrict citations to those; else cite all retrieved.
    """
    if insufficient is None:
        insufficient = is_insufficient(answer)
    if insufficient or not retrieved_chunk_ids:
        return []
    named = [cid for cid in retrieved_chunk_ids if cid in answer]
    return named or list(retrieved_chunk_ids)
