"""
tests/test_production_build_masters.py
Phase 5 — master's source in the production build path (offline, deterministic).

Verifies that get_or_build_store()'s rebuild appends master's knowledge to the
SAME build (one unified collection), gated by config, without touching the shared
pipeline. No network: sources are mocked, and the end-to-end acquisition path is
exercised with a synthetic index + fake fetcher.

Run: pytest tests/test_production_build_masters.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.documents import Document

from ingestion.pipeline.documents import KnowledgeDocument
import rag.masters_ingest as mi

B = "https://www.csulb.edu"

# Minimal synthetic master's directory: one program card (name + degree + url).
_INDEX = f'<html><body><table><tr><td>' \
         f'<a href="{B}/alpha">Alpha (MS)</a></td></tr></table></body></html>'
_SITE = {
    f"{B}/alpha": f'<html><head><title>Alpha</title></head><body><main>'
                  f'<a href="{B}/alpha/admissions">admission requirements</a></main></body></html>',
    f"{B}/alpha/admissions": '<html><head><title>Admissions</title></head><body><main>'
                             '<p>Admission requirements: letters of recommendation and a '
                             'statement of purpose for the graduate program. ' * 8 + '</p></main></body></html>',
}


def _fetch(url):
    return _SITE.get(url)


class TestMastersBuildHook(unittest.TestCase):
    def test_disabled_by_default_returns_empty(self):
        # default flag is off → no master's documents, base build unchanged
        self.assertEqual(mi.masters_build_documents(enabled=False), [])

    def test_enabled_end_to_end_offline(self):
        docs = mi.masters_build_documents(enabled=True, index_html=_INDEX, fetch_fn=_fetch)
        self.assertTrue(docs)                                   # produced chunks
        self.assertTrue(all(isinstance(d, Document) for d in docs))
        # metadata carried through to LangChain Documents
        md = docs[0].metadata
        self.assertEqual(md["page_type"], "masters_program")
        self.assertIn("chunk_id", md)
        self.assertIn("source_url", md)

    def test_fail_safe_on_acquisition_error(self):
        with patch.object(mi, "acquire_masters_documents", side_effect=RuntimeError("boom")):
            self.assertEqual(mi.masters_build_documents(enabled=True), [])   # never raises

    def test_config_toggle(self):
        with patch.object(mi, "acquire_masters_documents", return_value=[
                KnowledgeDocument(text="x " * 200, source_url=f"{B}/p", content_type="faq")]):
            self.assertEqual(mi.masters_build_documents(enabled=False), [])
            self.assertTrue(mi.masters_build_documents(enabled=True))


class TestUnifiedProductionBuild(unittest.TestCase):
    def setUp(self):
        import rag.store as store
        self.store = store
        store._STORE = None
        store._STORE_VALIDATED = False

    def _run_rebuild(self, masters_docs):
        existing = Document(page_content="doctoral eligibility info", metadata={
            "url": f"{B}/doctoral", "page_type": "eligibility", "chunk_id": "d_0000"})
        captured = {}

        def _capture(documents):
            captured["docs"] = documents
            return "STORE"

        with patch("rag.ingestion.ingest_pages", return_value=[{"url": f"{B}/d", "text": "t"}]), \
             patch("rag.chunking.chunk_documents", return_value=[existing]), \
             patch("rag.masters_ingest.masters_build_documents", return_value=masters_docs), \
             patch.object(self.store, "build_vector_store", side_effect=_capture):
            result = self.store.get_or_build_store(force_rebuild=True)
        return result, captured.get("docs"), existing

    def test_build_unifies_existing_and_masters(self):
        masters = [Document(page_content="masters admissions", metadata={
            "url": f"{B}/alpha/admissions", "page_type": "masters_program", "chunk_id": "a_0000"})]
        result, docs, existing = self._run_rebuild(masters)
        self.assertEqual(result, "STORE")
        self.assertEqual(len(docs), 2)
        self.assertIn(existing, docs)                          # existing source preserved
        self.assertIn(masters[0], docs)                        # master's added
        types = {d.metadata["page_type"] for d in docs}
        self.assertEqual(types, {"eligibility", "masters_program"})  # unified collection

    def test_build_unchanged_when_masters_disabled(self):
        # masters_build_documents returns [] (disabled default) → only existing docs
        result, docs, existing = self._run_rebuild([])
        self.assertEqual(docs, [existing])


if __name__ == "__main__":
    unittest.main()
