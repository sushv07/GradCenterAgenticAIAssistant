"""
experiments/rag_vs_finetuning/track_a/prompt.py
Deterministic, versioned prompt construction for Track A (Phase P7).

The prompt grounds the base model strictly in retrieved context: answer only
from the provided evidence, never fabricate, preserve published deadline wording
verbatim, cite the evidence chunks, and explicitly say when evidence is
insufficient. No answer-set / eval tuning is done here.
"""
from __future__ import annotations

from experiments.rag_vs_finetuning.track_a.models import RetrievalResult

PROMPT_VERSION = "rag_prompt_v1"

_SYSTEM = (
    "You are the CSULB Graduate Center assistant. Answer the user's question "
    "USING ONLY the retrieved context below. Follow these rules strictly:\n"
    "1. Use only facts present in the retrieved context. Never invent, infer, or "
    "add outside knowledge.\n"
    "2. If the context does not contain the answer, reply exactly: "
    "\"I don't have that information in the provided sources.\" Do not guess.\n"
    "3. Preserve published deadline wording verbatim (e.g. 'February 15', "
    "'Not Accepting'). Do not convert dates or invent a year.\n"
    "4. Distinguish what is stated from what is absent: if a fact is not in the "
    "context, treat it as unknown/source-missing and say it is not available.\n"
    "5. Cite the evidence you used by referencing the program and section (each "
    "context item is labelled with its chunk id, program, and section).\n"
    "6. Be concise and factual."
)

_INSUFFICIENT_ANSWER = "I don't have that information in the provided sources."


def _format_context(result: RetrievalResult) -> str:
    if not result.retrieved_chunks:
        return "(no relevant context was retrieved)"
    blocks = []
    for c in result.retrieved_chunks:
        blocks.append(
            f"[chunk_id={c.chunk_id} | program={c.program_id} | section={c.section} "
            f"| similarity={c.similarity_score}]\n{c.content}")
    return "\n\n".join(blocks)


def build_prompt(question: str, result: RetrievalResult) -> tuple[str, str, str]:
    """Return (system, user, full_text). Deterministic given the same inputs."""
    user = (
        f"Retrieved context:\n{_format_context(result)}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the retrieved context. If the context is insufficient, "
        f"say: \"{_INSUFFICIENT_ANSWER}\"")
    full = f"<<SYSTEM>>\n{_SYSTEM}\n\n<<USER>>\n{user}"
    return _SYSTEM, user, full
