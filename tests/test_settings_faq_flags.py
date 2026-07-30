"""
tests/test_settings_faq_flags.py
Phase 4.0 — FAQ feature flags.

Verifies the new config flags exist with the correct inert defaults and are
env-overridable, and that a bad env value falls back to the default rather than
raising at import. Phase 4.0 is configuration only: these constants must not
change any runtime behavior yet.

Run: pytest tests/test_settings_faq_flags.py -v
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config.settings as settings


class TestFaqFlagDefaults(unittest.TestCase):
    def test_defaults_are_inert(self):
        self.assertFalse(settings.FAQ_SYNTHESIS_ENABLED)
        self.assertFalse(settings.FAQ_CRAWL_SUPPORTING)
        self.assertEqual(settings.FAQ_TOP_K, 6)
        self.assertEqual(settings.FAQ_MIN_SCORE, 0.30)
        self.assertEqual(settings.FAQ_CONTEXT_MAX_CHARS, 6000)
        self.assertEqual(settings.FAQ_CRAWL_DEPTH, 1)
        self.assertEqual(settings.FAQ_DOMAIN_ALLOWLIST, "csulb.edu")

    def test_faq_min_score_matches_global_default(self):
        # FAQ retrieval threshold must stay consistent with the global retriever.
        self.assertEqual(settings.FAQ_MIN_SCORE, settings.RETRIEVAL_MIN_RELEVANCE)


class TestFaqFlagEnvOverride(unittest.TestCase):
    def _reload(self):
        return importlib.reload(settings)

    def tearDown(self):
        # Restore pristine module state for other tests importing settings.
        for k in ("FAQ_SYNTHESIS_ENABLED", "FAQ_TOP_K", "FAQ_MIN_SCORE",
                  "FAQ_DOMAIN_ALLOWLIST", "FAQ_CONTEXT_MAX_CHARS"):
            import os
            os.environ.pop(k, None)
        importlib.reload(settings)

    def test_env_overrides_apply(self):
        import os
        os.environ["FAQ_SYNTHESIS_ENABLED"] = "true"
        os.environ["FAQ_TOP_K"] = "10"
        os.environ["FAQ_MIN_SCORE"] = "0.45"
        os.environ["FAQ_DOMAIN_ALLOWLIST"] = "example.edu"
        s = self._reload()
        self.assertTrue(s.FAQ_SYNTHESIS_ENABLED)
        self.assertEqual(s.FAQ_TOP_K, 10)
        self.assertEqual(s.FAQ_MIN_SCORE, 0.45)
        self.assertEqual(s.FAQ_DOMAIN_ALLOWLIST, "example.edu")

    def test_unparseable_env_falls_back_to_default(self):
        import os
        os.environ["FAQ_TOP_K"] = "not-a-number"
        os.environ["FAQ_CONTEXT_MAX_CHARS"] = ""
        s = self._reload()
        self.assertEqual(s.FAQ_TOP_K, 6)              # bad int → default
        self.assertEqual(s.FAQ_CONTEXT_MAX_CHARS, 6000)  # blank → default


if __name__ == "__main__":
    unittest.main()
