"""
tests/test_ingestion_masters_discovery.py
Stage 1 discovery: parse the index fixture into a DiscoveryManifest offline.

Run: pytest tests/test_ingestion_masters_discovery.py -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.discovery import discover_from_html

FIXTURES = Path(__file__).parent / "fixtures" / "masters_html"
INDEX = (FIXTURES / "index.html").read_bytes()
NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _manifest():
    return discover_from_html(INDEX, source_url="https://example.edu/index", discovered_at=NOW)


class TestDiscovery(unittest.TestCase):
    def test_three_programs_discovered(self):
        self.assertEqual(len(_manifest().programs), 3)

    def test_program_names_not_confused_with_advisor_column(self):
        names = [p.normalized_program_name for p in _manifest().programs]
        self.assertIn("MS in Data Science", names)
        self.assertIn("MS in Applied Statistics", names)
        self.assertNotIn("Dr. Ada Advisor", names)

    def test_links_and_stem_and_deadlines(self):
        ds = next(p for p in _manifest().programs if p.normalized_program_name == "MS in Data Science")
        self.assertEqual(ds.official_program_url, "https://example.edu/cecs/ms-data-science")
        self.assertTrue(ds.stem_designated)
        self.assertEqual(ds.fall_application_deadline, "March 1")
        self.assertEqual(ds.fall_accept_decline_deadline, "April 15")
        self.assertIn("fall", ds.term_availability)
        self.assertNotIn("spring", ds.term_availability)  # spring = Not Accepting

    def test_missing_link_warning(self):
        amb = next(p for p in _manifest().programs if p.normalized_program_name == "MA in Ambiguous Studies")
        self.assertIsNone(amb.official_program_url)
        self.assertIn("missing official program link", amb.warnings)

    def test_incomplete_deadline_block_warning(self):
        amb = next(p for p in _manifest().programs if p.normalized_program_name == "MA in Ambiguous Studies")
        self.assertTrue(any("incomplete deadline block" in w for w in amb.warnings))

    def test_source_hash_present(self):
        m = _manifest()
        self.assertTrue(m.discovery_source_hash.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
