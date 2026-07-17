"""
tests/test_experiment_evaluation.py
Frozen evaluation benchmark tests (Phase P7.1). Offline; deterministic; no LLM.

Run: pytest tests/test_experiment_evaluation.py -v
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.evaluation.dataset import (
    DATASET_PATH, compute_checksum, load_chunk_ids, load_dataset, validate_dataset,
)
from experiments.rag_vs_finetuning.evaluation.metrics import aggregate, score_case
from experiments.rag_vs_finetuning.evaluation.models import (
    EvalCase, EvalDataset, ResponseRecord,
)
from experiments.rag_vs_finetuning.evaluation.runner import run_evaluation

REPO = Path(__file__).parent.parent
_CHUNKS = REPO / "experiments/rag_vs_finetuning/data/chunks/chunks.jsonl"


def _answerable(**kw):
    base = dict(id="C1", question="q", program="p", category="contact", difficulty="easy",
                expected_answer="x@csulb.edu", acceptable_alternatives=["Dr. X"],
                required_program="p", required_section="contact",
                expected_citation_targets=["p::contact::chunk::000"], answerable=True,
                source_missing=False)
    base.update(kw)
    return EvalCase(**base)


def _unanswerable(**kw):
    base = dict(id="C2", question="q2", program="p", category="source_missing",
                difficulty="hard", expected_answer=None, answerable=False, source_missing=True,
                expected_citation_targets=[])
    base.update(kw)
    return EvalCase(**base)


def _resp(**kw):
    base = dict(question="q", answer="", insufficient_evidence=False,
                citation_chunk_ids=[], retrieved_chunk_ids=[])
    base.update(kw)
    return ResponseRecord(**base)


class TestFrozenDataset(unittest.TestCase):
    def test_real_dataset_valid(self):
        ds = load_dataset(REPO / DATASET_PATH)
        errors = validate_dataset(ds, load_chunk_ids(_CHUNKS))
        self.assertEqual(errors, [], f"dataset invalid: {errors}")

    def test_checksum_stable(self):
        ds = load_dataset(REPO / DATASET_PATH)
        self.assertEqual(compute_checksum(ds), ds.dataset_checksum)

    def test_all_programs_and_case_count(self):
        ds = load_dataset(REPO / DATASET_PATH)
        self.assertEqual(len(ds.cases), 84)
        self.assertEqual(len({c.program for c in ds.cases}), 12)

    def test_duplicate_question_detected(self):
        ds = load_dataset(REPO / DATASET_PATH)
        bad = copy.deepcopy(ds)
        bad.cases[1].question = bad.cases[0].question
        errors = validate_dataset(bad, load_chunk_ids(_CHUNKS))
        self.assertTrue(any("duplicate question" in e for e in errors))

    def test_missing_citation_target_detected(self):
        ds = load_dataset(REPO / DATASET_PATH)
        bad = copy.deepcopy(ds)
        for c in bad.cases:
            if c.answerable:
                c.expected_citation_targets = ["nonexistent::chunk::000"]
                break
        errors = validate_dataset(bad, load_chunk_ids(_CHUNKS))
        self.assertTrue(any("does not exist" in e for e in errors))


class TestMetrics(unittest.TestCase):
    def test_answerable_correct(self):
        r = score_case(_answerable(), _resp(answer="Contact Dr. X at x@csulb.edu",
                                            citation_chunk_ids=["p::contact::chunk::000"],
                                            retrieved_chunk_ids=["p::contact::chunk::000"]))
        self.assertTrue(r.answer_correct)
        self.assertFalse(r.hallucinated)
        self.assertEqual(r.citation_precision, 1.0)
        self.assertEqual(r.citation_recall, 1.0)
        self.assertEqual(r.retrieval_recall, 1.0)

    def test_answerable_abstained_is_incorrect(self):
        r = score_case(_answerable(), _resp(answer="I don't have that information", insufficient_evidence=True))
        self.assertFalse(r.answer_correct)
        self.assertTrue(r.abstained)

    def test_unanswerable_abstain_correct(self):
        r = score_case(_unanswerable(), _resp(question="q2", insufficient_evidence=True,
                                              answer="I don't have that information"))
        self.assertTrue(r.answer_correct)
        self.assertFalse(r.hallucinated)

    def test_unanswerable_fabrication_is_hallucination(self):
        r = score_case(_unanswerable(), _resp(question="q2", answer="Yes, it is STEM designated."))
        self.assertTrue(r.hallucinated)
        self.assertFalse(r.answer_correct)

    def test_citation_precision_partial(self):
        r = score_case(_answerable(), _resp(answer="x@csulb.edu",
                                            citation_chunk_ids=["p::contact::chunk::000", "wrong::chunk::000"]))
        self.assertEqual(r.citation_precision, 0.5)
        self.assertEqual(r.citation_recall, 1.0)

    def test_aggregate(self):
        cases = [_answerable(), _unanswerable()]
        resps = {"C1": _resp(answer="x@csulb.edu", citation_chunk_ids=["p::contact::chunk::000"],
                             retrieved_chunk_ids=["p::contact::chunk::000"],
                             retrieval_latency_ms=10, generation_latency_ms=20),
                 "C2": _resp(question="q2", insufficient_evidence=True, answer="not available")}
        results = [score_case(cases[0], resps["C1"]), score_case(cases[1], resps["C2"])]
        m = aggregate(results, resps)
        self.assertEqual(m["answer_accuracy"], 1.0)
        self.assertEqual(m["abstention_accuracy"], 1.0)
        self.assertEqual(m["hallucination_rate"], 0.0)
        self.assertEqual(m["avg_end_to_end_latency_ms"], 15.0)  # (30 + 0)/2


class TestRunner(unittest.TestCase):
    def _dataset(self):
        cases = [_answerable(question="qa"), _unanswerable(question="qb")]
        ds = EvalDataset(dataset_version="t", frozen=True, generated_from="test",
                         case_count=2, dataset_checksum="x", cases=cases)
        return ds

    def test_run_evaluation_report(self):
        ds = self._dataset()
        responses = [_resp(question="qa", answer="x@csulb.edu",
                           citation_chunk_ids=["p::contact::chunk::000"],
                           retrieved_chunk_ids=["p::contact::chunk::000"]),
                     _resp(question="qb", insufficient_evidence=True, answer="no information")]
        report = run_evaluation(ds, responses, track="track_a")
        self.assertEqual(report.responded_count, 2)
        self.assertEqual(report.failure_count, 0)
        self.assertEqual(report.metrics["answer_accuracy"], 1.0)
        self.assertIn("contact", report.metrics_by_category)

    def test_missing_response_is_failure(self):
        ds = self._dataset()
        report = run_evaluation(ds, [_resp(question="qa", answer="x@csulb.edu",
                                           citation_chunk_ids=["p::contact::chunk::000"])])
        self.assertEqual(report.failure_count, 1)


if __name__ == "__main__":
    unittest.main()
