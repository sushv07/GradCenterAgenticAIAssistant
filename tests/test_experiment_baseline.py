"""
tests/test_experiment_baseline.py
Track A baseline execution + report tests (Phase P7.2). Offline: FakeEmbedder +
temp Chroma + MockLLM; no Ollama, no network.

Run: pytest tests/test_experiment_baseline.py -v
"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.chunking.chunk import ChunkConfig, chunk_document
from experiments.rag_vs_finetuning.embeddings.embedder import FakeEmbedder
from experiments.rag_vs_finetuning.evaluation.execute import (
    OfficialResponse, load_responses, persist_responses, run_track_a, to_response_record,
)
from experiments.rag_vs_finetuning.evaluation.models import EvalCase, EvalDataset
from experiments.rag_vs_finetuning.evaluation.report import (
    build_baseline_report, render_markdown,
)
from experiments.rag_vs_finetuning.index.build import build_collection
from experiments.rag_vs_finetuning.projection.models import (
    RetrievalDocument, SourceReference,
)
from experiments.rag_vs_finetuning.track_a.llm import MockLLM

CFG = ChunkConfig()


def _doc(content, doc_id):
    pid, sec = doc_id.split("::")
    return RetrievalDocument(
        document_id=doc_id, program_id=pid, program_level="masters", title=pid,
        section=sec, content=content,
        source_references=[SourceReference(source_id="src-index", source_url="https://x.edu",
                                           content_hash="sha256:idx")],
        volatility="stable", freshness_status="fresh",
        metadata={"canonical_name": pid, "degree_type": "MS"},
        canonical_record_hash="sha256:rec", projection_version="projection-0.1")


def _collection(tmp):
    docs = [_doc("Contact: hansen@csulb.edu for social work.", "social-work::contact"),
            _doc("International Affairs prepares leaders.", "international-affairs::overview")]
    chunks = []
    for d in docs:
        chunks.extend(chunk_document(d, CFG))
    return build_collection(chunks, FakeEmbedder(), persist_dir=Path(tmp) / "chroma",
                            collection_name="test_baseline", versions={"chunking_version": "chunking-0.1"})


def _dataset():
    cases = [
        EvalCase(id="C1", question="who to contact for social work?", program="social-work",
                 category="contact", difficulty="easy", expected_answer="hansen@csulb.edu",
                 required_section="contact",
                 expected_citation_targets=["social-work::contact::chunk::000"],
                 answerable=True, source_missing=False),
        EvalCase(id="C2", question="is social work STEM designated?", program="social-work",
                 category="source_missing", difficulty="hard", expected_answer=None,
                 answerable=False, source_missing=True, expected_citation_targets=[]),
    ]
    return EvalDataset(dataset_version="t", frozen=True, generated_from="test",
                       case_count=2, dataset_checksum="x", cases=cases)


class TestExecution(unittest.TestCase):
    def test_run_track_a_produces_official_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = run_track_a(_dataset(), embedder=FakeEmbedder(),
                                    collection=_collection(tmp),
                                    llm=MockLLM(), top_k=4, threshold=0.0,
                                    persist_traces=False)
            self.assertEqual(len(responses), 2)
            self.assertTrue(all(isinstance(r, OfficialResponse) for r in responses))
            self.assertEqual(responses[0].question_id, "C1")
            self.assertTrue(responses[0].prompt_version)

    def test_response_serialization_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = run_track_a(_dataset(), embedder=FakeEmbedder(),
                                    collection=_collection(tmp), llm=MockLLM(),
                                    top_k=4, threshold=0.0, persist_traces=False)
            path = Path(tmp) / "resp.jsonl"
            persist_responses(responses, path)
            back = load_responses(path)
            self.assertEqual([r.question_id for r in back], [r.question_id for r in responses])

    def test_to_response_record(self):
        off = OfficialResponse(question_id="C1", question="q", category="contact",
                               program="p", prompt_version="rag_prompt_v1", model="m",
                               answer="a", citations=["p::contact::chunk::000"],
                               timestamp="2026-07-14T00:00:00Z")
        rr = to_response_record(off)
        self.assertEqual(rr.citation_chunk_ids, ["p::contact::chunk::000"])


class TestReport(unittest.TestCase):
    def _responses(self, tmp):
        return run_track_a(_dataset(), embedder=FakeEmbedder(), collection=_collection(tmp),
                           llm=MockLLM(canned="Contact hansen@csulb.edu."), top_k=4,
                           threshold=0.0, persist_traces=False)

    def test_baseline_report_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = build_baseline_report(_dataset(), self._responses(tmp))
            for key in ("overall_metrics", "metrics_by_category", "metrics_by_program",
                        "retrieval_diagnostics", "failure_analysis", "config", "limitations"):
                self.assertIn(key, report)
            self.assertEqual(report["responded_count"], 2)

    def test_metric_aggregation_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = self._responses(tmp)
            # C2 (source_missing) gets a canned substantive answer -> hallucination
            report = build_baseline_report(_dataset(), responses)
            self.assertIn("hallucination", report["failure_analysis"]["counts"])
            self.assertIn("track_a", report["track"])

    def test_render_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = render_markdown(build_baseline_report(_dataset(), self._responses(tmp)))
            self.assertIn("# Track A", md)
            self.assertIn("Overall metrics", md)

    def test_regression_consistency_same_inputs_same_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = self._responses(tmp)
            r1 = build_baseline_report(_dataset(), responses)
            r2 = build_baseline_report(_dataset(), responses)
            self.assertEqual(r1["overall_metrics"], r2["overall_metrics"])
            self.assertEqual(r1["failure_analysis"]["counts"], r2["failure_analysis"]["counts"])


if __name__ == "__main__":
    unittest.main()
