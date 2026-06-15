"""
llm_synthesizer.py
Local LLM synthesis layer for the answer route.

Calls a local Ollama model to synthesize a grounded answer from retrieved
content. Disabled by default (LLM_SYNTHESIS_ENABLED=false).

This module is NOT wired into any production code path in Phase 10B.
Phase 10C will integrate it into orchestrator._run_answer().

Public API
----------
    synthesize_answer(query, retrieved_answer, source_file, source_url=None)
        -> {"answer": str, "confidence": "high"|"medium"|"low"} | None

Configuration (environment variables)
--------------------------------------
    LLM_SYNTHESIS_ENABLED   bool   default: false
    OLLAMA_BASE_URL         str    default: http://localhost:11434
    LLM_SYNTHESIS_MODEL     str    default: qwen2.5:7b-instruct
    LLM_SYNTHESIS_TIMEOUT_S int    default: 30

Observability
-------------
    llm.synthesis.start  — emitted before the Ollama call
    llm.synthesis.result — emitted on success
    llm.synthesis.error  — emitted on any failure (network, validation, etc.)
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests

from gradcenter_logging import emit


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENABLED  = os.getenv("LLM_SYNTHESIS_ENABLED", "false").lower() == "true"
_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
_MODEL    = os.getenv("LLM_SYNTHESIS_MODEL", "qwen2.5:7b-instruct")
_TIMEOUT  = int(os.getenv("LLM_SYNTHESIS_TIMEOUT_S", "30"))

_CHAT_URL         = f"{_BASE_URL}/api/chat"
_VALID_CONFIDENCE = frozenset({"high", "medium", "low"})


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a CSULB Graduate Center assistant. Your role is to TRANSFORM retrieved \
information into a clear, student-friendly response.

You are NOT a summarizer. Do not compress or omit important details.

Priority order: Accuracy > Completeness > Source Fidelity > Readability > Brevity

Use ONLY facts present in the retrieved content below. Never add or invent information.

MUST PRESERVE — include all of these when found in the retrieved content:
- Scholarship, fellowship, grant, and program names (exact names, no abbreviation)
- Dollar amounts and funding values (every amount listed)
- Deadlines and dates (exact values — do not paraphrase or round)
- Eligibility requirements (all criteria listed, not just the first)
- Contact details: email addresses, phone numbers, office locations
- Advisor names and titles
- Office names and room numbers
- Step-by-step instructions (all steps, in original order)
- URLs already present in the retrieved content (copy exactly — never modify)
- Lists of multiple items — always use bullet points; never collapse into one sentence

NEVER:
- Invent URLs, deadlines, names, dollar amounts, or requirements
- Omit details solely for brevity
- Merge multiple distinct items into a single compressed sentence

FORMATTING:
- Use bullet points (- item) for multiple items, options, or criteria
- Use short labels (Eligibility:, Contact:, Deadline:) to group related information
- Use numbered steps for sequential instructions
- Use plain prose only when the answer is a single fact

If the retrieved content does not answer the question, state what IS available \
and set confidence to low.

Respond with valid JSON in exactly this format, nothing else:
{"answer": "your full response — use newlines and bullet points for clarity", "confidence": "high"}

confidence values:
- "high":   retrieved content directly and completely answers the question
- "medium": content partially addresses the question
- "low":    content is related but does not directly answer the question\
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize_answer(
    query: str,
    retrieved_answer: str | dict,
    source_file: str,
    source_url: Optional[str] = None,
) -> Optional[dict]:
    """
    Synthesize a grounded answer from retrieved content using a local LLM.

    Returns {"answer": str, "confidence": "high"|"medium"|"low"} on success.
    Returns None on any failure — never raises into the caller.

    source_file and source_url are accepted for Phase 10C API compatibility
    but are not passed to the LLM. Source attribution remains the
    orchestrator's responsibility.
    """
    if not _ENABLED:
        return None

    emit("llm.synthesis.start", model=_MODEL)
    t0 = time.monotonic()

    try:
        content = _call_ollama(query, retrieved_answer)
    except Exception as exc:
        emit("llm.synthesis.error", level="ERROR",
             model=_MODEL, error=str(exc))
        return None

    result = _validate(content)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    if result is None:
        emit("llm.synthesis.error", level="WARNING",
             model=_MODEL, error="response validation failed")
        return None

    emit("llm.synthesis.result",
         model=_MODEL,
         confidence=result["confidence"],
         elapsed_ms=elapsed_ms)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context(retrieved_answer: str | dict) -> str:
    """Serialize retrieved_answer into prompt-ready text."""
    if isinstance(retrieved_answer, dict):
        return json.dumps(retrieved_answer, indent=2, ensure_ascii=False)
    return str(retrieved_answer)


def _call_ollama(query: str, retrieved_answer: str | dict) -> str:
    """
    POST to Ollama /api/chat and return the raw content string.

    Raises on any HTTP or network failure — caller is responsible for catching.
    """
    context      = _build_context(retrieved_answer)
    user_message = f"Retrieved content:\n{context}\n\nQuestion: {query}"

    payload = {
        "model":    _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "format":  "json",
        "stream":  False,
        "options": {"temperature": 0},
    }

    resp = requests.post(_CHAT_URL, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")


def _validate(content: str) -> Optional[dict]:
    """
    Parse and validate the model response.

    Returns {"answer": str, "confidence": str} on success, None on any
    validation failure. Pure — no emit calls.
    """
    if not content or not content.strip():
        return None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None

    answer     = parsed.get("answer", "")
    confidence = parsed.get("confidence", "")

    if not isinstance(answer, str) or not answer.strip():
        return None

    if confidence not in _VALID_CONFIDENCE:
        return None

    return {"answer": answer.strip(), "confidence": confidence}
