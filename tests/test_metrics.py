"""
tests/test_metrics.py
Phase 1 observability — Prometheus metrics.

Verifies the additive metrics layer without changing any application behavior:
  * /metrics is exposed in the Prometheus text exposition format
  * HTTP-transport metrics are recorded by the middleware for real requests
  * pipeline (domain) metrics are recorded at the handle_user_query seam
  * high-cardinality data (session_id, query text) never appears as a label
  * existing endpoints behave exactly as before (status codes, response shape)

These assertions read the live /metrics output through the FastAPI TestClient,
so they exercise the real middleware + endpoint wiring, not mocks.

Run: pytest tests/test_metrics.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from api.app import app
from state.context_manager import clear_context
from telemetry import metrics


def _metrics_text(client: TestClient) -> str:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    return resp.text


class TestMetricsEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_metrics_endpoint_exposition_format(self):
        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers["content-type"])
        body = resp.text
        # HELP/TYPE lines for our declared instruments are present.
        self.assertIn("http_requests_total", body)
        self.assertIn("http_request_duration_seconds", body)
        self.assertIn("http_requests_in_flight", body)
        self.assertIn("pipeline_requests_total", body)

    def test_http_metrics_recorded_for_request(self):
        # A health call is cheap and deterministic; it must be counted.
        self.client.get("/health")
        body = _metrics_text(self.client)
        self.assertIn('http_requests_total{', body)
        self.assertIn('route="/health"', body)
        self.assertIn('status_class="2xx"', body)

    def test_metrics_endpoint_not_self_counted(self):
        # The middleware skips /metrics, so scraping never appears as a route.
        body = _metrics_text(self.client)
        self.assertNotIn('route="/metrics"', body)

    def test_pipeline_metrics_recorded_via_query(self):
        clear_context("metrics-pipe")
        r = self.client.post("/query", json={"query": "", "session_id": "metrics-pipe"})
        self.assertEqual(r.status_code, 200)            # behavior unchanged
        body = _metrics_text(self.client)
        # Empty query resolves to the welcome route; pipeline counter reflects it.
        self.assertIn("pipeline_requests_total{", body)
        self.assertIn('outcome="ok"', body)

    def test_no_high_cardinality_labels(self):
        # Drive a request carrying a distinctive session id + query, then assert
        # neither leaks into the metric labels (they belong in logs/traces).
        clear_context("SECRET-SESSION-XYZ")
        self.client.post("/query",
                         json={"query": "who is the advisor for physical therapy",
                               "session_id": "SECRET-SESSION-XYZ"})
        body = _metrics_text(self.client)
        self.assertNotIn("SECRET-SESSION-XYZ", body)
        self.assertNotIn("physical therapy", body)


class TestMetricsHelpers(unittest.TestCase):
    def test_status_class(self):
        self.assertEqual(metrics.status_class(200), "2xx")
        self.assertEqual(metrics.status_class(404), "4xx")
        self.assertEqual(metrics.status_class(503), "5xx")

    def test_record_pipeline_normalises_empty_route(self):
        # Empty route must not produce an empty label; it becomes "unknown".
        before = _sample("pipeline_requests_total", route="unknown", outcome="ok")
        metrics.record_pipeline("", had_error=False, duration_seconds=0.01)
        after = _sample("pipeline_requests_total", route="unknown", outcome="ok")
        self.assertEqual(after - before, 1.0)

    def test_record_pipeline_error_path(self):
        before = _sample("pipeline_errors_total", route="advisor")
        metrics.record_pipeline("advisor", had_error=True, duration_seconds=0.02)
        after = _sample("pipeline_errors_total", route="advisor")
        self.assertEqual(after - before, 1.0)


def _sample(name: str, **labels) -> float:
    """Read a single sample value from the default registry (0.0 if absent).
    `name` is the full exposed series name, e.g. "pipeline_requests_total"."""
    from prometheus_client import REGISTRY
    return REGISTRY.get_sample_value(name, labels) or 0.0


if __name__ == "__main__":
    unittest.main()
