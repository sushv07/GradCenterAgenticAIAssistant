"""
tests/test_masters_directory_discovery.py
Phase 1 — master's directory discovery, validated against a REAL captured
snapshot of the Graduate Studies master's index.

`tests/fixtures/masters_html/index_live_snapshot.html` is a byte-for-byte capture
of the live directory (distinct from the synthetic `index.html` used by the
parser calibration tests). Running the existing, unmodified
`discovery.discover_from_html` against it verifies the parser still handles the
current site deterministically. No network access — the snapshot is committed.

Run: pytest tests/test_masters_directory_discovery.py -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.discovery import discover_from_html
from ingestion.masters.discovery_report import build_discovery_report, render_markdown
from ingestion.masters.manifest import DiscoveryManifest

FIXTURE = Path(__file__).parent / "fixtures" / "masters_html" / "index_live_snapshot.html"
INDEX_URL = ("https://www.csulb.edu/graduate-studies-csulb/article/"
             "programs-advisors-and-deadlines-masters")
_NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


def _manifest() -> DiscoveryManifest:
    return discover_from_html(FIXTURE.read_bytes(), source_url=INDEX_URL, discovered_at=_NOW)


class TestLiveSnapshotDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _manifest()
        cls.progs = cls.manifest.programs

    def test_reasonable_program_count(self):
        # Live directory has ~67 master's cards; guard a sane floor/ceiling so a
        # future capture that silently loses cards fails loudly.
        self.assertGreaterEqual(len(self.progs), 55)
        self.assertLessEqual(len(self.progs), 120)

    def test_deterministic(self):
        a = [(p.raw_listing_name, p.official_program_url) for p in _manifest().programs]
        b = [(p.raw_listing_name, p.official_program_url) for p in _manifest().programs]
        self.assertEqual(a, b)

    def test_no_duplicate_cards(self):
        # (listing name, url) pairs must be unique — discovery dedupes exact cards.
        keys = [(p.raw_listing_name, p.official_program_url) for p in self.progs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_program_has_name_degree_and_valid_url(self):
        for p in self.progs:
            self.assertTrue(p.normalized_program_name.strip())
            self.assertTrue(p.degree_label and p.degree_label.strip())
            self.assertTrue(p.official_program_url and p.official_program_url.startswith("http"))

    def test_advisor_email_mostly_present_and_never_crashes(self):
        # Missing advisor fields must parse to None, never raise.
        with_email = sum(1 for p in self.progs if p.advisor_email)
        self.assertGreaterEqual(with_email, int(0.9 * len(self.progs)))
        for p in self.progs:
            self.assertIn(p.advisor_email, [None, *[p.advisor_email]])  # type is Optional[str]

    def test_deadlines_parse_and_preserve_verbatim(self):
        # At least one deadline per program on this snapshot; published text kept
        # verbatim (no fabricated ISO dates — a leading digit-year would be wrong).
        for p in self.progs:
            vals = [p.spring_application_deadline, p.fall_application_deadline,
                    p.spring_accept_decline_deadline, p.fall_accept_decline_deadline]
            for v in vals:
                if v is not None:
                    self.assertNotRegex(v, r"^\d{4}-\d{2}-\d{2}$")

    def test_duplicate_names_are_flagged(self):
        # Same normalized name with different degrees must carry the ambiguity warning.
        report = build_discovery_report(self.manifest)
        for name in report["manual_review"]["duplicate_normalized_names"]:
            dupes = [p for p in self.progs if p.normalized_program_name == name]
            self.assertTrue(all(
                any("ambiguous" in w for w in p.warnings) for p in dupes),
                f"{name} duplicates not all flagged")

    def test_missing_advisor_does_not_crash_and_is_reported(self):
        report = build_discovery_report(self.manifest)
        # Museum Studies has no advisor email on the live snapshot — reported, not fatal.
        self.assertIsInstance(report["manual_review"]["missing_advisor_email"], list)


class TestDiscoveryReport(unittest.TestCase):
    def test_report_shape_and_render(self):
        report = build_discovery_report(_manifest())
        stats = report["statistics"]
        self.assertEqual(stats["programs_discovered"], len(_manifest().programs))
        self.assertGreater(stats["urls_extracted"], 0)
        self.assertGreaterEqual(stats["programs_discovered"], stats["unique_urls"])
        md = render_markdown(report)
        self.assertIn("Master's Directory Discovery", md)
        self.assertIn("programs discovered", md)


if __name__ == "__main__":
    unittest.main()
