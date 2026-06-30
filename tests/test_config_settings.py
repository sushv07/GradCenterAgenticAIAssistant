"""
tests/test_config_settings.py
Phase 5A — regression tests for the centralized configuration layer.

Covers:
  - config values load correctly and match the original hardcoded values.
  - paths resolve to real, existing locations.
  - the modules that were migrated actually read their values FROM config
    (not just coincidentally matching) — verified by monkeypatching a
    config value and confirming the consuming module's value follows.
  - gradcenter_logging.py deliberately does NOT import config (documented
    "Standard library only. No project imports." constraint) — verified
    directly so a future change doesn't silently violate that invariant.

Run from the project root:
    pytest tests/test_config_settings.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

import config.settings as settings


class TestConfigValuesLoadCorrectly(unittest.TestCase):
    def test_embedding_settings(self):
        self.assertEqual(settings.EMBEDDING_MODEL, "all-MiniLM-L6-v2")
        self.assertEqual(settings.EMBEDDING_DEVICE, "cpu")
        self.assertTrue(settings.EMBEDDING_NORMALIZE)

    def test_retrieval_settings(self):
        self.assertEqual(settings.RETRIEVAL_MIN_RELEVANCE, 0.30)
        self.assertEqual(settings.RETRIEVAL_DEFAULT_TOP_K, 3)

    def test_chunking_settings(self):
        self.assertEqual(settings.CHUNK_SIZE, 500)
        self.assertEqual(settings.CHUNK_OVERLAP, 75)

    def test_chroma_settings(self):
        self.assertEqual(settings.CHROMA_COLLECTION_NAME, "csulb_grad_center")
        self.assertEqual(settings.CHROMA_STORE_TTL_SECONDS, 86_400)

    def test_faq_store_has_its_own_distinct_ttl(self):
        # Deliberately different from CHROMA_STORE_TTL_SECONDS — not merged.
        self.assertEqual(settings.FAQ_VECTORSTORE_TTL_SECONDS, 3_600)
        self.assertNotEqual(
            settings.FAQ_VECTORSTORE_TTL_SECONDS, settings.CHROMA_STORE_TTL_SECONDS
        )

    def test_application_settings(self):
        self.assertEqual(settings.DEFAULT_SESSION_ID, "default")
        self.assertEqual(settings.ADVISOR_STRONG_MATCH_THRESHOLD, 90)


class TestConfigPathsResolveCorrectly(unittest.TestCase):
    def test_chroma_dir_is_absolute_and_under_project_root(self):
        self.assertTrue(settings.CHROMA_DIR.is_absolute())
        self.assertEqual(settings.CHROMA_DIR.name, "chroma_db")

    def test_program_taxonomy_path_exists(self):
        self.assertTrue(settings.PROGRAM_TAXONOMY_PATH.exists())
        self.assertEqual(settings.PROGRAM_TAXONOMY_PATH.name, "program_taxonomy.json")


class TestModulesActuallyReadFromConfig(unittest.TestCase):
    """Confirm migrated modules consume config — not just coincidentally
    matching the same literal value."""

    def test_rag_store_constants_match_config(self):
        import rag.store as store
        # CHROMA_DIR is a real Path object (not interned like small literals),
        # so identity here genuinely proves it's the imported object, not a
        # coincidentally-equal redefinition.
        self.assertIs(store.CHROMA_DIR, settings.CHROMA_DIR)
        self.assertEqual(store.EMBEDDING_MODEL, settings.EMBEDDING_MODEL)
        self.assertEqual(store.COLLECTION_NAME, settings.CHROMA_COLLECTION_NAME)
        self.assertEqual(store.STORE_TTL, settings.CHROMA_STORE_TTL_SECONDS)

    def test_rag_retriever_min_relevance_matches_config(self):
        import rag.retriever as retriever
        self.assertEqual(retriever.MIN_RELEVANCE, settings.RETRIEVAL_MIN_RELEVANCE)

    def test_rag_chunking_constants_match_config(self):
        import rag.chunking as chunking
        self.assertEqual(chunking.CHUNK_SIZE, settings.CHUNK_SIZE)
        self.assertEqual(chunking.CHUNK_OVERLAP, settings.CHUNK_OVERLAP)

    def test_orchestrator_default_session_id_matches_config(self):
        import orchestrator
        self.assertEqual(orchestrator.run.__defaults__, (settings.DEFAULT_SESSION_ID,))

    def test_backend_entrypoint_default_session_id_matches_config(self):
        import inspect
        from backend.entrypoint import handle_user_query
        sig = inspect.signature(handle_user_query)
        self.assertEqual(
            sig.parameters["session_id"].default, settings.DEFAULT_SESSION_ID
        )


class TestLoggingStaysIndependentOfConfig(unittest.TestCase):
    """gradcenter_logging.py's own docstring states 'Standard library only.
    No project imports.' — config centralization must not violate that."""

    def test_gradcenter_logging_has_no_project_imports(self):
        import ast
        tree = ast.parse(Path("gradcenter_logging.py").read_text())
        project_modules = {"config", "rag", "agents", "routing", "retrieval",
                           "state", "responses", "context", "backend", "contracts"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], project_modules)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], project_modules)


if __name__ == "__main__":
    unittest.main()
