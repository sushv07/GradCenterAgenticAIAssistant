"""
tests/test_ingestion_masters_pipeline.py
End-to-end discovery -> enrichment -> validation -> persistence, fully offline.

Run: pytest tests/test_ingestion_masters_pipeline.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.validation import validate_program
from ingestion.masters.fetching import StaticFetcher
from ingestion.masters.persistence import load_program
from ingestion.masters.pipeline import run_pipeline
from ingestion.masters.snapshots import SnapshotStore
from ingestion.masters.sources_policy import GRADUATE_STUDIES_MASTERS_INDEX_URL

FIXTURES = Path(__file__).parent / "fixtures" / "masters_html"
NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)

_PAGES = {
    GRADUATE_STUDIES_MASTERS_INDEX_URL: (FIXTURES / "index.html").read_bytes(),
    "https://example.edu/cecs/ms-data-science": (FIXTURES / "program_ms_data_science.html").read_bytes(),
    "https://example.edu/math/ms-applied-statistics": (FIXTURES / "program_ms_applied_statistics.html").read_bytes(),
}


def _run(tmp: Path):
    return run_pipeline(
        fetcher=StaticFetcher(_PAGES, clock=lambda: NOW),
        snapshot_store=SnapshotStore(tmp / "sources"),
        programs_dir=tmp / "programs",
        fall_year=2027, spring_year=2028, now=NOW,
    )


class TestPipeline(unittest.TestCase):
    def test_discovers_three_canonicalizes_two_skips_linkless(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = _run(Path(tmp))
            self.assertEqual(len(res.manifest.programs), 3)
            canonical = [r for r in res.results if not r.skipped]
            skipped = [r for r in res.results if r.skipped]
            self.assertEqual(len(canonical), 2)
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0].skip_reason, "missing official program link")

    def test_persisted_records_load_and_validate_without_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = _run(Path(tmp))
            for r in res.results:
                if r.skipped:
                    continue
                self.assertTrue(Path(r.canonical_path).exists())
                program = load_program(Path(r.canonical_path))
                errors = [f for f in validate_program(program, now=NOW) if f.severity.value == "error"]
                self.assertEqual(errors, [], f"{r.program_id} errors: {errors}")

    def test_file_per_program_naming(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(Path(tmp))
            files = sorted(p.name for p in (Path(tmp) / "programs").glob("*.json"))
            self.assertEqual(files, ["ms-in-applied-statistics.json", "ms-in-data-science.json"])

    def test_provenance_all_source_refs_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = _run(Path(tmp))
            for r in res.results:
                if r.skipped:
                    continue
                program = load_program(Path(r.canonical_path))
                known = {s.source_id for s in program.sources}
                self.assertIn("src-index", known)
                # every fact reference resolves (validator would flag CP-E007 otherwise)
                refs = [f.rule_id for f in validate_program(program, now=NOW) if f.rule_id == "CP-E007"]
                self.assertEqual(refs, [])

    def test_snapshots_written_and_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(Path(tmp))
            snaps = list((Path(tmp) / "sources").rglob("*.html"))
            self.assertGreaterEqual(len(snaps), 3)  # index + 2 program pages

    def test_deterministic_reruns_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            a = _run(Path(tmp1))
            b = _run(Path(tmp2))
            ids_a = sorted(r.program_id for r in a.results if r.program_id)
            ids_b = sorted(r.program_id for r in b.results if r.program_id)
            self.assertEqual(ids_a, ids_b)
            # identical canonical JSON across runs
            for pid in ids_a:
                fa = (Path(tmp1) / "programs" / f"{pid}.json").read_text()
                fb = (Path(tmp2) / "programs" / f"{pid}.json").read_text()
                self.assertEqual(fa, fb)

    def test_does_not_write_to_production_corpus(self):
        prod = Path(__file__).parent.parent / "data" / "masters" / "programs"
        with tempfile.TemporaryDirectory() as tmp:
            _run(Path(tmp))
            if prod.exists():
                self.assertEqual(list(prod.glob("ms-in-*.json")), [])


if __name__ == "__main__":
    unittest.main()
