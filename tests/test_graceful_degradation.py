"""
tests/test_graceful_degradation.py
Phase 6A — regression tests for graceful failure handling.

Covers:
  - Retriever/Chroma unavailable: rag.retriever.retrieve() already returns
    [] gracefully (pre-existing behavior) — locked in here as a regression
    test, not newly introduced.
  - Taxonomy unavailable: _load_taxonomy() logs clearly and re-raises
    rather than silently returning an empty list (which would be
    indistinguishable from "no programs matched").
  - Backend entry point exception: handle_user_query() never propagates an
    unhandled exception — it returns a controlled route="error" response.
  - Tool exception: an exception raised deep inside the call chain (e.g.
    inside orchestrator.run()'s dispatch) is still caught at the entry
    point, not just exceptions raised directly by orchestrator.run() itself.
  - FastAPI returns a controlled response (200, not 500) instead of
    crashing when the backend raises.
  - Successful requests are completely unaffected by any of this.

Run from the project root:
    pytest tests/test_graceful_degradation.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.entrypoint import handle_user_query
from api.app import app
from api.contracts import ErrorResponseModel
from state.context_manager import clear_context


def _fresh(sid: str) -> None:
    clear_context(sid)


class TestRetrieverUnavailable(unittest.TestCase):
    """Pre-existing behavior, locked in as a regression test."""

    def test_store_unavailable_returns_empty_list_not_exception(self):
        from rag.retriever import retrieve
        with patch("rag.retriever.get_or_build_store", return_value=None):
            result = retrieve("what gpa do i need")
        self.assertEqual(result, [])

    def test_similarity_search_exception_returns_empty_list_not_exception(self):
        from rag.retriever import retrieve
        fake_store = type("FakeStore", (), {
            "similarity_search_with_relevance_scores": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("chroma down"))
        })()
        with patch("rag.retriever.get_or_build_store", return_value=fake_store):
            result = retrieve("what gpa do i need")
        self.assertEqual(result, [])


class TestTaxonomyUnavailable(unittest.TestCase):
    def test_load_taxonomy_logs_and_reraises_on_missing_file(self):
        import agents.recommendation_engine as engine
        with patch.object(engine, "_TAXONOMY_CACHE", None), \
             patch.object(engine, "PROGRAM_TAXONOMY_PATH") as mock_path:
            mock_path.open.side_effect = FileNotFoundError("no such file")
            with self.assertRaises(FileNotFoundError):
                engine._load_taxonomy()

    def test_taxonomy_failure_is_caught_at_backend_entry_point(self):
        """The recommendation_engine layer re-raises (by design); the
        backend entry point is responsible for turning that into a safe
        response."""
        import agents.recommendation_engine as engine
        sid = "grace-taxonomy-1"
        _fresh(sid)
        with patch.object(engine, "_TAXONOMY_CACHE", None), \
             patch.object(engine, "PROGRAM_TAXONOMY_PATH") as mock_path:
            mock_path.open.side_effect = FileNotFoundError("no such file")
            response = handle_user_query("I want to become a nurse practitioner", session_id=sid)
        self.assertEqual(response["route"], "error")
        self.assertEqual(response["error"], "FileNotFoundError")
        _fresh(sid)


class TestBackendEntryPointException(unittest.TestCase):
    def test_orchestrator_exception_returns_controlled_response(self):
        sid = "grace-entry-1"
        _fresh(sid)
        with patch("orchestrator.run", side_effect=RuntimeError("simulated outage")):
            response = handle_user_query("when is the application deadline", session_id=sid)
        self.assertEqual(response["route"], "error")
        self.assertEqual(response["error"], "RuntimeError")
        self.assertIn("session_id", response)
        self.assertEqual(response["session_id"], sid)
        _fresh(sid)

    def test_handle_discovery_exception_returns_controlled_response(self):
        """Exercises the discovery-continuation branch of handle_user_query(),
        not just the orchestrator.run() branch."""
        sid = "grace-entry-2"
        _fresh(sid)
        # First turn starts discovery so the session is in "clarifying" phase.
        handle_user_query("I am interested in educational leadership", session_id=sid)
        with patch("backend.entrypoint.handle_discovery", side_effect=RuntimeError("boom")):
            response = handle_user_query("looking to lead K-12 schools", session_id=sid)
        self.assertEqual(response["route"], "error")
        self.assertEqual(response["error"], "RuntimeError")
        _fresh(sid)

    def test_error_response_does_not_leak_raw_exception_message(self):
        """error must be the exception TYPE NAME only — never the message,
        which could contain internal paths or details."""
        sid = "grace-entry-3"
        _fresh(sid)
        with patch("orchestrator.run", side_effect=RuntimeError("/etc/secret/path leaked")):
            response = handle_user_query("when is the application deadline", session_id=sid)
        self.assertEqual(response["error"], "RuntimeError")
        self.assertNotIn("/etc/secret/path", str(response))
        _fresh(sid)

    def test_successful_request_unaffected(self):
        sid = "grace-entry-4"
        _fresh(sid)
        response = handle_user_query("when is the application deadline", session_id=sid)
        self.assertEqual(response["route"], "deadlines")
        self.assertNotIn("error", response)
        _fresh(sid)


class TestFastAPIDoesNotCrash(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_query_returns_200_not_500_when_backend_raises(self):
        sid = "grace-api-1"
        _fresh(sid)
        with patch("orchestrator.run", side_effect=RuntimeError("simulated outage")):
            r = self.client.post("/query", json={"query": "when is the application deadline", "session_id": sid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["route"], "error")
        _fresh(sid)

    def test_error_response_validates_against_error_response_model(self):
        sid = "grace-api-2"
        _fresh(sid)
        with patch("orchestrator.run", side_effect=RuntimeError("simulated outage")):
            r = self.client.post("/query", json={"query": "when is the application deadline", "session_id": sid})
        ErrorResponseModel(**r.json())
        _fresh(sid)

    def test_error_route_model_registered_in_openapi(self):
        schema = app.openapi()
        component_names = set(schema.get("components", {}).get("schemas", {}).keys())
        self.assertIn("ErrorResponseModel", component_names)


if __name__ == "__main__":
    unittest.main()
