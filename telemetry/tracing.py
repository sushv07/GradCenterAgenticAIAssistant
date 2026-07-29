"""
telemetry/tracing.py
OpenTelemetry distributed tracing (Phase 2).

Design contract — identical in spirit to Phase 1's metrics:
    * Additive and safe. Importing this module never requires OpenTelemetry to
      be installed (the SDK import is guarded); calling span() with tracing
      uninitialised is a near-zero-cost no-op; a failed exporter never raises
      into a request. The application behaves identically with tracing off.
    * One correlation source. trace_id/span_id reach the NDJSON logs through a
      single enricher registered with gradcenter_logging — the logging module
      itself stays free of any OpenTelemetry dependency. request_id and
      session_id remain the existing ContextVars; OpenTelemetry context also
      rides on contextvars, so span nesting propagates automatically across the
      existing call graph without threading anything by hand.
    * Manual, semantic instrumentation. Spans are created only at the meaningful
      pipeline stages (see the seam call sites), never for helper functions and
      never via blanket auto-instrumentation, so a trace reads like the request
      lifecycle rather than framework noise.

Enablement:
    Tracing is OFF unless OTEL_TRACES_ENABLED is truthy (so tests and the
    default dev/Streamlit paths incur no exporter and no behavior change). When
    enabled, spans export via OTLP/HTTP to the OpenTelemetry Collector; the
    endpoint follows the standard OTEL_EXPORTER_OTLP_ENDPOINT env var.
"""
from __future__ import annotations

import functools
import os
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

try:  # OpenTelemetry is a backend-only dependency; degrade cleanly if absent.
    from opentelemetry import trace as _otel_trace
    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001
    _OTEL_AVAILABLE = False

_TRACER_NAME = "gradcenter"
_INITIALISED = False


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    """Whether tracing export is switched on for this process."""
    return _truthy("OTEL_TRACES_ENABLED")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_tracing(*, span_exporter=None, force: bool = False) -> bool:
    """Initialise the global tracer provider once. Returns True if tracing is
    now active, False if it was skipped (disabled/unavailable) or already set up.

    Called once from the service entry point (api/app.py). `span_exporter` and
    `force` exist for tests, which inject an in-memory exporter and bypass the
    env gate to capture spans without a running Collector. Any failure here is
    swallowed — tracing must never prevent the app from starting.
    """
    global _INITIALISED
    if _INITIALISED:
        return True
    if not _OTEL_AVAILABLE:
        return False
    if not (force or is_enabled()):
        return False

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )

        resource = Resource.create({
            "service.name":            os.environ.get("OTEL_SERVICE_NAME", "gradcenter-ai"),
            "service.version":         os.environ.get("OTEL_SERVICE_VERSION", "1.0.0"),
            "deployment.environment":  os.environ.get("OTEL_ENV", "local"),
        })
        provider = TracerProvider(resource=resource)

        if span_exporter is not None:
            # Tests: synchronous processor so spans are readable immediately.
            provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        else:
            # Production: OTLP/HTTP → Collector, exported on a background thread
            # (BatchSpanProcessor) so export latency never touches the request
            # path and a slow/unavailable Collector cannot block a response.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

        _otel_trace.set_tracer_provider(provider)
        _register_log_correlation()
        _INITIALISED = True
        return True
    except Exception:  # noqa: BLE001 — tracing setup must never break startup
        return False


# ---------------------------------------------------------------------------
# Span helper
# ---------------------------------------------------------------------------

@contextmanager
def span(name: str, attributes: Optional[dict] = None) -> Iterator[object]:
    """Start a span as the current span for the duration of the block.

    Nesting is automatic: any span opened while another is current becomes its
    child, because OpenTelemetry propagates the active span via contextvars
    across the existing call graph. When OpenTelemetry is unavailable or tracing
    is uninitialised, this yields a no-op (an API tracer returns a
    non-recording span) with negligible cost.

    On an unhandled exception the span is marked with error status and the
    exception is recorded, then re-raised — instrumentation never suppresses it.
    """
    if not _OTEL_AVAILABLE:
        yield None
        return

    tracer = _otel_trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name) as sp:
        _set_attributes(sp, attributes)
        try:
            yield sp
        except Exception as exc:  # noqa: BLE001 — annotate then re-raise
            try:
                from opentelemetry.trace import Status, StatusCode
                sp.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                sp.record_exception(exc)
            except Exception:  # noqa: BLE001
                pass
            raise


def traced(name: str) -> Callable:
    """Decorator form of span() for whole-function seams (e.g. the root
    pipeline span on handle_user_query). Dynamic attributes learned inside the
    function are added with set_attributes(). Preserves the wrapped function's
    identity so existing `from ... import handle_user_query` call sites are
    unaffected."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with span(name):
                return fn(*args, **kwargs)
        return wrapper
    return decorator


def set_attributes(**attributes) -> None:
    """Attach attributes to the current span, if one is recording. Convenience
    for seams that learn attribute values partway through their block (e.g. the
    resolved route). Safe no-op when tracing is off."""
    if not _OTEL_AVAILABLE:
        return
    _set_attributes(_otel_trace.get_current_span(), attributes)


def _set_attributes(sp, attributes: Optional[dict]) -> None:
    if not attributes or sp is None:
        return
    for key, value in attributes.items():
        if value is not None:
            try:
                sp.set_attribute(key, value)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Log ↔ trace correlation
# ---------------------------------------------------------------------------

def current_trace_ids() -> dict:
    """Return {"trace_id", "span_id"} (zero-padded hex, W3C format) for the
    active span, or {} when there is no valid recording span. This is the single
    place trace correlation is computed; gradcenter_logging merges it into every
    event via the enricher registered in init_tracing()."""
    if not _OTEL_AVAILABLE:
        return {}
    ctx = _otel_trace.get_current_span().get_span_context()
    if not ctx or not ctx.is_valid:
        return {}
    return {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id":  format(ctx.span_id, "016x"),
    }


def _register_log_correlation() -> None:
    # Imported here (not at module top) so telemetry.tracing carries no import
    # coupling to the logging module until tracing is actually initialised.
    import gradcenter_logging
    gradcenter_logging.register_log_enricher(current_trace_ids)
