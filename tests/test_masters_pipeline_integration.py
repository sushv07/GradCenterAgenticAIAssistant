"""
tests/test_masters_pipeline_integration.py
Phase 4 — master's documents through the SHARED pipeline (offline, deterministic).

Uses the REAL production chunker (RecursiveCharacterChunker) so chunking,
metadata survival, and deterministic chunk IDs are exercised exactly as in
production, plus an in-memory fake index so no embedding model or Chroma (and no
network) is required. Verifies ingestion, metadata preservation, deterministic
chunk IDs, and idempotent upsert.

Run: pytest tests/test_masters_pipeline_integration.py -v
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.loaders.masters import masters_page_to_document
from ingestion.pipeline.pipeline import KnowledgePipeline
from ingestion.pipeline.ports import Chunk
from rag.masters_ingest import ingest_masters_documents
from rag.pipeline_adapters.recursive_chunker import RecursiveCharacterChunker
from rag.pipeline_adapters.wiring import production_config

_LONG = ("Admission requirements for the program include letters of "
         "recommendation, a statement of purpose, and official transcripts. ") * 12


class _FakeIndex:
    """In-memory VectorIndex: upsert/build/delete keyed by chunk_id."""

    def __init__(self):
        self.store: dict[str, Chunk] = {}
        self.builds = 0
        self.handle = "fake"

    def build(self, chunks):
        self.builds += 1
        self.store = {c.chunk_id: c for c in chunks}
        return self.handle

    def upsert(self, chunks):
        for c in chunks:
            self.store[c.chunk_id] = c
        return len(chunks)

    def delete(self, ids):
        n = 0
        for i in ids:
            n += 1 if self.store.pop(i, None) is not None else 0
        return n

    def existing_ids(self):
        return set(self.store)


def _record(url, text=_LONG, programs=("Linguistics (MA)",), category="program_requirements"):
    return {
        "source_url": url, "title": "Admissions", "text": text,
        "program_name": "Linguistics", "degree": "MA", "degree_level": "Masters",
        "department": "", "college": "", "content_type": category,
        "workflow_priority": 3, "parent_program_url": "https://www.csulb.edu/ling",
        "crawl_depth": 1, "associated_programs": list(programs),
    }


def _docs():
    return [masters_page_to_document(_record("https://www.csulb.edu/ling/admissions")),
            masters_page_to_document(_record("https://www.csulb.edu/ling/apply",
                                             category="generic_application"))]


def _pipeline(index):
    return KnowledgePipeline(RecursiveCharacterChunker(production_config()), index, production_config())


class TestPipelineIntegration(unittest.TestCase):
    def test_successful_ingestion(self):
        idx = _FakeIndex()
        _, summary = ingest_masters_documents(_docs(), pipeline=_pipeline(idx), mode="upsert")
        self.assertEqual(summary.documents_processed, 2)
        self.assertEqual(summary.documents_indexed, 2)
        self.assertGreater(summary.chunks_created, 2)          # long text → multiple chunks
        self.assertEqual(summary.validation_failures, 0)
        self.assertEqual(len(idx.store), summary.chunks_indexed)

    def test_metadata_survives_chunking(self):
        idx = _FakeIndex()
        ingest_masters_documents(_docs(), pipeline=_pipeline(idx), mode="upsert")
        keys = ("program_name", "degree", "degree_level", "content_type",
                "source_url", "parent_program_url", "canonical_document_id",
                "chunk_id", "chunk_index")
        for chunk in idx.store.values():
            for k in keys:
                self.assertIn(k, chunk.metadata, f"lost metadata key {k}")
            self.assertEqual(chunk.metadata["degree_level"], "Masters")
            self.assertEqual(chunk.metadata["program_name"], "Linguistics")

    def test_deterministic_chunk_ids(self):
        url = "https://www.csulb.edu/ling/admissions"
        doc_id = hashlib.md5(url.encode()).hexdigest()[:8]
        idx = _FakeIndex()
        ingest_masters_documents([masters_page_to_document(_record(url))],
                                 pipeline=_pipeline(idx), mode="upsert")
        for chunk in idx.store.values():
            self.assertTrue(chunk.chunk_id.startswith(f"{doc_id}_"))
            self.assertEqual(chunk.chunk_id, f"{doc_id}_{chunk.metadata['chunk_index']:04d}")

    def test_idempotent_repeat_ingestion(self):
        idx = _FakeIndex()
        _, s1 = ingest_masters_documents(_docs(), pipeline=_pipeline(idx), mode="upsert")
        n_after_first = len(idx.store)
        ids_first = set(idx.store)
        _, s2 = ingest_masters_documents(_docs(), pipeline=_pipeline(idx), mode="upsert")
        # Same deterministic chunk_ids overwrite in place — no duplicates created.
        self.assertEqual(len(idx.store), n_after_first)
        self.assertEqual(set(idx.store), ids_first)
        self.assertEqual(s1.chunks_indexed, s2.chunks_indexed)

    def test_prune_removes_stale_on_reingest(self):
        idx = _FakeIndex()
        ingest_masters_documents(_docs(), pipeline=_pipeline(idx), mode="upsert")
        before = len(idx.store)
        # Re-ingest only ONE of the two docs with prune → the other's chunks are deleted.
        one = [masters_page_to_document(_record("https://www.csulb.edu/ling/admissions"))]
        _, s = ingest_masters_documents(one, pipeline=_pipeline(idx), mode="upsert", prune=True)
        self.assertLess(len(idx.store), before)
        self.assertGreater(s.deleted_chunks, 0)

    def test_empty_document_skipped_not_indexed(self):
        idx = _FakeIndex()
        empty = masters_page_to_document(_record("https://www.csulb.edu/x", text="   "))
        _, summary = ingest_masters_documents([empty], pipeline=_pipeline(idx), mode="upsert")
        self.assertEqual(summary.documents_skipped, 1)
        self.assertEqual(len(idx.store), 0)


if __name__ == "__main__":
    unittest.main()
