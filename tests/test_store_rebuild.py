"""
tests/test_store_rebuild.py
Phase 10G regression — mount-safe Chroma directory cleanup.

Verifies that _clear_chroma_dir_contents() removes all children of CHROMA_DIR
without removing CHROMA_DIR itself.  This is the correct behavior for a Render
persistent disk where the mount point directory cannot be rmdir'd (EBUSY).

No embedding model, no Chroma store, no network access required.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestClearChromaDirContents(unittest.TestCase):
    """_clear_chroma_dir_contents() deletes children, keeps the directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_clear(self) -> None:
        from rag.store import _clear_chroma_dir_contents
        with patch("rag.store.CHROMA_DIR", self.tmp):
            _clear_chroma_dir_contents()

    def test_top_level_directory_survives(self):
        self._run_clear()
        self.assertTrue(self.tmp.exists(), "CHROMA_DIR must not be removed")
        self.assertTrue(self.tmp.is_dir())

    def test_files_are_removed(self):
        (self.tmp / "chroma.sqlite3").write_bytes(b"fake-sqlite")
        (self.tmp / ".last_built").write_text("1234567890.0")
        self._run_clear()
        self.assertFalse((self.tmp / "chroma.sqlite3").exists())
        self.assertFalse((self.tmp / ".last_built").exists())

    def test_nested_directories_are_removed(self):
        uuid_dir = self.tmp / "4b7dabd5-6306-4880-8858-27ce66e917bb"
        uuid_dir.mkdir()
        (uuid_dir / "data_level0.bin").write_bytes(b"\x00" * 64)
        (uuid_dir / "header.bin").write_bytes(b"\x00" * 16)
        self._run_clear()
        self.assertFalse(uuid_dir.exists())

    def test_mixed_contents_fully_cleared(self):
        (self.tmp / "chroma.sqlite3").write_bytes(b"fake")
        nested = self.tmp / "sub"
        nested.mkdir()
        (nested / "file.bin").write_bytes(b"data")
        self._run_clear()
        remaining = list(self.tmp.iterdir())
        self.assertEqual(remaining, [], f"Expected empty dir, got: {remaining}")

    def test_empty_directory_leaves_no_error(self):
        # CHROMA_DIR already empty — iterdir yields nothing, no exception raised
        self._run_clear()
        self.assertTrue(self.tmp.exists())

    def test_returns_none(self):
        from rag.store import _clear_chroma_dir_contents
        with patch("rag.store.CHROMA_DIR", self.tmp):
            result = _clear_chroma_dir_contents()
        self.assertIsNone(result)


class TestBuildVectorStoreUsesContentsClear(unittest.TestCase):
    """build_vector_store() must call _clear_chroma_dir_contents, not rmtree(CHROMA_DIR)."""

    def test_rmtree_not_called_with_chroma_dir(self):
        """Passing CHROMA_DIR itself to shutil.rmtree would EBUSY on a mount point.
        Verify build_vector_store() never does that."""
        import inspect
        from rag import store as store_module

        source = inspect.getsource(store_module.build_vector_store)
        # Strip comment lines so that explanatory comments mentioning the old
        # pattern do not trigger a false positive.
        code_lines = [
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ]
        code_only = "\n".join(code_lines)
        # The helper must be called
        self.assertIn("_clear_chroma_dir_contents", code_only)
        # shutil.rmtree must NOT be called with CHROMA_DIR directly
        # (only called inside _clear_chroma_dir_contents, on subdirectories)
        self.assertNotIn("shutil.rmtree(CHROMA_DIR)", code_only)


if __name__ == "__main__":
    unittest.main()
