"""
tests/test_api_health.py
Phase 5E — regression tests for health/readiness endpoints.
Phase 10E — extended with memory-optimization tests.

Covers:
  - GET /health: liveness shape (status/service/timestamp), always 200.
  - GET /ready: readiness shape, 200 when all checks pass.
  - Readiness degraded: one check failing -> 503, status="degraded", the
    other checks still report ok individually.
  - Readiness unavailable: every check failing -> 503, status="unavailable".
  - Response schema: every check result has the CheckResult shape.
  - OpenAPI schema includes HealthResponse / ReadinessResponse / CheckResult.
  - POST /query behavior is unchanged by this phase.
  - Phase 10E: vector_store check is passive (no embeddings loaded, no
    get_or_build_store() called); check passes when chroma.sqlite3 exists
    and fails when the directory or file is absent.
  - Phase 10E: HEAD / returns 200 (Render port-binding probe).

Run from the project root:
    pytest tests/test_api_health.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from api.app import app
from api.contracts import CheckResult
from state.context_manager import clear_context


def _fresh(sid: str) -> None:
    clear_context(sid)


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_is_always_200(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

    def test_health_shape(self):
        body = self.client.get("/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "csulb-grad-center-assistant")
        self.assertIsInstance(body["timestamp"], str)
        self.assertTrue(body["timestamp"].endswith("Z"))


class TestReadinessEndpointHealthy(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_ready_returns_200_when_all_checks_pass(self):
        r = self.client.get("/ready")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_ready_includes_all_five_checks(self):
        body = self.client.get("/ready").json()
        self.assertEqual(
            set(body["checks"].keys()),
            {"configuration", "dependencies", "taxonomy_file", "context_manager", "vector_store"},
        )

    def test_each_check_has_ok_and_detail_fields(self):
        body = self.client.get("/ready").json()
        for name, result in body["checks"].items():
            self.assertIn("ok", result, name)
            self.assertIn("detail", result, name)
            self.assertIsInstance(result["ok"], bool, name)

    def test_passing_checks_have_no_detail(self):
        body = self.client.get("/ready").json()
        for name, result in body["checks"].items():
            if result["ok"]:
                self.assertIsNone(result["detail"], name)


class TestReadinessEndpointDegradedAndUnavailable(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_one_failing_check_yields_degraded_503(self):
        with patch(
            "api.health._check_vector_store",
            return_value=CheckResult(ok=False, detail="simulated outage"),
        ):
            r = self.client.get("/ready")
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        self.assertFalse(body["checks"]["vector_store"]["ok"])
        self.assertEqual(body["checks"]["vector_store"]["detail"], "simulated outage")
        # other checks remain independently evaluated and passing
        self.assertTrue(body["checks"]["configuration"]["ok"])

    def test_all_failing_checks_yield_unavailable_503(self):
        fail = CheckResult(ok=False, detail="down")
        with patch("api.health._check_configuration", return_value=fail), \
             patch("api.health._check_dependencies", return_value=fail), \
             patch("api.health._check_taxonomy_file", return_value=fail), \
             patch("api.health._check_context_manager", return_value=fail), \
             patch("api.health._check_vector_store", return_value=fail):
            r = self.client.get("/ready")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["status"], "unavailable")

    def test_a_check_that_raises_is_reported_not_propagated(self):
        """Checks must never crash the endpoint — exceptions become a
        failing CheckResult instead of a 500."""
        from api.health import _check_vector_store
        with patch("rag.store.check_store_on_disk", side_effect=RuntimeError("boom")):
            result = _check_vector_store()
        self.assertFalse(result.ok)
        self.assertIn("boom", result.detail)

    def test_a_check_that_raises_does_not_500_the_ready_endpoint(self):
        with patch("api.health._check_vector_store", side_effect=RuntimeError("boom")):
            r = self.client.get("/ready")
        self.assertIn(r.status_code, (200, 503))


class TestOpenAPISchemaIncludesHealthModels(unittest.TestCase):
    def test_health_and_readiness_models_registered(self):
        schema = app.openapi()
        component_names = set(schema.get("components", {}).get("schemas", {}).keys())
        self.assertTrue(
            {"HealthResponse", "ReadinessResponse", "CheckResult"}.issubset(component_names),
            component_names,
        )

    def test_ready_and_health_paths_documented(self):
        schema = app.openapi()
        self.assertIn("/health", schema["paths"])
        self.assertIn("/ready", schema["paths"])


class TestQueryUnaffectedByThisPhase(unittest.TestCase):
    def test_query_still_works_identically(self):
        sid = "health-phase-query-check"
        _fresh(sid)
        client = TestClient(app)
        r = client.post("/query", json={"query": "when is the application deadline", "session_id": sid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["route"], "deadlines")
        _fresh(sid)


# ---------------------------------------------------------------------------
# Phase 10E — passive vector_store check and HEAD / support
# ---------------------------------------------------------------------------

class TestVectorStorePassiveCheck(unittest.TestCase):
    """
    The _check_vector_store check must:
      - Pass when chroma.sqlite3 exists on disk
      - Fail (not raise) when the chroma_db directory is absent
      - Fail (not raise) when chroma.sqlite3 is absent but the dir exists
      - Never call get_or_build_store() (which would load the embedding model)
      - Never load HuggingFaceEmbeddings (memory safety on 512 MB instances)
    """

    def test_passes_when_sqlite3_exists(self):
        """check_store_on_disk returns (True, '') when chroma.sqlite3 is present."""
        import tempfile
        from pathlib import Path
        from api.health import _check_vector_store

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_dir = Path(tmpdir) / "chroma_db"
            fake_dir.mkdir()
            (fake_dir / "chroma.sqlite3").touch()

            with patch("rag.store.CHROMA_DIR", fake_dir):
                result = _check_vector_store()

        self.assertTrue(result.ok)
        self.assertIsNone(result.detail)

    def test_fails_when_chroma_dir_missing(self):
        """check_store_on_disk fails gracefully when chroma_db does not exist."""
        import tempfile
        from pathlib import Path
        from api.health import _check_vector_store

        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_dir = Path(tmpdir) / "chroma_db"
            # directory is intentionally NOT created

            with patch("rag.store.CHROMA_DIR", nonexistent_dir):
                result = _check_vector_store()

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.detail)
        self.assertIn("chroma_db", result.detail)

    def test_fails_when_sqlite3_missing(self):
        """check_store_on_disk fails gracefully when directory exists but sqlite3 is absent."""
        import tempfile
        from pathlib import Path
        from api.health import _check_vector_store

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_dir = Path(tmpdir) / "chroma_db"
            fake_dir.mkdir()
            # chroma.sqlite3 is intentionally NOT created

            with patch("rag.store.CHROMA_DIR", fake_dir):
                result = _check_vector_store()

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.detail)
        self.assertIn("chroma.sqlite3", result.detail)

    def test_ready_does_not_call_get_or_build_store(self):
        """GET /ready must never call get_or_build_store (the expensive ML load path)."""
        with patch("rag.store.get_or_build_store") as mock_build:
            TestClient(app).get("/ready")
        mock_build.assert_not_called()

    def test_ready_does_not_initialize_embeddings(self):
        """GET /ready must not load HuggingFaceEmbeddings into memory."""
        import rag.store as store
        original = store._EMBEDDINGS
        TestClient(app).get("/ready")
        self.assertIs(
            store._EMBEDDINGS,
            original,
            "/ready must not initialize the embedding model",
        )


class TestRootHeadSupport(unittest.TestCase):
    """
    Phase 10E — HEAD / must return 200.
    Render issues HEAD / to verify port binding before the configured
    healthCheckPath is probed. A 405 stalls the deployment loop.
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_head_root_returns_200(self):
        r = self.client.head("/")
        self.assertEqual(r.status_code, 200)

    def test_get_root_still_returns_200(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_head_root_returns_no_body(self):
        r = self.client.head("/")
        self.assertEqual(r.content, b"")

    def test_get_root_shape_unchanged(self):
        body = self.client.get("/").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "csulb-grad-center-assistant")

    def test_no_duplicate_operation_id_warning(self):
        """GET / and HEAD / must not produce a duplicate-operation-ID warning."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            try:
                app.openapi()
            except UserWarning as exc:
                self.fail(f"OpenAPI schema generation raised UserWarning: {exc}")


if __name__ == "__main__":
    unittest.main()
