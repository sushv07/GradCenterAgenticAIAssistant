"""
telemetry/metrics.py
Prometheus metric definitions and recording helpers (Phase 1).

Two families of metrics, matching the two instrumentation seams:

  HTTP (transport)   — recorded by telemetry.middleware.MetricsMiddleware.
                       RED signals for the FastAPI edge: rate, errors, duration,
                       plus an in-flight gauge for saturation.

  Pipeline (domain)  — recorded by backend.entrypoint.handle_user_query at its
                       existing completion point. This is the universal seam
                       every caller passes through (HTTP, Streamlit, evals, CLI),
                       so pipeline metrics count real domain work regardless of
                       transport, and carry the `route` label that HTTP cannot
                       see (route lives in the response body, not the URL).

All instruments live on prometheus_client's default REGISTRY, which the
/metrics endpoint serialises. Labels are kept strictly low-cardinality — see the
package docstring for why high-cardinality detail stays in logs/traces.
"""
from __future__ import annotations

from typing import Optional

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Latency buckets — tuned for THIS system, not web defaults.
# ---------------------------------------------------------------------------
# A /query request runs an agentic RAG pipeline ending in a local Qwen model via
# Ollama; real requests routinely take whole seconds. Default millisecond buckets
# would bucket almost everything into +Inf and make percentiles meaningless.
# Range spans a fast deterministic route (welcome/health, ~ms) through a slow
# multi-agent composite LLM turn (tens of seconds).
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)


# ---------------------------------------------------------------------------
# HTTP (transport) metrics — one label set, all bounded.
# ---------------------------------------------------------------------------
#   route        — the matched route TEMPLATE (e.g. "/query"), never a raw URL,
#                  so path parameters can never explode cardinality.
#   status_class — "2xx"/"4xx"/"5xx", not the exact code, to keep series small.
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled, by method, matched route, and status class.",
    ["method", "route", "status_class"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request wall-clock latency in seconds, by method and matched route.",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)

HTTP_ERRORS = Counter(
    "http_request_errors_total",
    "HTTP requests that ended in a client (4xx) or server (5xx) error, or an "
    "unhandled exception (recorded as 5xx).",
    ["method", "route", "status_class"],
)

HTTP_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Number of HTTP requests currently being processed (saturation signal).",
)


# ---------------------------------------------------------------------------
# Pipeline (domain) metrics — recorded once per handle_user_query call.
# ---------------------------------------------------------------------------
#   route   — the domain route the request resolved to (welcome, advisor,
#             application, discovery, composite, error, ...). Bounded (~12).
#   outcome — "ok" | "error".
PIPELINE_REQUESTS = Counter(
    "pipeline_requests_total",
    "Total domain pipeline requests processed by handle_user_query, across all "
    "callers (HTTP, Streamlit, evals), by resolved route and outcome.",
    ["route", "outcome"],
)

PIPELINE_REQUEST_DURATION = Histogram(
    "pipeline_request_duration_seconds",
    "End-to-end pipeline latency in seconds (routing + retrieval + LLM + "
    "response building), by resolved route.",
    ["route"],
    buckets=_LATENCY_BUCKETS,
)

PIPELINE_ERRORS = Counter(
    "pipeline_errors_total",
    "Pipeline requests that produced an error response, by resolved route.",
    ["route"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def status_class(status_code: int) -> str:
    """Map an HTTP status code to its class label ("2xx"/"4xx"/"5xx")."""
    return f"{status_code // 100}xx"


def record_http(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    """Record one completed HTTP request. Called by the metrics middleware."""
    sc = status_class(status_code)
    HTTP_REQUESTS.labels(method=method, route=route, status_class=sc).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)
    if status_code >= 400:
        HTTP_ERRORS.labels(method=method, route=route, status_class=sc).inc()


def record_pipeline(route: str, had_error: bool, duration_seconds: float) -> None:
    """Record one completed domain pipeline request. Called by
    handle_user_query at its existing completion point. `route` is normalised to
    "unknown" when empty so the label is always present.

    NOTE: route DISTRIBUTION (route counts) is read from this metric's `route`
    label — Phase 3 deliberately does NOT add a separate ai_route_selected_total,
    to avoid a duplicate series."""
    route = route or "unknown"
    outcome = "error" if had_error else "ok"
    PIPELINE_REQUESTS.labels(route=route, outcome=outcome).inc()
    PIPELINE_REQUEST_DURATION.labels(route=route).observe(duration_seconds)
    if had_error:
        PIPELINE_ERRORS.labels(route=route).inc()


# ═══════════════════════════════════════════════════════════════════════════
# AI-pipeline metrics (Phase 3) — observe the reasoning/retrieval behavior of
# the assistant, not just the infrastructure. All labels are bounded (see the
# Phase 3 docs). High-cardinality detail (query text, session, program_id,
# prompt text) stays in logs/trace attributes, never here.
# ═══════════════════════════════════════════════════════════════════════════

# Score buckets in [0, 1] — cosine relevance / retrieval scores.
_SCORE_BUCKETS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
# Small-count buckets — retrieved-doc / candidate-program counts.
_COUNT_BUCKETS = (0, 1, 2, 3, 5, 8, 13, 21)

# ── Routing ────────────────────────────────────────────────────────────────
AI_ROUTING_DURATION = Histogram(
    "ai_routing_duration_seconds",
    "Latency of the router's decide_route() decision, in seconds.",
    buckets=_LATENCY_BUCKETS,
)

# ── Retrieval (Chroma vector retriever) ──────────────────────────────────────
AI_RETRIEVAL_DURATION = Histogram(
    "ai_retrieval_duration_seconds",
    "Latency of a rag.retriever.retrieve() call, in seconds.",
    buckets=_LATENCY_BUCKETS,
)
AI_RETRIEVAL_REQUESTS = Counter(
    "ai_retrieval_requests_total",
    "Retrieval calls by outcome: hit (>=1 doc cleared threshold), empty "
    "(none cleared → fallback territory), or error.",
    ["outcome"],
)
AI_RETRIEVAL_DOCUMENTS = Histogram(
    "ai_retrieval_documents",
    "Number of documents returned by a retrieval call (post-threshold).",
    buckets=_COUNT_BUCKETS,
)
AI_RETRIEVAL_TOP_SCORE = Histogram(
    "ai_retrieval_top_score",
    "Top (best) relevance score of a retrieval call; 0 when empty.",
    buckets=_SCORE_BUCKETS,
)
AI_RETRIEVAL_SCORE = Histogram(
    "ai_retrieval_score",
    "Relevance score of every returned document (one observation per doc); "
    "the histogram average is the mean relevance.",
    buckets=_SCORE_BUCKETS,
)
AI_RETRIEVAL_SOURCE = Counter(
    "ai_retrieval_source_total",
    "Retrieval calls by the source page_type they targeted/returned.",
    ["page_type"],
)

# ── Recommendation engine ────────────────────────────────────────────────────
AI_RECOMMENDATION_DURATION = Histogram(
    "ai_recommendation_duration_seconds",
    "Latency of select_recommendation() scoring, in seconds.",
    buckets=_LATENCY_BUCKETS,
)
AI_RECOMMENDATION_BEHAVIOR = Counter(
    "ai_recommendation_behavior_total",
    "Recommendation outcomes by behavior (recommend, multi_recommend, "
    "partial_match_with_caveat, clarify, redirect). Clarification frequency is "
    "the clarify share.",
    ["behavior"],
)
AI_RECOMMENDATION_CANDIDATES = Histogram(
    "ai_recommendation_candidates",
    "Number of candidate program_matches surfaced by a recommendation.",
    buckets=_COUNT_BUCKETS,
)
AI_RECOMMENDATION_CONFIDENCE = Counter(
    "ai_recommendation_confidence_total",
    "Recommendation confidence distribution (high, medium, low, none).",
    ["confidence"],
)
AI_RECOMMENDATION_EXPLANATION = Counter(
    "ai_recommendation_explanation_total",
    "Per-program explanation generation outcomes: generated, no_evidence "
    "(skipped, no score_basis), failed (LLM error/invalid), disabled (flag off).",
    ["outcome"],
)

# ── Answer generation ────────────────────────────────────────────────────────
AI_ANSWER_DURATION = Histogram(
    "ai_answer_duration_seconds",
    "Latency of the answer route's retrieve+extract(+synthesis) work, seconds.",
    buckets=_LATENCY_BUCKETS,
)
AI_ANSWER = Counter(
    "ai_answer_total",
    "Answers by answer_type (direct/llm_synthesized/unknown/...) and confidence. "
    "Deterministic-vs-synthesized and insufficient-evidence (answer_type=unknown) "
    "are read from these labels.",
    ["answer_type", "confidence"],
)

# ── LLM (framework — populated whenever synthesis/explanation actually runs) ──
AI_LLM_REQUESTS = Counter(
    "ai_llm_requests_total",
    "LLM invocations by model, operation (synthesis|explanation), and outcome "
    "(success|error).",
    ["model", "operation", "outcome"],
)
AI_LLM_DURATION = Histogram(
    "ai_llm_duration_seconds",
    "LLM generation latency by model and operation, in seconds.",
    ["model", "operation"],
    buckets=_LATENCY_BUCKETS,
)
AI_LLM_ERRORS = Counter(
    "ai_llm_errors_total",
    "LLM failures by operation and error_type (e.g. ConnectionError, "
    "ReadTimeout, ValidationError). Timeout count = error_type ~ *Timeout*.",
    ["operation", "error_type"],
)
AI_RETRY_ATTEMPTS = Counter(
    "ai_retry_attempts_total",
    "Retry attempts made by utils.retry.retry_call, by operation. Exhausted "
    "retries (a proxy for persistent timeouts/outages) are counted separately.",
    ["operation"],
)
AI_RETRY_EXHAUSTED = Counter(
    "ai_retry_exhausted_total",
    "Times retry_call exhausted all attempts and gave up, by operation.",
    ["operation"],
)


# ---------------------------------------------------------------------------
# AI record helpers — thin, never raise, called at existing seams.
# ---------------------------------------------------------------------------

def observe_routing(duration_seconds: float) -> None:
    AI_ROUTING_DURATION.observe(duration_seconds)


def record_retrieval(outcome: str, duration_seconds: float, n_docs: int,
                     top_score: float, scores: Optional[list] = None,
                     page_type: Optional[str] = None) -> None:
    """Record one retrieval call. outcome ∈ {hit, empty, error}."""
    AI_RETRIEVAL_REQUESTS.labels(outcome=outcome).inc()
    AI_RETRIEVAL_DURATION.observe(duration_seconds)
    AI_RETRIEVAL_DOCUMENTS.observe(n_docs)
    AI_RETRIEVAL_TOP_SCORE.observe(top_score or 0.0)
    for s in (scores or []):
        AI_RETRIEVAL_SCORE.observe(s)
    AI_RETRIEVAL_SOURCE.labels(page_type=page_type or "unfiltered").inc()


def record_recommendation(behavior: str, n_candidates: int, confidence: str,
                          duration_seconds: float) -> None:
    AI_RECOMMENDATION_DURATION.observe(duration_seconds)
    AI_RECOMMENDATION_BEHAVIOR.labels(behavior=behavior or "unknown").inc()
    AI_RECOMMENDATION_CANDIDATES.observe(n_candidates)
    AI_RECOMMENDATION_CONFIDENCE.labels(confidence=confidence or "none").inc()


def record_explanation(outcome: str) -> None:
    """outcome ∈ {generated, no_evidence, failed, disabled}."""
    AI_RECOMMENDATION_EXPLANATION.labels(outcome=outcome).inc()


def record_answer(answer_type: str, confidence: str, duration_seconds: float) -> None:
    AI_ANSWER_DURATION.observe(duration_seconds)
    AI_ANSWER.labels(answer_type=answer_type or "unknown",
                     confidence=confidence or "low").inc()


def record_llm(model: str, operation: str, success: bool,
               duration_seconds: float, error_type: Optional[str] = None) -> None:
    """operation ∈ {synthesis, explanation}."""
    outcome = "success" if success else "error"
    AI_LLM_REQUESTS.labels(model=model, operation=operation, outcome=outcome).inc()
    AI_LLM_DURATION.labels(model=model, operation=operation).observe(duration_seconds)
    if not success:
        AI_LLM_ERRORS.labels(operation=operation, error_type=error_type or "Unknown").inc()


def record_retry_attempt(operation: str) -> None:
    AI_RETRY_ATTEMPTS.labels(operation=operation).inc()


def record_retry_exhausted(operation: str) -> None:
    AI_RETRY_EXHAUSTED.labels(operation=operation).inc()
