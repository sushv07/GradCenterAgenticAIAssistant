"""
tests/test_faq_synthesis.py
Phase 4.3 — grounded FAQ conversational synthesis (runtime answer generation).

Offline/network-free. Mocks the retriever and the Ollama call so no store or
model is required. Verifies the flag-gated FAQ synthesis path in the answer
workflow reuses the existing grounded synthesizer + citation validation, covers
the four evidence cases, and falls back deterministically.

Run: pytest tests/test_faq_synthesis.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
import agents.llm_synthesizer as llm

PORTAL = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"
FAQ_URL = f"{PORTAL}#accordion-2001"
SUP_URL = "https://www.csulb.edu/enrollment-services/transcripts"


def _faq_chunk(**kw):
    base = {"text": "Submit official transcripts to Enrollment Services.",
            "url": FAQ_URL, "source_url": FAQ_URL, "page_type": "faq",
            "faq_question": "How do I submit transcripts?", "category": "Graduate Admissions",
            "is_supporting_page": False, "score": 0.8}
    base.update(kw)
    return base


def _sup_chunk(**kw):
    base = {"text": "Transcripts must be sent by your prior institution.",
            "url": SUP_URL, "source_url": SUP_URL, "page_type": "faq_supporting",
            "title": "Transcript Requirements", "is_supporting_page": True, "score": 0.6}
    base.update(kw)
    return base


class _FaqSynthCase(unittest.TestCase):
    """Runs orchestrator._faq_synthesized_result with the flag ON, the retriever
    returning `chunks`, and the Ollama call mocked to `content`."""
    def _run(self, chunks, content='{"answer": "Send transcripts to Enrollment Services.", "confidence": "high"}',
             enabled=True):
        with mock.patch("config.settings.FAQ_SYNTHESIS_ENABLED", enabled), \
             mock.patch("config.settings.FAQ_TOP_K", 6), \
             mock.patch("config.settings.FAQ_MIN_SCORE", 0.3), \
             mock.patch("config.settings.FAQ_CONTEXT_MAX_CHARS", 6000), \
             mock.patch("rag.retriever.retrieve", return_value=chunks), \
             mock.patch.object(llm, "_ENABLED", True), \
             mock.patch.object(llm, "_call_ollama", return_value=content):
            return orchestrator._faq_synthesized_result("how do I submit transcripts", "s1")


class TestEvidenceCases(_FaqSynthCase):
    def test_faq_plus_supporting(self):
        r = self._run([_faq_chunk(), _sup_chunk()])
        self.assertIsNotNone(r)
        self.assertEqual(r["answer_type"], "faq_synthesized")
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["source_url"], FAQ_URL)          # top FAQ deep-link

    def test_faq_only(self):
        r = self._run([_faq_chunk()])
        self.assertEqual(r["answer_type"], "faq_synthesized")
        self.assertEqual(r["source_url"], FAQ_URL)

    def test_supporting_only(self):
        r = self._run([_sup_chunk()])
        self.assertIsNotNone(r)
        self.assertEqual(r["source_url"], SUP_URL)          # falls back to supporting url

    def test_no_evidence_returns_none(self):
        self.assertIsNone(self._run([]))                    # case 4 → existing fallback


class TestCitationAndFallback(_FaqSynthCase):
    def test_fabricated_url_rejected_falls_back(self):
        # Answer cites a URL absent from the evidence → _validate rejects → None.
        bad = '{"answer": "See https://evil.example.com/fake", "confidence": "high"}'
        self.assertIsNone(self._run([_faq_chunk()], content=bad))

    def test_real_source_url_preserved(self):
        good = f'{{"answer": "Details at {SUP_URL}", "confidence": "high"}}'
        r = self._run([_faq_chunk(), _sup_chunk()], content=good)
        self.assertIsNotNone(r)                             # URL is in evidence → accepted
        self.assertIn(SUP_URL, r["answer"])

    def test_llm_disabled_returns_none(self):
        with mock.patch("config.settings.FAQ_SYNTHESIS_ENABLED", True), \
             mock.patch("rag.retriever.retrieve", return_value=[_faq_chunk()]), \
             mock.patch.object(llm, "_ENABLED", False):     # synthesizer no-op → None
            self.assertIsNone(orchestrator._faq_synthesized_result("q", "s"))

    def test_feature_flag_disabled_skips_retrieval(self):
        # Flag off → no retrieval attempted at all → None.
        spy = mock.Mock()
        with mock.patch("config.settings.FAQ_SYNTHESIS_ENABLED", False), \
             mock.patch("rag.retriever.retrieve", spy):
            self.assertIsNone(orchestrator._faq_synthesized_result("q", "s"))
        spy.assert_not_called()


class TestContextAssembly(unittest.TestCase):
    def test_splits_faq_and_supporting_and_dedupes(self):
        chunks = [_faq_chunk(), _sup_chunk(), _sup_chunk()]  # duplicate supporting url
        ctx, top = orchestrator._build_faq_context(chunks, 6000)
        self.assertEqual(len(ctx["faqs"]), 1)
        self.assertEqual(len(ctx["supporting_evidence"]), 1)  # deduped by source_url
        self.assertEqual(top, FAQ_URL)
        self.assertEqual(ctx["faqs"][0]["question"], "How do I submit transcripts?")
        self.assertEqual(ctx["supporting_evidence"][0]["source_url"], SUP_URL)

    def test_respects_char_budget(self):
        big = _faq_chunk(text="x" * 500, source_url=FAQ_URL)
        big2 = _sup_chunk(text="y" * 500, source_url=SUP_URL)
        ctx, _ = orchestrator._build_faq_context([big, big2], max_chars=300)
        total = len(ctx["faqs"]) + len(ctx["supporting_evidence"])
        self.assertEqual(total, 1)                           # budget stops after first


class TestRunAnswerIntegration(unittest.TestCase):
    def test_run_answer_uses_faq_result_when_available(self):
        faq_result = {"answer": "A", "confidence": "high", "answer_type": "faq_synthesized",
                      "source_file": "", "source_url": FAQ_URL}
        with mock.patch.object(orchestrator, "_faq_synthesized_result", return_value=faq_result), \
             mock.patch.object(orchestrator, "handle_query") as hq:
            out = orchestrator._run_answer("q", "s")
        self.assertEqual(out["answer_type"], "faq_synthesized")
        hq.assert_not_called()                               # keyword path skipped

    def test_run_answer_falls_through_when_faq_none(self):
        with mock.patch.object(orchestrator, "_faq_synthesized_result", return_value=None), \
             mock.patch.object(orchestrator, "handle_query",
                               return_value={"results": [], "next_steps": []}) as hq:
            orchestrator._run_answer("q", "s")
        hq.assert_called_once()                              # existing keyword path used


if __name__ == "__main__":
    unittest.main()
