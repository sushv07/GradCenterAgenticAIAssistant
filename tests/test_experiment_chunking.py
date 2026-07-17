"""
tests/test_experiment_chunking.py
Deterministic chunking tests (Phase P6). Offline; no model/Chroma/LangChain.

Run: pytest tests/test_experiment_chunking.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.chunking.chunk import (
    ChunkConfig, aggregate_chunk_checksum, chunk_document, chunk_documents,
)
from experiments.rag_vs_finetuning.chunking.models import RetrievalChunk
from experiments.rag_vs_finetuning.chunking.run import run_chunking
from experiments.rag_vs_finetuning.projection.models import (
    RetrievalDocument, SourceReference,
)

CFG = ChunkConfig()


def _doc(content, *, section="overview", doc_id=None):
    return RetrievalDocument(
        document_id=doc_id or f"p::{section}", program_id="p", program_level="masters",
        title="P", section=section, content=content,
        source_references=[SourceReference(source_id="s1", source_url="https://x.edu",
                                           content_hash="sha256:a")],
        volatility="stable", freshness_status="fresh",
        metadata={"canonical_name": "P", "degree_type": "MS"},
        canonical_record_hash="sha256:rec", projection_version="projection-0.1")


class TestChunkModel(unittest.TestCase):
    def test_round_trip_and_required_fields(self):
        c = chunk_document(_doc("short overview text"), CFG)[0]
        back = RetrievalChunk.model_validate_json(c.model_dump_json())
        self.assertEqual(back, c)
        for f in ("chunk_id", "document_id", "program_id", "content_hash", "chunking_version"):
            self.assertTrue(getattr(c, f))

    def test_content_hash_stable(self):
        a = chunk_document(_doc("same text"), CFG)[0]
        b = chunk_document(_doc("same text"), CFG)[0]
        self.assertEqual(a.content_hash, b.content_hash)

    def test_model_module_has_no_chroma_import(self):
        src = (Path(__file__).parent.parent / "experiments/rag_vs_finetuning/chunking/models.py").read_text()
        self.assertNotIn("chromadb", src)
        self.assertNotIn("langchain", src)


class TestChunkingPolicy(unittest.TestCase):
    def test_short_document_one_chunk(self):
        chunks = chunk_document(_doc("a" * 200), CFG)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_id, "p::overview::chunk::000")
        self.assertEqual((chunks[0].character_start, chunks[0].character_end), (0, 200))

    def test_long_document_splits_with_overlap(self):
        chunks = chunk_document(_doc("a" * 1100), CFG)  # 500 size, 75 overlap
        self.assertGreater(len(chunks), 1)
        # overlap: window step = size - overlap = 425
        self.assertEqual(chunks[0].character_end, 500)
        self.assertEqual(chunks[1].character_start, 425)
        self.assertTrue(all(c.content for c in chunks))  # no empty chunks

    def test_stable_ids_offsets_ordering(self):
        a = chunk_document(_doc("a" * 1100), CFG)
        b = chunk_document(_doc("a" * 1100), CFG)
        self.assertEqual([c.chunk_id for c in a], [c.chunk_id for c in b])
        self.assertEqual([(c.character_start, c.character_end) for c in a],
                         [(c.character_start, c.character_end) for c in b])

    def test_application_term_and_deadline_kept_together(self):
        content = "Fall application deadline: June 01; accept/decline deadline: August 01. Spring: Not Accepting."
        chunks = chunk_document(_doc(content, section="application", doc_id="p::application"), CFG)
        self.assertEqual(len(chunks), 1)  # fits -> one chunk, deadline not split from term
        self.assertIn("June 01", chunks[0].content)
        self.assertIn("Not Accepting", chunks[0].content)

    def test_contact_block_kept_together(self):
        content = "Program office/advisor: Dept. Email: x@csulb.edu. Phone: 562-000-0000."
        chunks = chunk_document(_doc(content, section="contact", doc_id="p::contact"), CFG)
        self.assertEqual(len(chunks), 1)
        self.assertIn("Email", chunks[0].content)
        self.assertIn("Phone", chunks[0].content)

    def test_parent_provenance_preserved(self):
        c = chunk_document(_doc("text", doc_id="acct::overview"), CFG)[0]
        self.assertEqual(c.document_id, "acct::overview")
        self.assertEqual(c.source_references[0].source_id, "s1")

    def test_identical_input_identical_checksum(self):
        docs = [_doc("x" * 100, doc_id="a::overview"), _doc("y" * 100, doc_id="b::overview")]
        self.assertEqual(aggregate_chunk_checksum(chunk_documents(docs, CFG)),
                         aggregate_chunk_checksum(chunk_documents(docs, CFG)))


class TestChunkRun(unittest.TestCase):
    def _mini_data_root(self, tmp):
        dr = Path(tmp)
        (dr / "projected_documents").mkdir(parents=True)
        (dr / "manifests").mkdir(parents=True)
        (dr / "projected_documents" / "documents.jsonl").write_text(
            _doc("some overview content", doc_id="p::overview").model_dump_json() + "\n")
        (dr / "projection_report.json").write_text(json.dumps({
            "projection_version": "projection-0.1",
            "aggregate_projection_checksum": "sha256:proj"}))
        return dr

    def test_changed_config_same_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            dr = self._mini_data_root(tmp)
            run_chunking(dr, ChunkConfig(chunk_size_characters=500))
            with self.assertRaises(ValueError):
                run_chunking(dr, ChunkConfig(chunk_size_characters=10))  # same version, different size

    def test_identical_rerun_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            dr = self._mini_data_root(tmp)
            m1 = run_chunking(dr)
            m2 = run_chunking(dr)
            self.assertEqual(m1["aggregate_chunk_checksum"], m2["aggregate_chunk_checksum"])


if __name__ == "__main__":
    unittest.main()
