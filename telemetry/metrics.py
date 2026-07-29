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
    "unknown" when empty so the label is always present."""
    route = route or "unknown"
    outcome = "error" if had_error else "ok"
    PIPELINE_REQUESTS.labels(route=route, outcome=outcome).inc()
    PIPELINE_REQUEST_DURATION.labels(route=route).observe(duration_seconds)
    if had_error:
        PIPELINE_ERRORS.labels(route=route).inc()
