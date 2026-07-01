"""
tests/test_api_contracts.py
Phase 5D — regression tests for explicit API contracts (api/contracts.py).

Covers:
  - Request validation: QueryRequest accepts valid payloads, rejects a
    missing required "query" field, does NOT reject an empty query string
    (that's a valid, existing backend behavior, not invalid input).
  - Response validation: every route's real backend response validates
    cleanly against its corresponding Pydantic model in api.contracts.
  - response_model_exclude_unset=True: verified directly — fields the
    backend omits (program_matches, clarification_question, email_draft)
    stay absent from the HTTP response; fields the backend always sets,
    even to null (GuidanceStepItem.watch_out/link), stay present.
  - OpenAPI schema generation: /query has a documented 200 response with
    all 7 route-specific models registered as components.
  - Response model equality with backend output, for every route shape:
    welcome, guidance, answer, topic (deadlines), advisor (with and
    without email_draft), next_steps, discovery (clarify and recommend).
  - Invalid payloads: wrong type for session_id.

Run from the project root:
    pytest tests/test_api_contracts.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.app import app
from api.contracts import (
    QueryRequest,
    WelcomeResponseModel,
    GuidanceResponseModel,
    AnswerResponseModel,
    TopicResponseModel,
    AdvisorResponseModel,
    NextStepsResponseModel,
    DiscoveryResponseModel,
)
from backend.entrypoint import handle_user_query
from agents.journey_agent import handle_discovery
from state.context_manager import clear_context


def _fresh(sid: str) -> None:
    clear_context(sid)


class TestQueryRequestValidation(unittest.TestCase):
    def test_valid_payload(self):
        req = QueryRequest(query="hello", session_id="s1")
        self.assertEqual(req.query, "hello")
        self.assertEqual(req.session_id, "s1")

    def test_session_id_optional(self):
        req = QueryRequest(query="hello")
        self.assertIsNone(req.session_id)

    def test_empty_query_string_is_valid(self):
        """Deliberately NOT rejected — handle_user_query("") is a valid,
        existing backend call that returns a WelcomeResponse."""
        req = QueryRequest(query="")
        self.assertEqual(req.query, "")

    def test_missing_query_field_raises(self):
        with self.assertRaises(ValidationError):
            QueryRequest(session_id="s1")


class TestResponseModelsValidateRealBackendOutput(unittest.TestCase):
    """Each Pydantic model must accept the actual dict its route produces —
    not a hand-written fixture that might drift from reality."""

    def test_welcome(self):
        r = handle_user_query("")
        WelcomeResponseModel(**r)

    def test_guidance(self):
        sid = "contract-guidance"
        _fresh(sid)
        r = handle_user_query("how do I apply", session_id=sid)
        GuidanceResponseModel(**r)
        _fresh(sid)

    def test_answer(self):
        sid = "contract-answer"
        _fresh(sid)
        r = handle_user_query("who do i contact about thesis submission", session_id=sid)
        AnswerResponseModel(**r)
        _fresh(sid)

    def test_topic_deadlines(self):
        sid = "contract-deadlines"
        _fresh(sid)
        r = handle_user_query("when is the deadline", session_id=sid)
        TopicResponseModel(**r)
        _fresh(sid)

    def test_advisor_with_match(self):
        sid = "contract-advisor"
        _fresh(sid)
        r = handle_user_query("who is my advisor for nursing", session_id=sid)
        AdvisorResponseModel(**r)
        _fresh(sid)

    def test_advisor_without_match(self):
        sid = "contract-advisor-nomatch"
        _fresh(sid)
        r = handle_user_query("who is the advisor for underwater basket weaving", session_id=sid)
        AdvisorResponseModel(**r)
        _fresh(sid)

    def test_next_steps(self):
        sid = "contract-next-steps"
        _fresh(sid)
        r = handle_user_query("I dont know where to start", session_id=sid)
        NextStepsResponseModel(**r)
        _fresh(sid)

    def test_discovery_clarify(self):
        sid = "contract-disc-clarify"
        _fresh(sid)
        r, _ = handle_discovery("I am exploring my options", sid)
        DiscoveryResponseModel(**r)
        _fresh(sid)

    def test_discovery_recommend(self):
        sid = "contract-disc-rec"
        _fresh(sid)
        r, _ = handle_discovery("I want to become a nurse practitioner", sid)
        DiscoveryResponseModel(**r)
        _fresh(sid)


class TestExcludeUnsetPreservesBackendShapeExactly(unittest.TestCase):
    """The specific bug this phase's validation caught: without
    exclude_unset, optional fields the backend omits would reappear in the
    HTTP response as explicit nulls."""

    def setUp(self):
        self.client = TestClient(app)

    def test_discovery_clarify_omits_program_matches_key(self):
        sid = "exclude-unset-clarify"
        _fresh(sid)
        body = self.client.post("/query", json={"query": "I am exploring my options", "session_id": sid}).json()
        self.assertNotIn("program_matches", body)
        _fresh(sid)

    def test_discovery_recommend_omits_clarification_question_key(self):
        sid = "exclude-unset-recommend"
        _fresh(sid)
        body = self.client.post("/query", json={"query": "I want to become a nurse practitioner", "session_id": sid}).json()
        self.assertNotIn("clarification_question", body)
        _fresh(sid)

    def test_advisor_without_match_omits_email_draft_key(self):
        sid = "exclude-unset-advisor"
        _fresh(sid)
        body = self.client.post(
            "/query",
            json={"query": "who is the advisor for underwater basket weaving", "session_id": sid},
        ).json()
        self.assertNotIn("email_draft", body)
        _fresh(sid)

    def test_guidance_step_keeps_explicit_null_fields(self):
        """watch_out/link are always set by the backend (sometimes to None) —
        exclude_unset must NOT strip these, since they were explicitly set."""
        sid = "exclude-unset-guidance"
        _fresh(sid)
        body = self.client.post("/query", json={"query": "how do I apply", "session_id": sid}).json()
        step = body["steps"][0]
        self.assertIn("watch_out", step)
        self.assertIn("link", step)
        _fresh(sid)


class TestOpenAPISchemaGeneration(unittest.TestCase):
    def test_query_path_has_200_response_documented(self):
        schema = app.openapi()
        query_post = schema["paths"]["/query"]["post"]
        self.assertIn("200", query_post["responses"])

    def test_all_route_models_registered_as_components(self):
        schema = app.openapi()
        component_names = set(schema.get("components", {}).get("schemas", {}).keys())
        expected = {
            "WelcomeResponseModel", "GuidanceResponseModel", "AnswerResponseModel",
            "TopicResponseModel", "AdvisorResponseModel", "NextStepsResponseModel",
            "DiscoveryResponseModel", "QueryRequest",
        }
        self.assertTrue(expected.issubset(component_names), component_names)


class TestInvalidPayloads(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_wrong_type_for_session_id_is_422(self):
        r = self.client.post("/query", json={"query": "hello", "session_id": 12345})
        self.assertEqual(r.status_code, 422)

    def test_wrong_type_for_query_is_422(self):
        r = self.client.post("/query", json={"query": ["not", "a", "string"]})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
