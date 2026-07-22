"""
tests/test_knowledge_pipeline.py
Unit tests for the shared Knowledge Ingestion Pipeline (ingestion/pipeline/).

Infra-free: uses a trivial word-splitting chunker and an in-memory fake index,
so no embedding model, langchain, or Chroma is required. Verifies deterministic
IDs, validation + summary counters, byte-shape of chunk metadata, and idempotent
upsert/prune (Phase 6).

Run: pytest tests/test_knowledge_pipeline.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.config import PipelineConfig
from ingestion.pipeline.documents import KnowledgeDocument
from ingestion.pipeline.ids import chunk_id, document_id_from_url
from ingestion.pipeline.loaders.pages import page_to_document
from ingestion.pipeline.pipeline import KnowledgePipeline
from ingestion.pipeline.ports import Chunk


class _WordChunker:
    """Deterministic test chunker: one chunk per whitespace-split word."""

    def chunk(self, document: KnowledgeDocument):
        out = []
        for i, word in enumerate((document.text or "").split()):
            cid = chunk_id(document.document_id, i)
            out.append(Chunk(
                chunk_id=cid, document_id=document.document_id, index=i,
                text=word, content_hash=f"h{i}",
                metadata={**document.metadata, "chunk_id": cid, "chunk_index": i},
            ))
        return out


class _FakeIndex:
    """In-memory VectorIndex: records build/upsert/delete for assertions."""

    def __init__(self):
        self.store: dict[str, Chunk] = {}
        self.builds = 0

    def build(self, chunks):
        self.builds += 1
        self.store = {c.chunk_id: c for c in chunks}
        return "handle"

    def upsert(self, chunks):
        for c in chunks:
            self.store[c.chunk_id] = c
        return len(chunks)

    def delete(self, chunk_ids):
        n = 0
        for cid in chunk_ids:
            n += 1 if self.store.pop(cid, None) is not None else 0
        return n

    def existing_ids(self):
        return set(self.store)


def _doc(text, url="https://x.com/a", **md):
    return KnowledgeDocument(text=text, source_url=url, content_type="faq", metadata=md)


class TestDeterministicIds(unittest.TestCase):
    def test_chunk_id_matches_legacy_formula(self):
        import hashlib
        url = "https://www.csulb.edu/engineering"
        legacy = f"{hashlib.md5(url.encode()).hexdigest()[:8]}_{7:04d}"
        self.assertEqual(chunk_id(document_id_from_url(url), 7), legacy)


class TestPageLoaderParity(unittest.TestCase):
    def test_legacy_metadata_keys(self):
        page = {"url": "https://x.com", "title": "T", "page_type": "faq",
                "text": "hello world", "program_name": "", "links": []}
        doc = page_to_document(page)
        self.assertEqual(
            sorted(doc.metadata),
            sorted(["title", "url", "page_type", "program_name", "content_category",
                    "discovered_from", "parent_program_url", "workflow_priority",
                    "links_json"]))


class TestPipelineBuild(unittest.TestCase):
    def setUp(self):
        self.index = _FakeIndex()
        self.pipe = KnowledgePipeline(_WordChunker(), self.index, PipelineConfig())

    def test_build_counts_and_summary(self):
        docs = [_doc("alpha beta gamma"), _doc("delta", url="https://x.com/b")]
        handle, summary = self.pipe.run(docs, mode="build")
        self.assertEqual(handle, "handle")
        self.assertEqual(summary.documents_processed, 2)
        self.assertEqual(summary.documents_indexed, 2)
        self.assertEqual(summary.chunks_created, 4)      # 3 + 1
        self.assertEqual(summary.chunks_indexed, 4)
        self.assertEqual(summary.validation_failures, 0)
        self.assertEqual(self.index.builds, 1)
        self.assertIn("Chunks created      : 4", summary.render())

    def test_empty_document_skipped(self):
        _, summary = self.pipe.run([_doc("   "), _doc("one two")], mode="build")
        self.assertEqual(summary.documents_skipped, 1)
        self.assertEqual(summary.documents_indexed, 1)
        self.assertEqual(summary.chunks_created, 2)

    def test_oversized_chunk_dropped(self):
        cfg = PipelineConfig(max_chunk_chars=3)
        pipe = KnowledgePipeline(_WordChunker(), self.index, cfg)
        _, summary = pipe.run([_doc("ok toolongword")], mode="build")
        self.assertEqual(summary.chunks_created, 2)
        self.assertEqual(summary.chunks_indexed, 1)       # "toolongword" dropped
        self.assertEqual(summary.validation_failures, 1)


class TestIdempotentUpsert(unittest.TestCase):
    def test_upsert_then_prune_handles_removed(self):
        index = _FakeIndex()
        pipe = KnowledgePipeline(_WordChunker(), index, PipelineConfig())
        # Initial: 3 chunks
        pipe.run([_doc("a b c")], mode="build")
        self.assertEqual(len(index.existing_ids()), 3)
        # Re-run with fewer words + prune → stale chunk deleted, no full rebuild
        _, summary = pipe.run([_doc("a b")], mode="upsert", prune=True)
        self.assertEqual(index.builds, 1)                 # build not called again
        self.assertEqual(summary.deleted_chunks, 1)
        self.assertEqual(len(index.existing_ids()), 2)


if __name__ == "__main__":
    unittest.main()
