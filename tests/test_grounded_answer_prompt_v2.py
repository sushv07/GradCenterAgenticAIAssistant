"""
tests/test_grounded_answer_prompt_v2.py
Phase 10 — v2 grounded-answer prompt registration + config-selectable active
prompt (offline, deterministic).

Verifies:
  1. the v2 candidate is registered, loads, and matches its on-disk file;
  2. v2 encodes the Phase 10 targets the design review calls for (grounding,
     conflict-surfacing, clarification, missing-info abstention, citation
     discipline, concision) that v1 lacks;
  3. the synthesizer's active prompt is config-selectable and defaults to v1,
     so deployed behavior and existing tests are unchanged.

Run: pytest tests/test_grounded_answer_prompt_v2.py -v
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from prompts.loader import load_prompt
from prompts.registry import get_prompt_metadata, list_prompt_names

V2 = "grounded_answer_synthesis_v2"


class TestV2Registration(unittest.TestCase):
    def test_registered_with_version_v2(self):
        meta = get_prompt_metadata(V2)
        self.assertEqual(meta.version, "v2")
        self.assertIn(V2, list_prompt_names())

    def test_loads_and_matches_disk(self):
        from config.settings import PROMPTS_DIR
        text = load_prompt(V2)
        on_disk = (PROMPTS_DIR / get_prompt_metadata(V2).relative_path).read_text("utf-8")
        self.assertEqual(text, on_disk)
        self.assertGreater(len(text), 0)

    def test_v1_still_v1(self):
        # bumping in a NEW entry must not disturb the existing prompt's version
        self.assertEqual(get_prompt_metadata("grounded_answer_synthesis").version, "v1")


class TestV2Content(unittest.TestCase):
    def setUp(self):
        self.v1 = load_prompt("grounded_answer_synthesis").lower()
        self.v2 = load_prompt(V2).lower()

    def test_v2_addresses_conflict_clarification_missing(self):
        for concept in ("conflict", "clarif", "not available"):
            self.assertIn(concept, self.v2, msg=concept)

    def test_v2_prioritizes_concision_unlike_v1(self):
        # v1 explicitly deprioritizes brevity ("NOT a summarizer"); v2 leads
        # with answering the question and names concision as a priority
        self.assertIn("concision", self.v2)
        self.assertIn("answer the question first", self.v2)
        self.assertIn("not a summarizer", self.v1)      # documents the contrast

    def test_v2_keeps_citation_discipline(self):
        self.assertIn("only urls that appear", self.v2)
        self.assertIn("json", self.v2)


class TestConfigSelectablePrompt(unittest.TestCase):
    @staticmethod
    def _restore_default():
        """Reload the module with no override so its module-level default is
        restored for every other test in the suite."""
        import agents.llm_synthesizer as synth
        importlib.reload(synth)

    def test_default_is_v1(self):
        import agents.llm_synthesizer as synth
        self.assertEqual(synth._ACTIVE_PROMPT_NAME, "grounded_answer_synthesis")
        self.assertEqual(synth._SYSTEM_PROMPT,
                         load_prompt("grounded_answer_synthesis"))

    def test_env_selects_v2(self):
        # ensure the default is restored AFTER the patched env is torn down,
        # so this test can never leak a v2-bound module to its neighbours
        self.addCleanup(self._restore_default)
        with mock.patch.dict("os.environ", {"GROUNDED_ANSWER_PROMPT": V2}):
            import agents.llm_synthesizer as synth
            reloaded = importlib.reload(synth)
            self.assertEqual(reloaded._ACTIVE_PROMPT_NAME, V2)
            self.assertEqual(reloaded._SYSTEM_PROMPT, load_prompt(V2))


if __name__ == "__main__":
    unittest.main()
