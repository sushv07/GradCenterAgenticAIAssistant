"""
tests/test_retriever_service.py
Phase 4B — Retrieval Abstraction regression tests.

Covers:
  - ChromaRetriever / module-level retrieve(): filters/top_k/min_score map
    correctly onto rag.retriever.retrieve()'s call signature, and raw result
    dicts normalize into the RetrievedChunk shape (text/title/url/score/metadata).
  - tools.rag_tool.search_rag(): migrated call site still returns the exact
    same flat per-result dict shape it always has, despite now sourcing data
    through the Retriever abstraction instead of calling rag.retrieve() directly.

All tests mock the underlying rag.retriever.retrieve() call — no network,
no real ChromaDB store required. (See the Phase 4B output report for a
real-store before/after diff confirming byte-identical results.)

Run from the project root:
    pytest tests/test_retriever_service.py -v
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from retrieval.retriever_service import retrieve, ChromaRetriever


_RAW_CHUNK = {
    "text":               "GPA requirement is 3.0 for doctoral admission.",
    "title":              "Eligibility",
    "url":                "https://www.csulb.edu/eligibility",
    "page_type":          "eligibility",
    "program_name":       "",
    "content_category":   "",
    "discovered_from":    "",
    "parent_program_url": "",
    "workflow_priority":  6,
    "score":              0.81,
    "chunk_id":           "elig_0007",
}


class TestRetrieverServiceNormalization(unittest.TestCase):
    """RetrievedChunk shape: text/title/url/score top-level, everything else in metadata."""

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[_RAW_CHUNK])
    def test_normalizes_to_retrieved_chunk_shape(self, mock_retrieve):
        chunks = retrieve("what gpa do i need")
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(set(chunk.keys()), {"text", "title", "url", "score", "metadata"})
        self.assertEqual(chunk["text"], _RAW_CHUNK["text"])
        self.assertEqual(chunk["title"], _RAW_CHUNK["title"])
        self.assertEqual(chunk["url"], _RAW_CHUNK["url"])
        self.assertEqual(chunk["score"], _RAW_CHUNK["score"])

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[_RAW_CHUNK])
    def test_metadata_carries_everything_else(self, mock_retrieve):
        chunk = retrieve("what gpa do i need")[0]
        expected_metadata = {
            k: v for k, v in _RAW_CHUNK.items()
            if k not in ("text", "title", "url", "score")
        }
        self.assertEqual(chunk["metadata"], expected_metadata)

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_empty_results_pass_through(self, mock_retrieve):
        self.assertEqual(retrieve("xyznonexistentquery"), [])


class TestRetrieverServiceCallMapping(unittest.TestCase):
    """filters/top_k/min_score must map onto rag.retriever.retrieve()'s own kwargs."""

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_no_args_passes_no_extra_kwargs(self, mock_retrieve):
        retrieve("a query")
        mock_retrieve.assert_called_once_with("a query")

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_top_k_maps_to_k(self, mock_retrieve):
        retrieve("a query", top_k=7)
        mock_retrieve.assert_called_once_with("a query", k=7)

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_min_score_passed_through(self, mock_retrieve):
        retrieve("a query", min_score=0.5)
        mock_retrieve.assert_called_once_with("a query", min_score=0.5)

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_page_type_filter_maps_through(self, mock_retrieve):
        retrieve("a query", filters={"page_type": "deadlines"})
        mock_retrieve.assert_called_once_with("a query", page_type="deadlines")

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_program_name_filter_maps_through(self, mock_retrieve):
        retrieve("a query", filters={"program_name": "Physical Therapy (DPT)"})
        mock_retrieve.assert_called_once_with("a query", program_name="Physical Therapy (DPT)")

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_compound_filters_and_top_k_and_min_score(self, mock_retrieve):
        retrieve(
            "a query",
            filters={"page_type": "eligibility", "program_name": "DNP"},
            top_k=2,
            min_score=0.4,
        )
        mock_retrieve.assert_called_once_with(
            "a query", page_type="eligibility", program_name="DNP", k=2, min_score=0.4,
        )

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[])
    def test_unknown_filter_keys_are_ignored(self, mock_retrieve):
        """Mirrors rag.retriever.retrieve()'s own tolerant handling of an unknown
        page_type — an unrecognized filter key is silently dropped, not raised."""
        retrieve("a query", filters={"unknown_key": "whatever"})
        mock_retrieve.assert_called_once_with("a query")


class TestChromaRetrieverDirectly(unittest.TestCase):
    """The Retriever interface should also work via direct instantiation,
    not just the module-level convenience function."""

    @patch("retrieval.retriever_service._chroma_retrieve", return_value=[_RAW_CHUNK])
    def test_instantiated_retriever_matches_module_function(self, mock_retrieve):
        instance_result = ChromaRetriever().retrieve("a query")
        module_result   = retrieve("a query")
        self.assertEqual(instance_result, module_result)


class TestRagToolMigration(unittest.TestCase):
    """tools.rag_tool.search_rag() now sources data through the Retriever
    abstraction — its own public output contract must be unchanged."""

    @patch("tools.rag_tool._retriever_retrieve")
    def test_search_rag_flattens_back_to_original_shape(self, mock_retrieve):
        from retrieval.retriever_service import _to_retrieved_chunk
        mock_retrieve.return_value = [_to_retrieved_chunk(_RAW_CHUNK)]

        from tools.rag_tool import search_rag
        result = search_rag("what gpa do i need", k=3, min_score=0.3)

        self.assertTrue(result["found"])
        self.assertEqual(result["tool"], "rag_tool")
        self.assertIsNone(result["error"])
        self.assertEqual(result["sources"], [_RAW_CHUNK["url"]])
        self.assertEqual(result["top_score"], _RAW_CHUNK["score"])
        self.assertEqual(result["results"], [_RAW_CHUNK])

    @patch("tools.rag_tool._retriever_retrieve")
    def test_search_rag_calls_retriever_with_top_k_and_min_score(self, mock_retrieve):
        mock_retrieve.return_value = []
        from tools.rag_tool import search_rag
        search_rag("a query", k=4, min_score=0.45)
        mock_retrieve.assert_called_once_with("a query", top_k=4, min_score=0.45)

    def test_search_rag_empty_query_unchanged(self):
        from tools.rag_tool import search_rag
        result = search_rag("   ")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "Query is empty.")
        self.assertEqual(result["results"], [])

    @patch("tools.rag_tool._retriever_retrieve", side_effect=RuntimeError("boom"))
    def test_search_rag_retrieval_error_unchanged(self, mock_retrieve):
        from tools.rag_tool import search_rag
        result = search_rag("a query")
        self.assertFalse(result["found"])
        self.assertIn("RAG retrieval failed", result["error"])


if __name__ == "__main__":
    unittest.main()
