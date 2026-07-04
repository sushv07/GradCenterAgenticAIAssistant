"""
tests/test_frontend_client.py
Unit tests for ApiClient and response_mapper.

These tests never make real HTTP calls — all network I/O is patched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

# Ensure project root is importable
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from frontend.services.api_client import ApiClient, BackendError
from frontend.services.response_mapper import map_response


# ---------------------------------------------------------------------------
# ApiClient — URL construction
# ---------------------------------------------------------------------------

class TestApiClientURLConstruction(TestCase):

    def setUp(self):
        self.client = ApiClient(base_url="https://example.com/")

    def test_trailing_slash_stripped(self):
        self.assertEqual(self.client.base_url, "https://example.com")

    def test_health_calls_correct_url(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch("frontend.services.api_client.requests.get", return_value=mock_response) as mock_get:
            self.client.health()
            mock_get.assert_called_once_with("https://example.com/health", timeout=10)

    def test_query_calls_correct_url_with_payload(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"route": "answer", "summary": "x"}
        mock_response.raise_for_status = MagicMock()

        with patch("frontend.services.api_client.requests.post", return_value=mock_response) as mock_post:
            self.client.query("hi", "sess-123")
            mock_post.assert_called_once_with(
                "https://example.com/query",
                json={"query": "hi", "session_id": "sess-123"},
                timeout=90,
            )


# ---------------------------------------------------------------------------
# ApiClient — error handling
# ---------------------------------------------------------------------------

class TestApiClientErrorHandling(TestCase):

    def setUp(self):
        self.client = ApiClient(base_url="https://example.com")

    def _make_http_error(self, status_code: int):
        import requests as req
        resp = MagicMock()
        resp.status_code = status_code
        exc = req.HTTPError(response=resp)
        return exc

    def test_connection_error_raises_backend_error(self):
        import requests as req
        with patch("frontend.services.api_client.requests.get", side_effect=req.ConnectionError()):
            with self.assertRaises(BackendError) as ctx:
                self.client.health()
        self.assertIn("connect", ctx.exception.message.lower())

    def test_timeout_raises_backend_error(self):
        import requests as req
        with patch("frontend.services.api_client.requests.get", side_effect=req.Timeout()):
            with self.assertRaises(BackendError) as ctx:
                self.client.health()
        self.assertIn("timed out", ctx.exception.message.lower())

    def test_http_error_raises_backend_error_with_status(self):
        import requests as req
        with patch("frontend.services.api_client.requests.get", side_effect=self._make_http_error(503)):
            with self.assertRaises(BackendError) as ctx:
                self.client.health()
        self.assertEqual(ctx.exception.status_code, 503)

    def test_invalid_json_raises_backend_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("bad json")
        with patch("frontend.services.api_client.requests.get", return_value=mock_response):
            with self.assertRaises(BackendError) as ctx:
                self.client.health()
        self.assertIn("invalid json", ctx.exception.message.lower())

    def test_post_connection_error_raises_backend_error(self):
        import requests as req
        with patch("frontend.services.api_client.requests.post", side_effect=req.ConnectionError()):
            with self.assertRaises(BackendError):
                self.client.query("q", "s")

    def test_post_timeout_raises_backend_error(self):
        import requests as req
        with patch("frontend.services.api_client.requests.post", side_effect=req.Timeout()):
            with self.assertRaises(BackendError) as ctx:
                self.client.query("q", "s")
        self.assertIn("timed out", ctx.exception.message.lower())

    def test_backend_error_never_exposes_requests_exception(self):
        import requests as req
        with patch("frontend.services.api_client.requests.get", side_effect=req.ConnectionError()):
            try:
                self.client.health()
            except BackendError:
                pass  # correct
            except req.ConnectionError:
                self.fail("raw requests.ConnectionError leaked out of ApiClient")


# ---------------------------------------------------------------------------
# response_mapper — normal shapes
# ---------------------------------------------------------------------------

class TestResponseMapperNormalShapes(TestCase):

    def test_summary_route_uses_summary(self):
        raw = {"route": "guidance", "summary": "Do X, then Y.", "next_actions": [], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["answer"], "Do X, then Y.")
        self.assertEqual(result["route"], "guidance")

    def test_answer_route_prefers_answer_field(self):
        raw = {"route": "answer", "answer": "42", "summary": "fallback", "next_actions": [], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["answer"], "42")

    def test_answer_route_falls_back_to_summary_when_answer_not_string(self):
        raw = {"route": "answer", "answer": {"structured": True}, "summary": "Fallback text.", "next_actions": [], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["answer"], "Fallback text.")

    def test_answer_route_falls_back_to_summary_when_answer_empty(self):
        raw = {"route": "answer", "answer": "", "summary": "Summary text.", "next_actions": [], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["answer"], "Summary text.")

    def test_source_with_url_included_in_sources(self):
        raw = {"route": "topic", "summary": "x", "next_actions": [], "source": {"file": "f.txt", "url": "https://example.edu/page"}}
        result = map_response(raw)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["url"], "https://example.edu/page")

    def test_empty_source_excluded(self):
        raw = {"route": "topic", "summary": "x", "next_actions": [], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["sources"], [])

    def test_next_actions_become_followups(self):
        raw = {"route": "guidance", "summary": "x", "next_actions": ["Q1?", "Q2?"], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["followups"], ["Q1?", "Q2?"])

    def test_raw_preserved(self):
        raw = {"route": "advisor", "summary": "See Dr. Smith.", "next_actions": [], "source": {}}
        result = map_response(raw)
        self.assertIs(result["raw"], raw)


# ---------------------------------------------------------------------------
# response_mapper — missing / malformed fields
# ---------------------------------------------------------------------------

class TestResponseMapperMissingFields(TestCase):

    def test_missing_route_defaults_to_empty_string(self):
        result = map_response({"summary": "ok", "next_actions": [], "source": {}})
        self.assertEqual(result["route"], "")

    def test_missing_summary_triggers_fallback_message(self):
        result = map_response({"route": "guidance", "next_actions": [], "source": {}})
        self.assertIn("sorry", result["answer"].lower())

    def test_missing_next_actions_defaults_to_empty_list(self):
        result = map_response({"route": "guidance", "summary": "x", "source": {}})
        self.assertEqual(result["followups"], [])

    def test_non_dict_input_returns_safe_dict(self):
        result = map_response("not a dict")  # type: ignore[arg-type]
        self.assertIn("answer", result)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["followups"], [])

    def test_non_string_items_in_next_actions_are_filtered(self):
        raw = {"route": "x", "summary": "y", "next_actions": ["ok", 42, None, "also ok"], "source": {}}
        result = map_response(raw)
        self.assertEqual(result["followups"], ["ok", "also ok"])

    def test_all_keys_present_in_output(self):
        result = map_response({})
        for key in ("route", "answer", "sources", "followups", "raw"):
            self.assertIn(key, result)
