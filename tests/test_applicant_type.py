"""
tests/test_applicant_type.py
Generic domestic/international applicant-type clarification before application
workflows, integrated with the shared active-program context and the typed
pending-clarification framework.

End-to-end through the REAL backend path (backend.entrypoint.handle_user_query),
using two programs (Physical Therapy / DPT and Public Health / DrPH) to prove
the behavior is generic and not hard-coded. Uses the local store for the
application tool.

Run: pytest tests/test_applicant_type.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.entrypoint import handle_user_query
from state.context_manager import clear_context, get_context
from agents.journey_agent import init_journey_state
from state import clarification


def _js(sid):
    return get_context(sid, init_journey_state).journey_state


def _applicant_type(sid):
    return _js(sid).get("applicant_type", "")


def _pending(sid):
    return _js(sid).get("pending_clarification")


def _workflow(resp):
    return (resp.get("tool_result") or {}).get("workflow_steps") or []


def _needs_type(resp):
    return (resp.get("tool_result") or {}).get("needs_applicant_type")


# ---------------------------------------------------------------------------
# Framework unit tests (no store)
# ---------------------------------------------------------------------------

class TestClarificationFramework(unittest.TestCase):
    def test_parse_applicant_type(self):
        self.assertEqual(clarification.parse_applicant_type("international"), "international")
        self.assertEqual(clarification.parse_applicant_type("Domestic student"), "domestic")
        self.assertEqual(clarification.parse_applicant_type("Actually, I am an international student"),
                         "international")
        self.assertIsNone(clarification.parse_applicant_type("what are the steps"))

    def test_bare_statement_detection(self):
        self.assertTrue(clarification.is_bare_applicant_statement("international"))
        self.assertTrue(clarification.is_bare_applicant_statement("I am a domestic applicant"))
        # carries an actionable request → not bare
        self.assertFalse(clarification.is_bare_applicant_statement(
            "what are the application steps for international students"))

    def test_typed_pending_helpers_and_registry(self):
        js = {}
        clarification.set_pending(js, "applicant_type", route="application", original_query="x")
        p = clarification.get_pending(js)
        self.assertEqual(p["kind"], "applicant_type")
        self.assertIn("applicant_type", clarification._RESUMERS)   # resumer registered
        clarification.clear_pending(js)
        self.assertIsNone(clarification.get_pending(js))


# ---------------------------------------------------------------------------
# End-to-end conversation tests (two programs)
# ---------------------------------------------------------------------------

class TestApplicantTypeFlow(unittest.TestCase):
    def setUp(self):
        for s in ("t1", "t2", "t3", "t4", "t5", "t6", "t7"):
            clear_context(s)

    # 1 — unknown applicant type → clarification, no workflow yet
    def test_1_unknown_type_asks(self):
        r = handle_user_query("how do I apply for physical therapy", "t1")   # active=DPT
        self.assertEqual(r["route"], "application")
        self.assertTrue(_needs_type(r))
        self.assertEqual((r.get("tool_result") or {}).get("applicant_type_choices"), ["domestic", "international"])
        self.assertFalse(_workflow(r))                    # workflow NOT rendered yet
        self.assertTrue(_pending("t1"))                    # pending stored

    # 2 — domestic selection resumes with the program workflow, no intl guidance
    def test_2_domestic_resumes_no_international(self):
        handle_user_query("how do I apply for physical therapy", "t2")
        r = handle_user_query("domestic", "t2")
        self.assertEqual(r["route"], "application")
        self.assertEqual(_applicant_type("t2"), "domestic")
        self.assertIsNone(r.get("international_info"))
        self.assertTrue(_workflow(r))                      # DPT workflow present
        self.assertIsNone(_pending("t2"))                  # pending cleared

    # 3 — international selection: guidance (all categories) + workflow (supplement)
    def test_3_international_supplements_workflow(self):
        handle_user_query("how do I apply for public health", "t3")          # active=DrPH
        r = handle_user_query("international", "t3")
        self.assertEqual(_applicant_type("t3"), "international")
        info = r.get("international_info")
        self.assertIsNotNone(info)
        emails = {e["email"] for e in info["emails"]}
        self.assertEqual(emails, {"cie-apply@csulb.edu", "cie-admission@csulb.edu",
                                  "cie-student@csulb.edu", "studyabroad@csulb.edu"})
        self.assertEqual(info["phone"], "562-985-5555")
        self.assertIn("Foundation Building", info["location"])
        self.assertEqual(info["international_page"]["url"], "https://www.csulb.edu/international")
        self.assertTrue(_workflow(r))                      # workflow NOT replaced

    # 4 — persistence: already international, switch program → no re-ask
    def test_4_persistence_across_program_switch(self):
        handle_user_query("how do I apply for physical therapy", "t4")
        handle_user_query("international", "t4")            # DPT + international
        r = handle_user_query("how do I apply for public health", "t4")      # switch → DrPH
        self.assertEqual(r["route"], "application")
        self.assertFalse(_needs_type(r))    # not asked again
        self.assertEqual(_applicant_type("t4"), "international")
        self.assertIsNotNone(r.get("international_info"))
        self.assertTrue(_workflow(r))

    # 5 — explicit status change updates the canonical field
    def test_5_explicit_status_change(self):
        handle_user_query("how do I apply for physical therapy", "t5")
        handle_user_query("domestic", "t5")                # domestic
        ack = handle_user_query("Actually, I am an international student", "t5")
        self.assertEqual(_applicant_type("t5"), "international")
        r = handle_user_query("how do I apply to it", "t5")  # contextual, DPT active
        self.assertIsNotNone(r.get("international_info"))    # future app response includes intl

    # 6 — no active program → does NOT ask applicant type
    def test_6_no_active_program_no_ask(self):
        r = handle_user_query("How do I apply?", "t6")
        self.assertFalse(_needs_type(r))
        self.assertIsNone(_applicant_type("t6") or None)    # unset

    # 7 — non-application routes never trigger applicant-type clarification
    def test_7_non_application_routes_unaffected(self):
        handle_user_query("how do I apply for physical therapy", "t7")   # active=DPT (gate, but we ignore)
        clarification.clear_pending(_js("t7"))
        rd = handle_user_query("what is the deadline for this program", "t7")
        self.assertEqual(rd["route"], "deadlines")
        self.assertFalse(_needs_type(rd))
        self.assertIsNone(rd.get("international_info"))
        ra = handle_user_query("who is the advisor for it", "t7")
        self.assertIsNone(ra.get("international_info"))


# ---------------------------------------------------------------------------
# API-level regression — the response must satisfy FastAPI's QueryResponse
# validation (TopicResponseModel requires tool_result). This is the exact
# production failure: the gate response previously lacked tool_result.
# ---------------------------------------------------------------------------

class TestApiApplicantType(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.app import app
        cls.client = TestClient(app)

    def _post(self, query, session_id):
        return self.client.post("/query", json={"query": query, "session_id": session_id})

    def test_gate_is_valid_topic_response(self):
        sid = "api-gate"
        clear_context(sid)
        # establish an active program (deadline route sets active, no gate)
        self._post("what is the deadline for physical therapy", sid)
        resp = self._post("How do I apply to it?", sid)
        self.assertEqual(resp.status_code, 200)          # no ResponseValidationError
        body = resp.json()
        self.assertEqual(body["route"], "application")
        tr = body["tool_result"]
        self.assertTrue(tr["needs_applicant_type"])
        self.assertEqual(tr["applicant_type_choices"], ["domestic", "international"])
        self.assertNotIn("workflow_steps", tr)           # no workflow yet

    def test_international_reply_is_valid_topic_response(self):
        sid = "api-intl"
        clear_context(sid)
        self._post("what is the deadline for public health", sid)
        self._post("How do I apply to it?", sid)          # gate
        resp = self._post("international", sid)            # resume
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["route"], "application")
        self.assertIn("workflow_steps", body["tool_result"])          # program workflow present
        self.assertEqual(body["international_info"]["phone"], "562-985-5555")  # supplement survives

    def test_ack_is_valid_response(self):
        sid = "api-ack"
        clear_context(sid)
        resp = self._post("Actually, I am an international student", sid)
        self.assertEqual(resp.status_code, 200)          # ack also validates


if __name__ == "__main__":
    unittest.main()
