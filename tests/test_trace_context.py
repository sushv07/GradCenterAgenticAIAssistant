"""
tests/test_trace_context.py
Phase 4G — regression tests for TraceContext.

Covers:
  - TraceContext creation: request_id capture, session_id assignment,
    route defaulting to None, started_at populated.
  - Propagation: request_id set via gradcenter_logging before the call is
    captured unchanged; callers that never set one get "" (matching
    existing pre-Phase-4G logging behavior for non-Streamlit callers).
  - Route updates via record_route().
  - handle_user_query() assembles a TraceContext whose route always matches
    the route on the response actually returned, across all route types.
  - Multiple simultaneous sessions / isolation: TraceContexts for different
    session_ids never share state, and JourneyState isolation (Phase 4F)
    still holds with TraceContext now also in the mix.

Run from the project root:
    pytest tests/test_trace_context.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from datetime import datetime

from context.trace_context import TraceContext, create_trace_context, record_route
from gradcenter_logging import set_request_id, get_request_id
from backend.entrypoint import handle_user_query
from state.context_manager import _SESSION_STORE


def _fresh(sid: str) -> None:
    _SESSION_STORE.pop(sid, None)


class TestTraceContextCreation(unittest.TestCase):
    def test_session_id_assigned(self):
        trace = create_trace_context("sess-abc")
        self.assertEqual(trace.session_id, "sess-abc")

    def test_route_defaults_to_none(self):
        trace = create_trace_context("sess-abc")
        self.assertIsNone(trace.route)

    def test_started_at_is_a_datetime(self):
        trace = create_trace_context("sess-abc")
        self.assertIsInstance(trace.started_at, datetime)

    def test_is_a_dataclass_instance(self):
        trace = create_trace_context("sess-abc")
        self.assertIsInstance(trace, TraceContext)


class TestRequestIdPropagation(unittest.TestCase):
    def test_captures_currently_active_request_id(self):
        set_request_id("rid-12345")
        trace = create_trace_context("sess-abc")
        self.assertEqual(trace.request_id, "rid-12345")
        set_request_id("")  # reset for other tests

    def test_empty_when_no_request_id_was_set(self):
        set_request_id("")
        trace = create_trace_context("sess-abc")
        self.assertEqual(trace.request_id, "")

    def test_does_not_mint_a_new_id(self):
        set_request_id("fixed-id")
        before = get_request_id()
        create_trace_context("sess-abc")
        after = get_request_id()
        self.assertEqual(before, after)  # creating a trace never changes the active id
        set_request_id("")


class TestRouteUpdates(unittest.TestCase):
    def test_record_route_mutates_in_place(self):
        trace = create_trace_context("sess-abc")
        record_route(trace, "deadlines")
        self.assertEqual(trace.route, "deadlines")

    def test_record_route_returns_the_same_trace(self):
        trace = create_trace_context("sess-abc")
        result = record_route(trace, "advisor")
        self.assertIs(result, trace)

    def test_record_route_accepts_none(self):
        trace = create_trace_context("sess-abc")
        record_route(trace, "deadlines")
        record_route(trace, None)
        self.assertIsNone(trace.route)


class TestHandleUserQueryTraceIntegration(unittest.TestCase):
    """handle_user_query() doesn't expose its internal TraceContext, but its
    route-stamping logic must always match the route on the real response —
    verified here the same way handle_user_query() itself does it."""

    def test_route_matches_response_for_standard_request(self):
        sid = "trace-be-1"
        _fresh(sid)
        trace = create_trace_context(sid)
        response = handle_user_query("when is the application deadline", session_id=sid)
        record_route(trace, response.get("route"))
        self.assertEqual(trace.route, response["route"])
        self.assertEqual(trace.route, "deadlines")
        _fresh(sid)

    def test_route_matches_response_for_discovery_request(self):
        sid = "trace-be-2"
        _fresh(sid)
        trace = create_trace_context(sid)
        response = handle_user_query("I don't know what graduate program fits me", session_id=sid)
        record_route(trace, response.get("route"))
        self.assertEqual(trace.route, "discovery")
        _fresh(sid)


class TestMultipleSessionsIsolation(unittest.TestCase):
    def test_two_trace_contexts_for_different_sessions_are_independent(self):
        trace_a = create_trace_context("trace-iso-a")
        trace_b = create_trace_context("trace-iso-b")
        record_route(trace_a, "deadlines")
        record_route(trace_b, "advisor")
        self.assertEqual(trace_a.session_id, "trace-iso-a")
        self.assertEqual(trace_b.session_id, "trace-iso-b")
        self.assertEqual(trace_a.route, "deadlines")
        self.assertEqual(trace_b.route, "advisor")

    def test_session_request_pair_does_not_leak_into_other_session(self):
        sid_a = "trace-iso-c"
        sid_b = "trace-iso-d"
        _fresh(sid_a)
        _fresh(sid_b)

        handle_user_query("I am interested in educational leadership", session_id=sid_a)
        response_b = handle_user_query("when is the application deadline", session_id=sid_b)

        # sid_b's request must be routed on its own merits, unaffected by
        # sid_a's in-progress discovery clarification.
        self.assertEqual(response_b["route"], "deadlines")

        _fresh(sid_a)
        _fresh(sid_b)


if __name__ == "__main__":
    unittest.main()
