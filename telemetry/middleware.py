"""
telemetry/middleware.py
ASGI middleware that records HTTP-transport RED metrics (Phase 1).

Scope is deliberately narrow — this layer knows only about the HTTP edge:
request count, error count, latency, and in-flight concurrency. Domain concerns
(which route the request resolved to, retrieval, the LLM) are NOT this layer's
job; those are recorded at the pipeline seam (handle_user_query) and, from
Phase 2, as spans. Keeping the two seams separate is the core observability
design decision: transport metrics here, domain metrics/traces there.

Why BaseHTTPMiddleware:
    It is the simplest correct way to wrap request/response for cross-cutting
    timing and is trivially explainable in review. The app has no streaming
    endpoints, so BaseHTTPMiddleware's known streaming caveats do not apply.

The `/metrics` endpoint is excluded from measurement so Prometheus scrapes do
not inflate the very metrics they read.
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from telemetry import metrics

# Paths that must never be measured (the scrape endpoint itself).
_EXCLUDED_PATHS = frozenset({"/metrics"})


def _route_label(request: Request) -> str:
    """Return the matched route TEMPLATE (e.g. "/query"), not the raw URL.

    Starlette populates scope["route"] during routing, so after the app has run
    we can read the template — this bounds cardinality regardless of path
    parameters or arbitrary 404 URLs. Unmatched requests get a single "unmatched"
    label instead of leaking the raw path.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Time every HTTP request and record transport metrics. Never alters the
    response and never suppresses an exception."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        method = request.method
        metrics.HTTP_IN_FLIGHT.inc()
        start = time.perf_counter()
        # Default to 500: if call_next raises, the request failed as a server
        # error from the client's perspective. The exception is never swallowed —
        # it propagates out of `finally`, so FastAPI's default 500 handling is
        # completely unchanged; we only observe it on the way out.
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            metrics.record_http(method, _route_label(request), status_code,
                                time.perf_counter() - start)
            metrics.HTTP_IN_FLIGHT.dec()
