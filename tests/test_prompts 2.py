"""
tests/test_prompts.py
Phase 7E — regression tests for the prompt versioning package.

Covers:
  - Prompt loading: both registered prompts load and match the file content
    exactly.
  - Missing prompt handling: an unregistered name raises PromptNotFoundError
    with a clear, self-correcting message.
  - Cache behavior: repeated load_prompt() calls return the exact same
    string object (lru_cache), and the file is only read once.
  - Prompt version retrieval: get_prompt_version()/get_prompt_info().
  - Evaluation report prompt metadata: run_llm_evals.py's report includes
    prompt name/version for both sections.
  - Behavior identical before/after extraction: the live _SYSTEM_PROMPT
    module attributes in both production files exactly match their
    corresponding prompts/*.md file content, and full Phase 7B/7C/7D
    behavior is unaffected (covered by re-running those suites, asserted
    separately in this phase's validation step — this file focuses on the
    prompt package itself).

Run from the project root:
    pytest tests/test_prompts.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

from config.settings import PROMPTS_DIR
from prompts.loader import load_prompt, get_prompt_version, get_prompt_info, PromptNotFoundError
from prompts.registry import get_prompt_metadata, list_prompt_names, PromptMetadata


class TestPromptLoading(unittest.TestCase):
    def test_recommendation_explanation_loads(self):
        text = load_prompt("recommendation_explanation")
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_grounded_answer_synthesis_loads(self):
        text = load_prompt("grounded_answer_synthesis")
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_loaded_content_matches_file_on_disk_exactly(self):
        for name in list_prompt_names():
            meta = get_prompt_metadata(name)
            on_disk = (PROMPTS_DIR / meta.relative_path).read_text(encoding="utf-8")
            self.assertEqual(load_prompt(name), on_disk, name)

    def test_explanation_prompt_mentions_required_json_shape(self):
        text = load_prompt("recommendation_explanation")
        self.assertIn('{"explanation"', text)

    def test_synthesis_prompt_mentions_required_json_shape(self):
        text = load_prompt("grounded_answer_synthesis")
        self.assertIn('"answer"', text)
        self.assertIn('"confidence"', text)


class TestMissingPromptHandling(unittest.TestCase):
    def test_unregistered_name_raises_clear_error(self):
        with self.assertRaises(PromptNotFoundError) as ctx:
            load_prompt("does_not_exist")
        self.assertIn("does_not_exist", str(ctx.exception))
        self.assertIn("recommendation_explanation", str(ctx.exception))

    def test_registry_lookup_also_raises_for_unknown_name(self):
        with self.assertRaises(KeyError):
            get_prompt_metadata("does_not_exist")

    def test_missing_file_raises_prompt_not_found(self):
        from unittest.mock import patch
        from prompts.registry import PromptMetadata
        fake_meta = PromptMetadata(
            name="fake", version="v1", description="x",
            intended_model="x", relative_path="nonexistent/file_v99.md",
        )
        load_prompt.cache_clear()
        with patch("prompts.loader.get_prompt_metadata", return_value=fake_meta):
            with self.assertRaises(PromptNotFoundError):
                load_prompt("fake")
        load_prompt.cache_clear()


class TestCacheBehavior(unittest.TestCase):
    def test_repeated_calls_return_identical_string_object(self):
        a = load_prompt("recommendation_explanation")
        b = load_prompt("recommendation_explanation")
        self.assertIs(a, b)

    def test_file_only_read_once_across_repeated_calls(self):
        from unittest.mock import patch
        load_prompt.cache_clear()
        load_prompt("grounded_answer_synthesis")  # warm the cache
        with patch("pathlib.Path.read_text") as mock_read:
            load_prompt("grounded_answer_synthesis")
            load_prompt("grounded_answer_synthesis")
            mock_read.assert_not_called()
        load_prompt.cache_clear()
        load_prompt("grounded_answer_synthesis")  # restore real cache for other tests


class TestPromptVersionRetrieval(unittest.TestCase):
    def test_get_prompt_version_returns_v1(self):
        self.assertEqual(get_prompt_version("recommendation_explanation"), "v1")
        self.assertEqual(get_prompt_version("grounded_answer_synthesis"), "v1")

    def test_get_prompt_info_returns_metadata_record(self):
        info = get_prompt_info("recommendation_explanation")
        self.assertIsInstance(info, PromptMetadata)
        self.assertEqual(info.name, "recommendation_explanation")
        self.assertEqual(info.intended_model, "qwen2.5:7b-instruct")

    def test_list_prompt_names_includes_both_registered_prompts(self):
        names = list_prompt_names()
        self.assertIn("recommendation_explanation", names)
        self.assertIn("grounded_answer_synthesis", names)


class TestBehaviorIdenticalBeforeAfterExtraction(unittest.TestCase):
    def test_recommendation_explainer_system_prompt_matches_registry(self):
        import agents.recommendation_explainer as explainer
        self.assertEqual(explainer._SYSTEM_PROMPT, load_prompt("recommendation_explanation"))

    def test_llm_synthesizer_system_prompt_matches_registry(self):
        import agents.llm_synthesizer as synth
        self.assertEqual(synth._SYSTEM_PROMPT, load_prompt("grounded_answer_synthesis"))


class TestEvaluationReportPromptMetadata(unittest.TestCase):
    def test_report_includes_prompt_name_and_version_for_both_sections(self):
        from evals.run_llm_evals import _build_report, _load_dataset, _EXPLANATION_DATASET, _ANSWER_DATASET, _run_explanation_case, _run_answer_case

        explanation_dataset = _load_dataset(_EXPLANATION_DATASET)
        answer_dataset       = _load_dataset(_ANSWER_DATASET)
        explanation_results  = [_run_explanation_case(explanation_dataset["cases"][0])]
        answer_results        = [_run_answer_case(answer_dataset["cases"][0])]

        report = _build_report(explanation_results, answer_results, explanation_dataset, answer_dataset, 1.0)

        self.assertEqual(report["recommendation_explanation"]["prompt_name"], "recommendation_explanation")
        self.assertEqual(report["recommendation_explanation"]["prompt_version"], "v1")
        self.assertEqual(report["grounded_answer"]["prompt_name"], "grounded_answer_synthesis")
        self.assertEqual(report["grounded_answer"]["prompt_version"], "v1")

    def test_report_metrics_unchanged_by_prompt_metadata_addition(self):
        """Prompt metadata is additive — existing metric keys/shape unchanged."""
        from evals.run_llm_evals import _build_report, _load_dataset, _EXPLANATION_DATASET, _ANSWER_DATASET, _run_explanation_case, _run_answer_case

        explanation_dataset = _load_dataset(_EXPLANATION_DATASET)
        answer_dataset       = _load_dataset(_ANSWER_DATASET)
        explanation_results  = [_run_explanation_case(c) for c in explanation_dataset["cases"]]
        answer_results        = [_run_answer_case(c) for c in answer_dataset["cases"]]

        report = _build_report(explanation_results, answer_results, explanation_dataset, answer_dataset, 1.0)

        for key in ("explanation_generation_rate", "evidence_coverage_rate", "forbidden_claim_rate",
                    "deterministic_consistency_rate", "fallback_success_rate"):
            self.assertIn(key, report["recommendation_explanation"]["metrics"])
        for key in ("citation_fidelity_rate", "unsupported_url_rejection_rate",
                    "insufficient_evidence_correctness_rate", "deterministic_fallback_correctness_rate"):
            self.assertIn(key, report["grounded_answer"]["metrics"])


if __name__ == "__main__":
    unittest.main()
