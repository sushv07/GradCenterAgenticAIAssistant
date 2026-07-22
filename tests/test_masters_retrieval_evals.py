"""
tests/test_masters_retrieval_evals.py
Phase 6 — retrieval evaluation framework (offline, deterministic).

No network, no Chroma, no embeddings, no LLM: a fake retrieve_fn returns
scripted results, so the loader, rank metrics (Recall@k, MRR), runner,
failure classification, and report generation are all verified deterministically.

Run: pytest tests/test_masters_retrieval_evals.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.metrics_retrieval_ranking import (
    first_relevant_rank, mean_reciprocal_rank, normalize_url, recall_at_k,
    recall_summary, url_matches,
)
from evals.run_masters_retrieval_evals import (
    classify_failure, load_cases, render_report, run_case, run_evals,
)

B = "https://www.csulb.edu"


def _result(url, score=0.5):
    return {"url": url, "score": score, "page_type": "masters_program",
            "program_name": "Alpha", "chunk_id": "x_0000", "title": "T"}


class TestRankMetrics(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(normalize_url("HTTP://X.edu/a/"), "x.edu/a")
        self.assertEqual(normalize_url("https://x.edu/a?utm=1#frag"), "x.edu/a")
        self.assertTrue(url_matches("http://x.edu/a/", "https://x.edu/a"))

    def test_first_relevant_rank(self):
        urls = [f"{B}/one", f"{B}/two", f"{B}/three"]
        self.assertEqual(first_relevant_rank(urls, [f"{B}/two"]), 2)
        self.assertEqual(first_relevant_rank(urls, [f"{B}/three", f"{B}/one"]), 1)
        self.assertIsNone(first_relevant_rank(urls, [f"{B}/absent"]))
        self.assertIsNone(first_relevant_rank(urls, []))

    def test_recall_at_k(self):
        self.assertTrue(recall_at_k(1, 1))
        self.assertFalse(recall_at_k(4, 3))
        self.assertFalse(recall_at_k(None, 5))

    def test_mrr(self):
        # ranks 1, 2, miss -> (1 + 0.5 + 0)/3
        self.assertAlmostEqual(mean_reciprocal_rank([1, 2, None]), 0.5, places=4)
        self.assertEqual(mean_reciprocal_rank([]), 0.0)

    def test_recall_summary(self):
        s = recall_summary([1, 2, 4, None])
        self.assertEqual(s["recall@1"], 0.25)
        self.assertEqual(s["recall@3"], 0.5)
        self.assertEqual(s["recall@5"], 0.75)


class TestLoader(unittest.TestCase):
    def _write(self, cases):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"cases": cases}, f)
        f.close()
        return Path(f.name)

    def test_valid_and_duplicate_ids(self):
        good = {"case_id": "C1", "category": "gpa", "style": "direct",
                "query": "q", "expected_urls": [f"{B}/a"]}
        self.assertEqual(len(load_cases(self._write([good]))), 1)
        with self.assertRaises(ValueError):
            load_cases(self._write([good, good]))                # duplicate id

    def test_requires_expectation(self):
        bad = {"case_id": "C2", "category": "gpa", "style": "direct", "query": "q"}
        with self.assertRaises(ValueError):
            load_cases(self._write([bad]))


class TestRunnerAndReport(unittest.TestCase):
    CASES = [
        {"case_id": "P1", "category": "gpa", "style": "direct",
         "query": "gpa?", "expected_urls": [f"{B}/hit"]},
        {"case_id": "F1", "category": "deadlines", "style": "paraphrase",
         "query": "deadline?", "expected_urls": [f"{B}/missed"]},
        {"case_id": "N1", "category": "negative", "style": "negative",
         "query": "parking?", "expect_empty": True},
    ]

    @staticmethod
    def _fake_retrieve(query, k=5, **kwargs):
        if query == "gpa?":
            return [_result(f"{B}/hit", 0.8)]
        if query == "deadline?":
            return [_result(f"{B}/other", 0.5)]
        return []                                               # negative query

    def test_run_evals_metrics(self):
        out = run_evals(self.CASES, retrieve_fn=self._fake_retrieve)
        m = out["metrics"]
        self.assertEqual(m["total_cases"], 3)
        self.assertEqual(m["passed"], 2)                        # P1 + N1
        self.assertEqual(m["failed"], 1)
        self.assertEqual(m["recall@1"], 0.5)                    # of the 2 scored cases
        self.assertEqual(m["mrr"], 0.5)
        self.assertIn("gpa", m["per_category"])
        self.assertEqual(len(out["failures"]), 1)
        self.assertEqual(out["failures"][0]["case_id"], "F1")

    def test_latency_captured(self):
        out = run_evals(self.CASES, retrieve_fn=self._fake_retrieve)
        self.assertTrue(all(r["latency_ms"] >= 0 for r in out["results"]))

    def test_classification_acquisition_gap_vs_ranking(self):
        failed = run_case(self.CASES[1], self._fake_retrieve)
        gap = classify_failure(failed, {"store_chunk_counts": {}, "probe_rank": None})
        self.assertEqual(gap["category"], "acquisition_gap")
        rank = classify_failure(failed, {
            "store_chunk_counts": {normalize_url(f"{B}/missed"): 4}, "probe_rank": 9})
        self.assertEqual(rank["category"], "retriever_ranking")
        emb = classify_failure(failed, {
            "store_chunk_counts": {normalize_url(f"{B}/missed"): 4}, "probe_rank": None})
        self.assertEqual(emb["category"], "embedding_limitation")

    def test_report_renders(self):
        out = run_evals(self.CASES, retrieve_fn=self._fake_retrieve)
        md = render_report(out, store_description="test store")
        self.assertIn("Recall@1", md)
        self.assertIn("F1", md)                                 # failure listed
        self.assertIn("acquisition_gap", md)                    # classification shown


if __name__ == "__main__":
    unittest.main()
