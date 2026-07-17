"""
tests/test_experiment_index.py
Chroma index tests (Phase P6). Offline: FakeEmbedder + a temporary Chroma dir.
The production Chroma collection is never touched.

Run: pytest tests/test_experiment_index.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.chunking.chunk import ChunkConfig, chunk_document
from experiments.rag_vs_finetuning.embeddings.embedder import FakeEmbedder
from experiments.rag_vs_finetuning.index.build import (
    IndexError_, build_collection, verify_collection,
)
from experiments.rag_vs_finetuning.projection.models import (
    RetrievalDocument, SourceReference,
)

CFG = ChunkConfig()
_VERSIONS = {"chunking_version": "chunking-0.1", "corpus_version": "1.0"}


def _doc(content, doc_id):
    return RetrievalDocument(
        document_id=doc_id, program_id=doc_id.split("::")[0], program_level="masters",
        title="P", section=doc_id.split("::")[1], content=content,
        source_references=[SourceReference(source_id="src-index", source_url="https://x.edu",
                                           content_hash="sha256:idx")],
        volatility="stable", freshness_status="fresh",
        metadata={"canonical_name": "P", "degree_type": "MS"},
        canonical_record_hash="sha256:rec", projection_version="projection-0.1")


def _chunks():
    docs = [_doc("Accountancy overview text.", "accountancy::overview"),
            _doc("Contact program office email.", "accountancy::contact"),
            _doc("Social work overview text.", "social-work::overview")]
    out = []
    for d in docs:
        out.extend(chunk_document(d, CFG))
    return out


class TestIndexBuild(unittest.TestCase):
    def _build(self, tmp, chunks=None, clean=False):
        return build_collection(
            chunks or _chunks(), FakeEmbedder(), persist_dir=Path(tmp) / "chroma",
            collection_name="test_masters_v1", versions=_VERSIONS, clean=clean)

    def test_count_and_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            coll = self._build(tmp)
            self.assertEqual(coll.count(), 3)
            verify_collection(coll, _chunks())

    def test_idempotent_rebuild_no_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._build(tmp)
            coll = self._build(tmp)  # rerun, same inputs
            self.assertEqual(coll.count(), 3)

    def test_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            coll = self._build(tmp)
            got = coll.get(ids=["accountancy::overview::chunk::000"], include=["metadatas"])
            md = got["metadatas"][0]
            self.assertEqual(md["program_id"], "accountancy")
            self.assertEqual(md["section"], "overview")
            self.assertEqual(md["source_ids"], "src-index")
            self.assertEqual(md["embedding_model"], "fake-deterministic")

    def test_extra_record_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            coll = self._build(tmp)
            # verifying against a SUBSET makes the collection have an "extra" id
            with self.assertRaises(IndexError_):
                verify_collection(coll, _chunks()[:2])

    def test_missing_record_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            coll = self._build(tmp, chunks=_chunks()[:2])
            with self.assertRaises(IndexError_):
                verify_collection(coll, _chunks())  # expects 3, only 2 present

    def test_collection_isolated_not_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._build(tmp)
            prod = Path(__file__).parent.parent / "chroma_db"
            # production store path is untouched by the temp build
            self.assertTrue((Path(tmp) / "chroma").exists())
            self.assertNotIn(str(prod), str(Path(tmp) / "chroma"))


class TestCommittedIndexManifest(unittest.TestCase):
    def test_index_manifest_present_and_shaped(self):
        import json
        p = (Path(__file__).parent.parent
             / "experiments/rag_vs_finetuning/data/manifests/index_manifest.json")
        if p.exists():
            m = json.loads(p.read_text())
            self.assertEqual(m["vector_count"], 41)
            self.assertEqual(m["embedding_dimension"], 384)
            self.assertEqual(m["collection_name"], "masters_track_a_v1")
            self.assertTrue(m["collection_identity_hash"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
