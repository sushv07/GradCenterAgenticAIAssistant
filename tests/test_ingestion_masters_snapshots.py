"""
tests/test_ingestion_masters_snapshots.py
Content hashing + immutable snapshot storage.

Run: pytest tests/test_ingestion_masters_snapshots.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.enums import ExtractionMethod, SourceType
from domain.programs.sources import Source
from ingestion.masters.fetching import FetchResult
from ingestion.masters.hashing import content_hash
from ingestion.masters.snapshots import SnapshotStore, snapshot_to_source

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _fetch(url: str, content: bytes) -> FetchResult:
    return FetchResult(url=url, content=content, fetched_at=NOW)


class TestHashing(unittest.TestCase):
    def test_hash_is_deterministic_and_prefixed(self):
        h1 = content_hash(b"hello")
        h2 = content_hash(b"hello")
        self.assertEqual(h1, h2)
        self.assertTrue(h1.startswith("sha256:"))

    def test_different_content_different_hash(self):
        self.assertNotEqual(content_hash(b"a"), content_hash(b"b"))


class TestSnapshotStore(unittest.TestCase):
    def test_save_writes_once_and_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp))
            f = _fetch("https://www.csulb.edu/p", b"<html>content</html>")
            first = store.save(program_id="ms-x", source_id="src-x",
                               source_type=SourceType.PROGRAM_PAGE, fetch=f)
            self.assertTrue(first.was_newly_written)
            # re-save identical content — no overwrite, same hash
            second = store.save(program_id="ms-x", source_id="src-x",
                                source_type=SourceType.PROGRAM_PAGE, fetch=f)
            self.assertFalse(second.was_newly_written)
            self.assertEqual(first.content_hash, second.content_hash)
            files = list((Path(tmp) / "ms-x").glob("*.html"))
            self.assertEqual(len(files), 1)

    def test_different_content_new_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp))
            store.save(program_id="ms-x", source_id="s", source_type=SourceType.PROGRAM_PAGE,
                       fetch=_fetch("https://www.csulb.edu/p", b"v1"))
            store.save(program_id="ms-x", source_id="s", source_type=SourceType.PROGRAM_PAGE,
                       fetch=_fetch("https://www.csulb.edu/p", b"v2"))
            files = list((Path(tmp) / "ms-x").glob("*.html"))
            self.assertEqual(len(files), 2)

    def test_official_flag_from_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp))
            official = store.save(program_id="p", source_id="s", source_type=SourceType.PROGRAM_PAGE,
                                  fetch=_fetch("https://www.csulb.edu/p", b"x"))
            synthetic = store.save(program_id="p", source_id="s", source_type=SourceType.PROGRAM_PAGE,
                                   fetch=_fetch("https://example.edu/p", b"y"))
            self.assertTrue(official.official)
            self.assertFalse(synthetic.official)

    def test_snapshot_to_source_builds_valid_domain_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp))
            snap = store.save(program_id="p", source_id="src-x", source_type=SourceType.DEADLINE_TABLE,
                              fetch=_fetch("https://www.csulb.edu/p", b"x"))
            src = snapshot_to_source(snap, extraction_method=ExtractionMethod.TABLE_PARSE)
            self.assertIsInstance(src, Source)
            self.assertEqual(src.source_id, "src-x")
            self.assertTrue(src.content_hash.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
