"""
tests/test_ingestion_masters_discovery.py
Stage 1 discovery: parse the card-structured index fixture into a
DiscoveryManifest offline (structure calibrated to the real CSULB page in P3).

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


def _by_name(name):
    return next(p for p in _manifest().programs if p.normalized_program_name == name)


class TestDiscovery(unittest.TestCase):
    def test_three_program_cards_discovered(self):
        self.assertEqual(len(_manifest().programs), 3)

    def test_names_and_degrees_parsed_from_card_links(self):
        m = {p.normalized_program_name: p.degree_label for p in _manifest().programs}
        self.assertEqual(m, {"Data Science": "MS", "Applied Statistics": "MS",
                             "Ambiguous Studies": "MA"})

    def test_contact_office_email_phone(self):
        ds = _by_name("Data Science")
        self.assertEqual(ds.official_program_url, "https://example.edu/cecs/ms-data-science")
        self.assertEqual(ds.advisor_office, "Data Science Office")
        self.assertEqual(ds.advisor_email, "ds-grad@example.edu")
        self.assertEqual(ds.phone, "(562) 985-0001")

    def test_application_and_accept_decline_split(self):
        ds = _by_name("Data Science")
        self.assertEqual(ds.fall_application_deadline, "March 1")
        self.assertEqual(ds.fall_accept_decline_deadline, "April 15")
        # spring is "Not Accepting" — preserved verbatim, not blank/unknown
        self.assertEqual(ds.spring_application_deadline, "Not Accepting")

    def test_term_availability_excludes_not_accepting(self):
        ds = _by_name("Data Science")
        self.assertIn("fall", ds.term_availability)
        self.assertNotIn("spring", ds.term_availability)

    def test_stem_marker_detected_only_when_present(self):
        self.assertTrue(_by_name("Data Science").stem_designated)
        self.assertIsNone(_by_name("Applied Statistics").stem_designated)

    def test_incomplete_deadline_block_warning(self):
        amb = _by_name("Ambiguous Studies")
        self.assertTrue(any("incomplete deadline block" in w for w in amb.warnings))

    def test_source_hash_present(self):
        self.assertTrue(_manifest().discovery_source_hash.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
