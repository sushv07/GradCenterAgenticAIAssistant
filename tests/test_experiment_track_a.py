"""
tests/test_experiment_track_a.py
Track A Pure RAG baseline tests (Phase P7). Fully offline: FakeEmbedder + a
temporary Chroma collection + MockLLM. No Ollama, no network, no model download.

Run: pytest tests/test_experiment_track_a.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.chunking.chunk import ChunkConfig, chunk_document
from experiments.rag_vs_finetuning.embeddings.embedder import FakeEmbedder
from experiments.rag_vs_finetuning.index.build import build_collection
from experiments.rag_vs_finetuning.projection.models import (
    RetrievalDocument, SourceReference,
)
from experiments.rag_vs_finetuning.track_a.llm import MockLLM
from experiments.rag_vs_finetuning.track_a.models import RunTrace
from experiments.rag_vs_finetuning.track_a.pipeline import ask
from experiments.rag_vs_finetuning.track_a.prompt import PROMPT_VERSION, build_prompt
from experiments.rag_vs_finetuning.track_a.retriever import retrieve

CFG = ChunkConfig()


def _doc(content, doc_id):
    pid, sec = doc_id.split("::")
    return RetrievalDocument(
        document_id=doc_id, program_id=pid, program_level="masters",
        title=pid, section=sec, content=content,
        source_references=[SourceReference(source_id="src-index", source_url="https://x.edu",
                                           content_hash="sha256:idx")],
        volatility="stable", freshness_status="fresh",
        metadata={"canonical_name": pid, "degree_type": "MS"},
        canonical_record_hash="sha256:rec", projection_version="projection-0.1")


def _chunks():
    docs = [_doc("Accountancy fall application deadline: June 01.", "accountancy::application"),
            _doc("Social work contact: Dr. Hansen, email hansen@csulb.edu.", "social-work::contact"),
            _doc("International Affairs program prepares leaders.", "international-affairs::overview")]
    out = []
    for d in docs:
        out.extend(chunk_document(d, CFG))
    return out


def _collection(tmp):
    return build_collection(_chunks(), FakeEmbedder(), persist_dir=Path(tmp) / "chroma",
                            collection_name="test_track_a",
                            versions={"chunking_version": "chunking-0.1"})


class TestRetrieval(unittest.TestCase):
    def test_deterministic_ordering(self):
        with tempfile.TemporaryDirectory() as tmp:
            coll, emb = _collection(tmp), FakeEmbedder()
            a = retrieve("deadline", embedder=emb, collection=coll, top_k=3)
            b = retrieve("deadline", embedder=emb, collection=coll, top_k=3)
            self.assertEqual([c.chunk_id for c in a.retrieved_chunks],
                             [c.chunk_id for c in b.retrieved_chunks])
            sims = [c.similarity_score for c in a.retrieved_chunks]
            self.assertEqual(sims, sorted(sims, reverse=True))

    def test_top_k_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = retrieve("x", embedder=FakeEmbedder(), collection=_collection(tmp), top_k=2)
            self.assertLessEqual(len(r.retrieved_chunks), 2)

    def test_threshold_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = retrieve("x", embedder=FakeEmbedder(), collection=_collection(tmp),
                         top_k=3, threshold=1.1)  # impossible similarity -> empty
            self.assertEqual(r.retrieved_chunks, [])

    def test_metadata_and_provenance_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = retrieve("contact", embedder=FakeEmbedder(), collection=_collection(tmp), top_k=3)
            self.assertTrue(all(c.program_id for c in r.retrieved_chunks))
            self.assertTrue(all(c.source_references[0].source_id == "src-index"
                                for c in r.retrieved_chunks))


class TestPrompt(unittest.TestCase):
    def test_deterministic_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = retrieve("q", embedder=FakeEmbedder(), collection=_collection(tmp), top_k=2)
            self.assertEqual(build_prompt("q", r), build_prompt("q", r))

    def test_prompt_has_citations_and_grounding_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = retrieve("q", embedder=FakeEmbedder(), collection=_collection(tmp), top_k=2)
            _sys, user, full = build_prompt("q", r)
            self.assertIn("chunk_id=", user)          # citation labels present
            self.assertIn("USING ONLY the retrieved context", full)
            self.assertIn("I don't have that information", full)  # insufficient handling


class TestGenerationAndTrace(unittest.TestCase):
    def test_mock_generation_deterministic_config(self):
        llm = MockLLM()
        self.assertEqual(llm.config.temperature, 0.0)
        self.assertEqual(llm.config.top_p, 1.0)

    def test_pipeline_end_to_end_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = ask("contact for social work", embedder=FakeEmbedder(),
                        collection=_collection(tmp), llm=MockLLM(), top_k=3)
            self.assertIsInstance(trace, RunTrace)
            self.assertTrue(trace.retrieved_chunk_ids)
            self.assertEqual(trace.prompt_version, PROMPT_VERSION)
            self.assertTrue(trace.answer)
            self.assertFalse(trace.insufficient_evidence)
            self.assertTrue(trace.citations)          # citations drawn from evidence
            self.assertTrue(all(c.chunk_id in trace.retrieved_chunk_ids for c in trace.citations))

    def test_trace_json_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = ask("q", embedder=FakeEmbedder(), collection=_collection(tmp), llm=MockLLM())
            back = RunTrace.model_validate_json(trace.model_dump_json())
            self.assertEqual(back, trace)


class TestFailureModes(unittest.TestCase):
    def test_no_evidence_refuses_without_llm(self):
        class ExplodingLLM:
            from experiments.rag_vs_finetuning.track_a.models import GenerationConfig
            config = GenerationConfig(model="should-not-be-called")
            def generate(self, system, user):
                raise AssertionError("LLM must not be called when no evidence")
        with tempfile.TemporaryDirectory() as tmp:
            trace = ask("q", embedder=FakeEmbedder(), collection=_collection(tmp),
                        llm=ExplodingLLM(), top_k=3, threshold=1.1)  # force empty retrieval
            self.assertTrue(trace.insufficient_evidence)
            self.assertEqual(trace.citations, [])
            self.assertIn("don't have that information", trace.answer)

    def test_insufficient_llm_answer_yields_no_citations(self):
        canned = "I don't have that information in the provided sources."
        with tempfile.TemporaryDirectory() as tmp:
            trace = ask("q", embedder=FakeEmbedder(), collection=_collection(tmp),
                        llm=MockLLM(canned=canned), top_k=3)
            self.assertTrue(trace.insufficient_evidence)
            self.assertEqual(trace.citations, [])


if __name__ == "__main__":
    unittest.main()
