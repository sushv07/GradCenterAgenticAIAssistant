"""
utils/retry.py
Phase 6B — small, dependency-free retry helper for transient I/O failures.

Problem this solves:
    Three real external HTTP calls sit in the live request path with zero
    retry: agents/llm_synthesizer.py's call to a local Ollama server,
    retrieval/faq_rag_module.py's fetch of the CSULB FAQ page, and
    retrieval/admissions_rag.py's fetch of CSULB admissions pages. Each
    already degrades gracefully on failure (returns None/[]/"" rather than
    crashing — Phase 6A), but a single transient network blip (a momentary
    connection reset, a slow DNS lookup) currently means giving up
    immediately rather than trying again, even though a retry has a
    realistic chance of succeeding.

What this module deliberately does NOT do (Phase 6B non-goals):
    - It is not a general-purpose retry framework — no decorators-with-
      configurable-everything, no circuit breaker, no jitter, no async
      support. One function, retry_call(), used at exactly the call sites
      the Phase 6B audit identified as safe to retry.
    - It does not retry deterministic logic (routing, recommendation
      scoring, taxonomy loading, response building) — those are either
      already excluded by retryable_exceptions (a ValueError/KeyError/
      FileNotFoundError is never in that tuple) or simply never call this
      function at all.
    - It does not retry on HTTP error responses (4xx/5xx) — only on
      requests.exceptions.ConnectionError and .Timeout, i.e. failures where
      no response was received at all. A 4xx means the request itself is
      wrong (retrying won't help); a 5xx response is a possible future
      enhancement (see ARCHITECTURE_ANALYSIS.md's Phase 6B section) but
      conflating "got an error response" with "got no response" was judged
      more complexity than this phase's audit justified.
    - It does not introduce a third-party retry library (tenacity, backoff,
      etc.) — the policy is simple enough (N attempts, exponential delay,
      two specific exception types) that one ~30-line function is clearer
      than a new dependency.

Policy (config/settings.py):
    RETRY_MAX_ATTEMPTS       = 3     (1 initial attempt + 2 retries)
    RETRY_BASE_DELAY_SECONDS = 0.5   (exponential: 0.5s, 1.0s, ...)

Usage:
    from utils.retry import retry_call

    resp = retry_call(
        lambda: requests.get(url, timeout=8),
        operation="admissions_rag.fetch",
    )
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Type, TypeVar

import requests

from gradcenter_logging import emit
from telemetry import metrics
from config.settings import RETRY_MAX_ATTEMPTS, RETRY_BASE_DELAY_SECONDS

T = TypeVar("T")

# Only failures where no response was received at all — see module
# docstring for why HTTP error responses (4xx/5xx) are excluded.
RETRYABLE_EXCEPTIONS: tuple[Type[BaseException], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def retry_call(
    fn: Callable[[], T],
    *,
    operation: str,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY_SECONDS,
    retryable_exceptions: tuple[Type[BaseException], ...] = RETRYABLE_EXCEPTIONS,
) -> T:
    """
    Call fn(), retrying with exponential backoff on retryable_exceptions.

    A non-retryable exception (anything not in retryable_exceptions)
    propagates immediately on its first occurrence — no retry, no delay.

    If every attempt raises a retryable exception, the last one is
    re-raised after the final attempt (callers that already wrap this in
    their own try/except, e.g. for graceful degradation, see no change in
    behavior other than the added attempts and delay).

    Args:
        fn:            Zero-argument callable to invoke.
        operation:      Short, stable name for log correlation (e.g.
                        "admissions_rag.fetch") — not the URL or any
                        per-call data, so log volume doesn't depend on
                        input.
        max_attempts:   Total attempts including the first (default from
                        config.settings.RETRY_MAX_ATTEMPTS).
        base_delay:     Seconds before the first retry; doubles each
                        subsequent retry (default from
                        config.settings.RETRY_BASE_DELAY_SECONDS).
        retryable_exceptions: Exception types that trigger a retry.
    """
    last_exc: Optional[BaseException] = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            if attempt > 1:
                emit("retry.success", level="INFO",
                     operation=operation, attempt=attempt, max_attempts=max_attempts)
            return result
        except retryable_exceptions as exc:
            last_exc = exc
            metrics.record_retry_attempt(operation)   # Phase 3 AI observability
            emit("retry.attempt", level="WARNING",
                 operation=operation, attempt=attempt, max_attempts=max_attempts,
                 error=str(exc)[:200], error_type=type(exc).__name__)
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))

    metrics.record_retry_exhausted(operation)          # Phase 3 AI observability
    emit("retry.exhausted", level="ERROR",
         operation=operation, max_attempts=max_attempts,
         error=str(last_exc)[:200],
         error_type=type(last_exc).__name__ if last_exc else "")
    assert last_exc is not None  # loop always sets it before falling through
    raise last_exc
