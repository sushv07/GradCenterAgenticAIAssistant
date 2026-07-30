"""
llm_synthesizer.py
Local LLM synthesis layer for the answer route.

Calls a local Ollama model to synthesize a grounded answer from retrieved
content. Disabled by default (LLM_SYNTHESIS_ENABLED=false).

Wired into orchestrator.py:_run_answer() (the "answer" route only).

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

Phase 7C grounding improvements
--------------------------------
    Two real gaps found by the Phase 7C grounding review, both fixed here:

    1. source_url was accepted but never actually used — the LLM had no
       signal about which of potentially several URLs inside the retrieved
       content was the deterministically-resolved canonical source.
       _build_context() now threads it through as "canonical_source_url".
       This does NOT change what the user sees as the response's source —
       orchestrator.py still always uses the deterministic result["source_url"]
       for that, regardless of what the LLM does with this hint.

    2. The prompt asked the model not to invent URLs, but nothing enforced
       it. _validate() now extracts every URL the model's answer contains
       and fails validation (falls back to the deterministic answer,
       exactly like any other validation failure) if any of them did not
       appear in the retrieved content. A prompt instruction is a request;
       this check is a guarantee.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

import requests

from gradcenter_logging import emit
from telemetry import metrics
from telemetry.tracing import set_attributes, span
from utils.retry import retry_call
from prompts.loader import load_prompt


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
# Phase 7E: extracted to prompts/grounded_answers/synthesis_v1.md — wording
# unchanged (verified byte-identical at extraction time). Loading is cached
# (prompts/loader.py), so this module-level read costs nothing beyond the
# first import.
#
# Phase 10: the active grounded-answer prompt is config-selectable via
# GROUNDED_ANSWER_PROMPT (a registered prompt name). Default is the v1 prompt,
# so deployed behavior and every existing test are unchanged until an operator
# opts into the v2 candidate (grounded_answer_synthesis_v2) — matching the
# LLM_SYNTHESIS_ENABLED / MASTERS_INGESTION_ENABLED toggle idiom. Only the
# prompt text changes; the deterministic URL-fidelity guard below is untouched.

_ACTIVE_PROMPT_NAME = os.getenv("GROUNDED_ANSWER_PROMPT", "grounded_answer_synthesis")
_SYSTEM_PROMPT = load_prompt(_ACTIVE_PROMPT_NAME)


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

    source_file is accepted for API symmetry with the orchestrator's call
    site but is not passed to the LLM. source_url IS used (Phase 7C) as a
    grounding hint — see module docstring. Neither parameter changes what
    the final response displays as its source; that remains the
    orchestrator's deterministic responsibility regardless of LLM output.
    """
    if not _ENABLED:
        return None

    emit("llm.synthesis.start", model=_MODEL)
    t0 = time.monotonic()

    context = _build_context(retrieved_answer, source_url)

    # llm.generate — the local Ollama inference call. This is the dominant-
    # latency span in most requests; isolating it is the single most useful
    # part of the trace for diagnosing slow responses.
    with span("llm.generate", attributes={"llm.model": _MODEL,
                                          "prompt.version": _ACTIVE_PROMPT_NAME}):
        try:
            content = _call_ollama(query, context)
        except Exception as exc:
            metrics.record_llm(_MODEL, "synthesis", False,
                               time.monotonic() - t0, type(exc).__name__)
            emit("llm.synthesis.error", level="ERROR",
                 model=_MODEL, error=str(exc))
            return None

    source_urls = _extract_urls(context)
    result = _validate(content, source_urls)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    if result is None:
        metrics.record_llm(_MODEL, "synthesis", False,
                           time.monotonic() - t0, "ValidationError")
        emit("llm.synthesis.error", level="WARNING",
             model=_MODEL, error="response validation failed")
        return None

    metrics.record_llm(_MODEL, "synthesis", True, time.monotonic() - t0)
    emit("llm.synthesis.result",
         model=_MODEL,
         confidence=result["confidence"],
         elapsed_ms=elapsed_ms)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context(retrieved_answer: str | dict, source_url: Optional[str] = None) -> str:
    """
    Serialize retrieved_answer into prompt-ready text.

    Phase 7C: when source_url is known (the deterministic answer_agent's
    own resolved citation), it's threaded in as "canonical_source_url" so
    the model has an explicit signal for which source is authoritative when
    the retrieved content spans multiple files/sections each with their own
    URL. This is a grounding hint only — it does not change what the final
    response displays as its source.
    """
    if isinstance(retrieved_answer, dict):
        payload: dict = dict(retrieved_answer)
    else:
        payload = {"retrieved_text": str(retrieved_answer)}
    if source_url:
        payload = {"canonical_source_url": source_url, **payload}
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _call_ollama(query: str, context: str) -> str:
    """
    POST to Ollama /api/chat and return the raw content string.

    Raises on any HTTP or network failure — caller is responsible for catching.
    Phase 6B: connection/timeout failures (Ollama briefly unavailable, slow
    to respond) are retried via utils.retry.retry_call before giving up;
    an HTTP error response (model not found, bad request) is not retried —
    see utils/retry.py's module docstring for why.
    """
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

    def _post() -> requests.Response:
        resp = requests.post(_CHAT_URL, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp

    resp = retry_call(_post, operation="llm_synthesis.ollama_post")
    return resp.json().get("message", {}).get("content", "")


_URL_PATTERN = re.compile(r'https?://[^\s\)\]"\'<>]+')


def _extract_urls(text: str) -> set[str]:
    """
    Return every http(s) URL found in text, as a set.

    Trailing sentence punctuation (.,;:!?) is stripped from each match.
    Without this, a URL the model correctly copied verbatim but placed at
    the end of a sentence ("...details: https://example.com/page.") would
    capture the trailing period as part of the URL, fail to match the same
    URL as it appears in the source JSON (which has no trailing period),
    and be incorrectly flagged as a fabricated citation — rejecting a
    perfectly legitimate, correctly-grounded answer.
    """
    return {match.rstrip(".,;:!?") for match in _URL_PATTERN.findall(text)}


def _validate(content: str, source_urls: set[str]) -> Optional[dict]:
    """
    Parse and validate the model response.

    Returns {"answer": str, "confidence": str} on success, None on any
    validation failure. Pure — no emit calls.

    Phase 7C citation-fidelity check: source_urls is every URL that
    appeared in the retrieved content handed to the model. If the model's
    answer contains a URL NOT in that set, it fabricated a citation —
    treated as a validation failure exactly like a malformed response,
    falling back to the deterministic answer.
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

    fabricated_urls = _extract_urls(answer) - source_urls
    if fabricated_urls:
        return None

    return {"answer": answer.strip(), "confidence": confidence}
