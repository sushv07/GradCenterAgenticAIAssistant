"""
tests/test_experiment_freeze.py
Freeze-tooling tests (Phase P5). Offline: synthetic card index + StaticFetcher
for the tool logic; the committed frozen corpus is verified via checksums.

Run: pytest tests/test_experiment_freeze.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.fetching import StaticFetcher
from ingestion.masters.sources_policy import GRADUATE_STUDIES_MASTERS_INDEX_URL
from experiments.rag_vs_finetuning.freeze.freeze import (
    FreezeError, freeze_corpus, verify_frozen_corpus,
)

FIXTURES = Path(__file__).parent / "fixtures" / "masters_html"
NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)
REPO = Path(__file__).parent.parent
_APPROVED = ("Data Science", "Applied Statistics")

_PAGES = {
    GRADUATE_STUDIES_MASTERS_INDEX_URL: (FIXTURES / "index.html").read_bytes(),
    "https://example.edu/cecs/ms-data-science": (FIXTURES / "program_ms_data_science.html").read_bytes(),
    "https://example.edu/math/ms-applied-statistics": (FIXTURES / "program_ms_applied_statistics.html").read_bytes(),
}


def _freeze(data_root, *, pages=_PAGES, selection=_APPROVED, approved=_APPROVED,
            corpus_version="1.0"):
    return freeze_corpus(
        fetcher=StaticFetcher(pages, clock=lambda: NOW), data_root=Path(data_root),
        freeze_id="test-freeze", corpus_version=corpus_version,
        code_baseline_commit="testsha", schema_version="masters-1.0", now=NOW,
        selection=selection, approved=approved)


class TestFreezeSuccess(unittest.TestCase):
    def test_freezes_approved_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _freeze(tmp)
            self.assertEqual(m["record_count"], 2)
            self.assertEqual(sorted(m["approved_program_ids"]), ["applied-statistics", "data-science"])
            verify_frozen_corpus(Path(tmp))

    def test_writes_records_and_snapshots_not_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            _freeze(tmp)
            self.assertTrue((Path(tmp) / "frozen_subset/programs/data-science.json").exists())
            snaps = list((Path(tmp) / "frozen_subset/sources").rglob("*.html"))
            self.assertGreaterEqual(len(snaps), 2)
            prod = REPO / "data" / "masters" / "programs"
            if prod.exists():
                self.assertEqual(list(prod.glob("data-science.json")), [])

    def test_manifest_has_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _freeze(tmp)
            self.assertTrue(m["aggregate_corpus_checksum"].startswith("sha256:"))
            for rec in m["records"]:
                self.assertTrue(rec["record_checksum"].startswith("sha256:"))
                for s in rec["sources"]:
                    self.assertTrue(s["content_hash"].startswith("sha256:"))


class TestFreezeFailures(unittest.TestCase):
    def test_missing_program_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FreezeError):
                _freeze(tmp, selection=("Data Science", "Nonexistent"),
                        approved=("Data Science", "Nonexistent"))

    def test_set_differs_from_approved_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FreezeError):
                _freeze(tmp, selection=("Data Science",), approved=_APPROVED)

    def test_tampered_record_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            _freeze(tmp)
            rec = Path(tmp) / "frozen_subset/programs/data-science.json"
            rec.write_text(rec.read_text() + " ")  # mutate frozen record
            with self.assertRaises(FreezeError):
                verify_frozen_corpus(Path(tmp))

    def test_missing_snapshot_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            _freeze(tmp)
            snap = next((Path(tmp) / "frozen_subset/sources/data-science").glob("*.html"))
            snap.unlink()
            with self.assertRaises(FreezeError):
                verify_frozen_corpus(Path(tmp))


class TestFreezeImmutability(unittest.TestCase):
    def test_aggregate_checksum_stable_across_builds(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(_freeze(a)["aggregate_corpus_checksum"],
                             _freeze(b)["aggregate_corpus_checksum"])

    def test_identical_rerun_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            m1 = _freeze(tmp)
            m2 = _freeze(tmp)  # same inputs, same version
            self.assertEqual(m1["aggregate_corpus_checksum"], m2["aggregate_corpus_checksum"])

    def test_changed_rerun_without_new_version_fails(self):
        changed = dict(_PAGES)
        changed["https://example.edu/cecs/ms-data-science"] = (
            FIXTURES / "program_ms_data_science.html").read_bytes() + b"<!-- drift -->"
        with tempfile.TemporaryDirectory() as tmp:
            _freeze(tmp)
            with self.assertRaises(FreezeError):
                _freeze(tmp, pages=changed, corpus_version="1.0")  # drift, same version


class TestCommittedFrozenCorpus(unittest.TestCase):
    def test_committed_corpus_verifies(self):
        data_root = REPO / "experiments" / "rag_vs_finetuning" / "data"
        if (data_root / "manifests" / "freeze_manifest.json").exists():
            verify_frozen_corpus(data_root)
            m = json.loads((data_root / "manifests" / "freeze_manifest.json").read_text())
            self.assertEqual(m["record_count"], 12)


if __name__ == "__main__":
    unittest.main()
