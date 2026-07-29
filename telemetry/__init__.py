"""
telemetry/ — live, in-process observability instrumentation.

This package is the home for the "live" observability signals — Prometheus
metrics (Phase 1) and, later, OpenTelemetry tracing (Phase 2). It is
deliberately separate from obs/, which does OFFLINE, log-derived aggregation
(reconstructing request traces and KB-health reports from the NDJSON stream
after the fact). Different lifetimes, different consumers:

    obs/        — batch/offline analysis over gradcenter.log
    telemetry/  — real-time metrics/traces exported to Prometheus/Tempo

Design contract:
    * Additive and non-invasive — importing or calling anything here must never
      change application behavior or raise into a request path.
    * Bounded cardinality — only low-cardinality labels (route, method, status
      class) are ever attached to metrics. High-cardinality domain detail
      (session_id, query text, program ids) stays in the NDJSON logs and in
      OpenTelemetry span attributes, never in Prometheus labels.
"""
