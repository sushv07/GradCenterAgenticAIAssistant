"""
tests/test_experiment_embeddings.py
Embedding-service tests (Phase P6). Default suite uses a deterministic
FakeEmbedder (no downloads, no internet). One integration test uses the real
model only if it is available locally.

Run: pytest tests/test_experiment_embeddings.py -v
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.embeddings.embedder import (
    EmbeddingError, FakeEmbedder, _validate,
)


class TestFakeEmbedder(unittest.TestCase):
    def setUp(self):
        self.emb = FakeEmbedder(dimension=384, normalize=True)

    def test_deterministic_same_text_same_vector(self):
        self.assertEqual(self.emb.embed(["hello"]), self.emb.embed(["hello"]))

    def test_input_ordering_and_count_preserved(self):
        v = self.emb.embed(["a", "b", "c"])
        self.assertEqual(len(v), 3)
        self.assertNotEqual(v[0], v[1])

    def test_dimension(self):
        self.assertTrue(all(len(x) == 384 for x in self.emb.embed(["x", "y"])))

    def test_normalization_unit_norm(self):
        v = self.emb.embed(["something"])[0]
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0, places=5)

    def test_empty_content_fails(self):
        with self.assertRaises(EmbeddingError):
            self.emb.embed(["ok", "  "])

    def test_metadata_capture(self):
        info = self.emb.info
        self.assertEqual(info.dimension, 384)
        self.assertTrue(info.normalize)
        self.assertTrue(info.model_id)


class TestValidation(unittest.TestCase):
    def test_nan_vector_fails(self):
        with self.assertRaises(EmbeddingError):
            _validate([[float("nan")] * 3], dimension=3)

    def test_inf_vector_fails(self):
        with self.assertRaises(EmbeddingError):
            _validate([[float("inf")] * 3], dimension=3)

    def test_wrong_dimension_fails(self):
        with self.assertRaises(EmbeddingError):
            _validate([[0.1, 0.2]], dimension=3)


def _model_available() -> bool:
    try:
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        SentenceTransformer("all-MiniLM-L6-v2")
        return True
    except Exception:
        return False


class TestRealModelIntegration(unittest.TestCase):
    @unittest.skipUnless(_model_available(), "all-MiniLM-L6-v2 not available locally")
    def test_real_embedder_dimension_and_norm(self):
        from experiments.rag_vs_finetuning.embeddings.embedder import SentenceTransformerEmbedder
        emb = SentenceTransformerEmbedder(model_id="all-MiniLM-L6-v2", device="cpu", normalize=True)
        self.assertEqual(emb.info.dimension, 384)
        vecs = emb.embed(["admissions overview", "contact information"])
        self.assertEqual(len(vecs), 2)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in vecs[0])), 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
