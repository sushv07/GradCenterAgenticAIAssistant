"""
tests/test_experiment_training.py
Frozen SFT dataset tests (Phase P8.0). Offline; deterministic; no model training.

Run: pytest tests/test_experiment_training.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.rag_vs_finetuning.training.export import (
    dataset_checksum, to_alpaca, to_conversational,
)
from experiments.rag_vs_finetuning.training.generate import REFUSAL, generate_examples
from experiments.rag_vs_finetuning.training.models import TrainingExample
from experiments.rag_vs_finetuning.training.split import deterministic_split
from experiments.rag_vs_finetuning.training.validate import validate_examples

REPO = Path(__file__).parent.parent


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.examples = generate_examples()

    def test_generates_examples(self):
        self.assertGreater(len(self.examples), 100)
        self.assertTrue(all(e.instruction and e.output for e in self.examples))

    def test_all_programs_and_refusals_present(self):
        self.assertEqual(len({e.program for e in self.examples}), 12)
        self.assertTrue(any(e.category == "refusal" for e in self.examples))
        self.assertTrue(all(e.output == REFUSAL for e in self.examples if not e.answerable))

    def test_no_benchmark_overlap_and_valid(self):
        errors, stats = validate_examples(self.examples)
        self.assertEqual(errors, [], f"validation errors: {errors[:5]}")
        self.assertEqual(stats["benchmark_overlap"], 0)


class TestValidationCatchesErrors(unittest.TestCase):
    def _base(self, **kw):
        base = dict(id="X1", program="accountancy", category="overview",
                    instruction="Describe accountancy.", input="",
                    output="text", answerable=True, grounded_in=["accountancy::overview"])
        base.update(kw)
        return TrainingExample(**base)

    def test_fabricated_answer_flagged(self):
        ex = self._base(output="A fabricated fact not in the corpus.")
        errors, _ = validate_examples([ex])
        self.assertTrue(any("not exactly supported" in e for e in errors))

    def test_benchmark_overlap_flagged(self):
        # an actual evaluation-benchmark question
        ex = self._base(instruction="What is the Accountancy program about?",
                        output=REFUSAL, answerable=False, grounded_in=["canonical:stem=source_missing"])
        errors, _ = validate_examples([ex])
        self.assertTrue(any("overlaps an evaluation-benchmark" in e for e in errors))

    def test_wrong_refusal_flagged(self):
        ex = self._base(answerable=False, output="Actually it is STEM.",
                        grounded_in=["canonical:stem=source_missing"])
        errors, _ = validate_examples([ex])
        self.assertTrue(any("refusal output" in e for e in errors))


class TestSplit(unittest.TestCase):
    def test_deterministic_and_complete(self):
        ex = generate_examples()
        t1, v1 = deterministic_split(ex)
        t2, v2 = deterministic_split(ex)
        self.assertEqual((t1, v1), (t2, v2))
        self.assertEqual(sorted(t1 + v1), sorted(e.id for e in ex))
        self.assertEqual(len(set(t1) & set(v1)), 0)

    def test_ratio_roughly_90_10(self):
        ex = generate_examples()
        t, v = deterministic_split(ex)
        self.assertAlmostEqual(len(t) / len(ex), 0.9, delta=0.03)


class TestExport(unittest.TestCase):
    def test_alpaca_and_conversational_shape(self):
        ex = generate_examples()[0]
        a = to_alpaca(ex)
        self.assertEqual(set(a), {"instruction", "input", "output"})
        c = to_conversational(ex)
        self.assertEqual([m["role"] for m in c["messages"]], ["system", "user", "assistant"])

    def test_checksum_stable(self):
        ex = generate_examples()
        self.assertEqual(dataset_checksum(ex), dataset_checksum(ex))


class TestCommittedDataset(unittest.TestCase):
    def test_manifest_and_files_present(self):
        td = REPO / "experiments/rag_vs_finetuning/data/training"
        if (td / "ft_manifest.json").exists():
            m = json.loads((td / "ft_manifest.json").read_text())
            self.assertEqual(m["total_examples"], m["train_count"] + m["val_count"])
            self.assertTrue(m["dataset_checksum"].startswith("sha256:"))
            # committed alpaca file matches the manifest count
            n = len((td / "ft_dataset.jsonl").read_text().strip().splitlines())
            self.assertEqual(n, m["total_examples"])


if __name__ == "__main__":
    unittest.main()
