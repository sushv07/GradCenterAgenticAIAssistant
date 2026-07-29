"""
tests/test_tracing.py
Phase 2 observability — OpenTelemetry tracing.

Verifies the additive tracing layer captures the correct span hierarchy and
correlates traces with the existing NDJSON logs, WITHOUT requiring a running
Collector or Tempo — spans are captured in-process via an InMemorySpanExporter.

Covered:
  * span hierarchy for a single-intent request (pipeline.request → route.decide)
  * full composite hierarchy (coordinator.run → planner/agents → rag.retrieve →
    vectordb.query → synthesizer.compose), proving automatic contextvar nesting
  * log ↔ trace correlation (every log line emitted inside a span carries
    trace_id/span_id alongside the existing request_id)
  * the llm.generate span wraps the Ollama call (LLM path, mocked)
  * graceful no-op: span()/set_attributes() are safe when tracing is disabled
  * existing behavior is unchanged (responses still valid)

Run: pytest tests/test_tracing.py -v
"""
from __future__ import annotations

import io
import json
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from telemetry import tracing
from state.context_manager import clear_context

COMPOSITE = ("I am a registered nurse seeking a doctoral nursing practice degree. "
             "Recommend a program, tell me who the advisor is, and explain how an "
             "international student should apply.")


def _parent_name(span, by_id):
    p = span.parent
    return by_id[p.span_id].name if (p and p.span_id in by_id) else "ROOT"


class _TracingCase(unittest.TestCase):
    """Base: install an in-memory exporter once for the process. init_tracing is
    idempotent, so the first test to run wins; all share the same exporter,
    which we clear per-test."""
    exporter: InMemorySpanExporter

    @classmethod
    def setUpClass(cls):
        cls.exporter = InMemorySpanExporter()
        tracing.init_tracing(span_exporter=cls.exporter, force=True)

    def setUp(self):
        self.exporter.clear()

    def _spans(self):
        spans = self.exporter.get_finished_spans()
        return spans, {s.context.span_id: s for s in spans}


class TestSpanHierarchy(_TracingCase):
    def test_single_intent_hierarchy(self):
        from backend.entrypoint import handle_user_query
        clear_context("tr-single")
        r = handle_user_query("who is the advisor for physical therapy", "tr-single")
        self.assertEqual(r["route"], "advisor")            # behavior unchanged
        spans, by_id = self._spans()
        names = {s.name for s in spans}
        self.assertIn("pipeline.request", names)
        self.assertIn("route.decide", names)
        # route.decide nests under the root pipeline span.
        rd = next(s for s in spans if s.name == "route.decide")
        self.assertEqual(_parent_name(rd, by_id), "pipeline.request")
        # root has no in-trace parent
        root = next(s for s in spans if s.name == "pipeline.request")
        self.assertEqual(_parent_name(root, by_id), "ROOT")

    def test_composite_full_hierarchy(self):
        from backend.entrypoint import handle_user_query
        clear_context("tr-comp")
        with mock.patch("config.settings.ENABLE_MULTI_AGENT_COORDINATOR", True):
            r = handle_user_query(COMPOSITE, "tr-comp")
        self.assertEqual(r["route"], "composite")          # behavior unchanged
        spans, by_id = self._spans()
        names = {s.name for s in spans}
        # every composite-path span type is present
        for expected in {"pipeline.request", "coordinator.run", "planner",
                         "discovery", "advisor", "application",
                         "rag.retrieve", "vectordb.query", "synthesizer.compose"}:
            self.assertIn(expected, names, f"missing span: {expected}")
        # structural checks
        parent_of = lambda n: _parent_name(next(s for s in spans if s.name == n), by_id)
        self.assertEqual(parent_of("coordinator.run"), "pipeline.request")
        self.assertEqual(parent_of("planner"), "coordinator.run")
        self.assertEqual(parent_of("synthesizer.compose"), "coordinator.run")
        # vectordb.query is a child of rag.retrieve wherever it occurs
        for vq in [s for s in spans if s.name == "vectordb.query"]:
            self.assertEqual(_parent_name(vq, by_id), "rag.retrieve")

    def test_llm_generate_span_wraps_ollama(self):
        # Drive the LLM synthesis path directly with the model enabled and the
        # network call mocked, so the llm.generate span is produced offline.
        import agents.llm_synthesizer as llm
        with mock.patch.object(llm, "_ENABLED", True), \
             mock.patch.object(llm, "_call_ollama", return_value="A grounded answer."), \
             mock.patch.object(llm, "_validate", return_value={"answer": "A grounded answer.",
                                                               "confidence": "high"}):
            out = llm.synthesize_answer("q", {"answer": "ctx"}, "f.json",
                                        source_url="https://www.csulb.edu/x")
        self.assertIsNotNone(out)
        names = {s.name for s in self.exporter.get_finished_spans()}
        self.assertIn("llm.generate", names)


class TestLogCorrelation(_TracingCase):
    def test_logs_carry_trace_and_span_ids(self):
        from backend.entrypoint import handle_user_query
        from gradcenter_logging import _logger

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        _logger.addHandler(handler)
        try:
            clear_context("tr-log")
            handle_user_query("who is the advisor for physical therapy", "tr-log")
        finally:
            _logger.removeHandler(handler)

        lines = [json.loads(l) for l in buf.getvalue().splitlines()
                 if l.strip().startswith("{")]
        self.assertTrue(lines, "expected NDJSON log lines")
        traced_lines = [l for l in lines if l.get("trace_id")]
        # Events emitted inside the pipeline span (request.started/completed,
        # route.decision, retrieval.*) must carry correlation ids.
        self.assertTrue(traced_lines, "no log line carried a trace_id")
        sample = traced_lines[0]
        self.assertEqual(len(sample["trace_id"]), 32)      # W3C hex
        self.assertEqual(len(sample["span_id"]), 16)
        self.assertIn("request_id", sample)                # existing id preserved


class TestGracefulNoop(unittest.TestCase):
    """span()/set_attributes()/current_trace_ids() must be safe no-ops when no
    span is active — this is what guarantees zero behavior change with tracing
    off. (Uses the API directly; does not depend on a provider being set.)"""

    def test_span_contextmanager_is_safe(self):
        with tracing.span("adhoc", attributes={"k": "v"}) as sp:
            # yields either a span or None; either way, no exception
            _ = sp
        tracing.set_attributes(foo="bar")                  # no active span → no-op

    def test_current_trace_ids_empty_without_span(self):
        # Outside any span, correlation returns nothing → logs stay unchanged.
        self.assertEqual(tracing.current_trace_ids(), {})


if __name__ == "__main__":
    unittest.main()
