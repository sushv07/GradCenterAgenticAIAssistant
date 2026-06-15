"""
test_llm_synthesizer.py
Smoke tests for agents/llm_synthesizer.py.

All Ollama HTTP calls are mocked — no real model required.
Tests verify: feature flag, happy path, validation failures, network failures,
input type flexibility, and output contract (no extra fields).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests as req_module

import agents.llm_synthesizer as synth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ollama_response(answer: str, confidence: str, status_code: int = 200) -> MagicMock:
    """Return a mock requests.Response mimicking a successful Ollama reply."""
    resp = MagicMock()
    resp.status_code = status_code

    if status_code >= 400:
        resp.raise_for_status.side_effect = req_module.HTTPError(
            f"HTTP {status_code}"
        )
    else:
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "message": {
                "content": json.dumps({"answer": answer, "confidence": confidence})
            }
        }

    return resp


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def test_disabled_returns_none_without_api_call():
    """When LLM_SYNTHESIS_ENABLED is false, synthesize_answer returns None with no HTTP call."""
    with patch.object(synth, "_ENABLED", False), \
         patch("requests.post") as mock_post:
        result = synth.synthesize_answer(
            "what is the GPA requirement?",
            {"details": "GPA must be 3.0"},
            "admissions.json",
        )
    assert result is None
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_returns_answer_and_confidence_on_success():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("GPA must be 3.0.", "high")):
        result = synth.synthesize_answer(
            "what is the GPA requirement?",
            {"details": "minimum cumulative GPA 3.0"},
            "admissions.json",
        )
    assert result == {"answer": "GPA must be 3.0.", "confidence": "high"}


def test_output_contains_only_answer_and_confidence():
    """The returned dict must NOT contain query, source_file, source_url, or next_steps."""
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("Deadline is October 1.", "medium")):
        result = synth.synthesize_answer(
            "when is the deadline?",
            "Fall deadline: October 1.",
            "admissions.json",
            source_url="https://www.csulb.edu/admissions",
        )
    assert result is not None
    assert set(result.keys()) == {"answer", "confidence"}


def test_answer_text_is_stripped():
    """Leading/trailing whitespace in the model response is stripped."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "message": {"content": json.dumps({"answer": "  Stripped.  ", "confidence": "low"})}
    }
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=resp):
        result = synth.synthesize_answer("q", "ctx", "f.json")
    assert result["answer"] == "Stripped."


# ---------------------------------------------------------------------------
# Validation failures — each returns None
# ---------------------------------------------------------------------------

def test_invalid_confidence_returns_none():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("An answer.", "very_high")):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_empty_answer_returns_none():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("", "high")):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_whitespace_only_answer_returns_none():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("   ", "medium")):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_invalid_json_returns_none():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message": {"content": "not json {"}}
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=resp):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_empty_content_returns_none():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message": {"content": ""}}
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=resp):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_missing_answer_key_returns_none():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message": {"content": json.dumps({"confidence": "high"})}}
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=resp):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


# ---------------------------------------------------------------------------
# Network / HTTP failures — each returns None
# ---------------------------------------------------------------------------

def test_http_500_returns_none():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("", "", status_code=500)):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_connection_error_returns_none():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", side_effect=req_module.ConnectionError("Ollama not running")):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


def test_timeout_returns_none():
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", side_effect=req_module.Timeout("timed out")):
        assert synth.synthesize_answer("q", "ctx", "f.json") is None


# ---------------------------------------------------------------------------
# Input type flexibility
# ---------------------------------------------------------------------------

def test_dict_retrieved_answer_makes_api_call():
    """A dict retrieved_answer is serialized — no crash."""
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("From dict.", "medium")) as mock_post:
        synth.synthesize_answer("q", {"key": "value", "nested": [1, 2]}, "f.json")
    mock_post.assert_called_once()


def test_str_retrieved_answer_makes_api_call():
    """A plain string retrieved_answer is accepted."""
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("From str.", "low")) as mock_post:
        synth.synthesize_answer("q", "plain text context", "f.json")
    mock_post.assert_called_once()


def test_source_url_none_does_not_crash():
    """source_url=None (default) is accepted without error."""
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("OK.", "high")):
        result = synth.synthesize_answer("q", "ctx", "f.json")
    assert result is not None


# ---------------------------------------------------------------------------
# All three confidence enum values are accepted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("conf", ["high", "medium", "low"])
def test_all_valid_confidence_values(conf):
    with patch.object(synth, "_ENABLED", True), \
         patch("requests.post", return_value=_ollama_response("Answer.", conf)):
        result = synth.synthesize_answer("q", "ctx", "f.json")
    assert result is not None
    assert result["confidence"] == conf
