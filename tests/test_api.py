"""
tests/test_api.py
Phase 5C — regression tests for the FastAPI service layer.

Covers:
  - GET / and GET /health.
  - POST /query for a standard route, a discovery route, and multi-turn
    discovery continuation (same session_id across two calls).
  - Invalid request (missing required "query" field) -> 422.
  - Dependency injection still works through FastAPI's own Depends()
    override mechanism.
  - Response equality: calling the API produces the exact same dict as
    calling backend.entrypoint.handle_user_query() directly for the same
    query/session_id — proving FastAPI added no business logic.

Run from the project root:
    pytest tests/test_api.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from fastapi.testclient import TestClient

from api.app import app
from backend.entrypoint import handle_user_query
from backend.dependencies import get_dependencies
from state.context_manager import clear_context


def _fresh(sid: str) -> None:
    clear_context(sid)


class TestRootAndHealth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("service", body)
        self.assertIn("timestamp", body)


class TestQueryEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_standard_route(self):
        sid = "api-test-standard"
        _fresh(sid)
        r = self.client.post("/query", json={"query": "when is the application deadline", "session_id": sid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["route"], "deadlines")
        _fresh(sid)

    def test_discovery_start(self):
        sid = "api-test-discovery-start"
        _fresh(sid)
        r = self.client.post("/query", json={"query": "I don't know what graduate program fits me", "session_id": sid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["route"], "discovery")
        _fresh(sid)

    def test_discovery_continuation_across_two_calls(self):
        sid = "api-test-discovery-continue"
        _fresh(sid)
        r1 = self.client.post("/query", json={"query": "I am interested in educational leadership", "session_id": sid})
        self.assertEqual(r1.json()["behavior"], "clarify")

        r2 = self.client.post("/query", json={"query": "looking to lead K-12 schools and districts", "session_id": sid})
        ids = [m["program_id"] for m in r2.json().get("program_matches", [])]
        self.assertIn("edd-educational-leadership-p12", ids)
        _fresh(sid)

    def test_empty_query_returns_welcome_not_an_error(self):
        r = self.client.post("/query", json={"query": ""})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["route"])

    def test_missing_query_field_is_422(self):
        r = self.client.post("/query", json={})
        self.assertEqual(r.status_code, 422)

    def test_session_default_when_omitted(self):
        r = self.client.post("/query", json={"query": "when is the application deadline"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["session_id"], "default")


class TestDependencyInjectionThroughFastAPI(unittest.TestCase):
    """FastAPI's own Depends() override mechanism must work for the
    Phase 5B dependency container — proving the API doesn't bypass it."""

    def test_overriding_get_dependencies_is_honored(self):
        from backend.dependencies import get_dependencies as real_get_dependencies

        calls: list[bool] = []

        def spy_get_dependencies():
            calls.append(True)
            return real_get_dependencies()

        app.dependency_overrides[real_get_dependencies] = spy_get_dependencies
        try:
            client = TestClient(app)
            sid = "api-test-di-override"
            _fresh(sid)
            r = client.post("/query", json={"query": "when is the application deadline", "session_id": sid})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(calls, "overridden dependency provider was never called")
            _fresh(sid)
        finally:
            app.dependency_overrides.clear()


class TestResponseEqualityWithDirectBackendCall(unittest.TestCase):
    """The API must add zero business logic — same input must produce the
    exact same dict as calling handle_user_query() directly."""

    def test_query_endpoint_matches_direct_call(self):
        sid_api = "api-test-equality-api"
        sid_direct = "api-test-equality-direct"
        _fresh(sid_api)
        _fresh(sid_direct)

        client = TestClient(app)
        api_response = client.post(
            "/query", json={"query": "who is my advisor for nursing", "session_id": sid_api}
        ).json()
        direct_response = handle_user_query("who is my advisor for nursing", session_id=sid_direct)

        # session_id differs by construction (different sid per call) — compare everything else.
        api_response.pop("session_id")
        direct_response.pop("session_id")
        self.assertEqual(api_response, direct_response)

        _fresh(sid_api)
        _fresh(sid_direct)


if __name__ == "__main__":
    unittest.main()
