"""
tests/test_ingestion_masters_calibration.py
Regression tests locking the behaviors calibrated against real CSULB layouts in
Phase P3 / P3.1. All fixtures are SYNTHETIC (inline HTML / example.edu) — no live
HTML is committed.

Covers: card-based discovery, Program-Overview extraction, boilerplate rejection,
navigation rejection, "Not Accepting", accept/decline deadline text, advisor
email extraction, and the no-fabricated-ISO-date deadline policy.

Run: pytest tests/test_ingestion_masters_calibration.py -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.enums import DeadlineKind, ExtractionMethod, SourceType
from domain.programs.sources import Source
from ingestion.masters.discovery import discover_from_html
from ingestion.masters.extraction import extract_program_page
from ingestion.masters.normalization import normalize_program, parse_gpa

FIXTURES = Path(__file__).parent / "fixtures" / "masters_html"
INDEX = (FIXTURES / "index.html").read_bytes()
NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)

# A real-shaped program page: heavy chrome (nav/header/footer) wrapping a <main>
# whose overview sits under a "Program Overview" heading. The GRE mention lives
# ONLY in the nav; the campus address is boilerplate.
_PAGE_WITH_OVERVIEW = b"""
<html><body>
  <nav>Apply Explore GMAT/GRE Not Required Give Students</nav>
  <header>California State University, Long Beach</header>
  <p>1250 Bellflower Boulevard Long Beach, California 90840 562.985.4111</p>
  <main>
    <h2>Program Overview</h2>
    <p>The Master of Science in Widgetry trains students in advanced widget design,
       reliability analysis, and reproducible experimentation across two tracks.</p>
    <h2>Admissions</h2>
    <p>Applicants must have a minimum GPA of 3.0 in the last 60 units of coursework.</p>
    <h2>Prerequisites</h2>
    <ul><li>Introduction to Widgets</li><li>Widget Calculus</li></ul>
  </main>
  <footer>1250 Bellflower Boulevard Long Beach, California 90840</footer>
</body></html>
"""

# No "Program Overview" heading: the first paragraph in main is a boilerplate
# campus address; the real overview is the second paragraph.
_PAGE_BOILERPLATE_FIRST = b"""
<html><body>
  <main>
    <p>1250 Bellflower Boulevard Long Beach, California 90840 562.985.4111</p>
    <p>The Master of Fine Arts in Studio Practice is a three-year terminal degree
       spanning ten studio tracks with a culminating exhibition requirement.</p>
  </main>
</body></html>
"""


def _index_source() -> Source:
    return Source(source_id="src-index", source_url="https://www.csulb.edu/masters",
                  source_type=SourceType.DEADLINE_TABLE, official=True, fetched_at=NOW,
                  last_verified=NOW.date(), content_hash="sha256:idx",
                  extraction_method=ExtractionMethod.TABLE_PARSE)


class TestCardDiscoveryLayout(unittest.TestCase):
    def _manifest(self):
        return discover_from_html(INDEX, source_url="https://example.edu/index", discovered_at=NOW)

    def test_cards_parsed_with_names_degrees_links(self):
        progs = {p.normalized_program_name: p for p in self._manifest().programs}
        self.assertEqual(set(progs), {"Data Science", "Applied Statistics", "Ambiguous Studies"})
        self.assertEqual(progs["Data Science"].degree_label, "MS")
        self.assertTrue(progs["Data Science"].official_program_url.startswith("https://"))

    def test_advisor_email_extracted(self):
        ds = next(p for p in self._manifest().programs if p.normalized_program_name == "Data Science")
        self.assertEqual(ds.advisor_email, "ds-grad@example.edu")
        self.assertEqual(ds.advisor_office, "Data Science Office")

    def test_not_accepting_preserved_verbatim(self):
        ds = next(p for p in self._manifest().programs if p.normalized_program_name == "Data Science")
        self.assertEqual(ds.spring_application_deadline, "Not Accepting")

    def test_application_and_accept_decline_split(self):
        ds = next(p for p in self._manifest().programs if p.normalized_program_name == "Data Science")
        self.assertEqual(ds.fall_application_deadline, "March 1")
        self.assertEqual(ds.fall_accept_decline_deadline, "April 15")


class TestExtractionCalibration(unittest.TestCase):
    def test_program_overview_extracted_from_main(self):
        f = extract_program_page(_PAGE_WITH_OVERVIEW, source_id="src-program")
        self.assertTrue(f.overview_text.startswith("The Master of Science in Widgetry"))

    def test_boilerplate_address_rejected(self):
        f = extract_program_page(_PAGE_WITH_OVERVIEW, source_id="src-program")
        self.assertNotIn("Bellflower", f.overview_text or "")
        f2 = extract_program_page(_PAGE_BOILERPLATE_FIRST, source_id="src-program")
        self.assertTrue(f2.overview_text.startswith("The Master of Fine Arts"))
        self.assertNotIn("Bellflower", f2.overview_text)

    def test_navigation_gre_not_captured(self):
        # "GMAT/GRE Not Required" appears only in <nav>, outside main content
        f = extract_program_page(_PAGE_WITH_OVERVIEW, source_id="src-program")
        self.assertIsNone(f.gre_statement)

    def test_real_gpa_sentence_extracted(self):
        f = extract_program_page(_PAGE_WITH_OVERVIEW, source_id="src-program")
        self.assertIsNotNone(f.gpa_statement)
        self.assertEqual(parse_gpa(f.gpa_statement), 3.0)

    def test_prerequisites_extracted(self):
        f = extract_program_page(_PAGE_WITH_OVERVIEW, source_id="src-program")
        self.assertIn("Introduction to Widgets", f.prerequisites)


class TestDeadlinePolicyNoFabricatedDates(unittest.TestCase):
    def test_published_text_preserved_and_no_iso_date(self):
        manifest = discover_from_html(INDEX, source_url="https://example.edu/index", discovered_at=NOW)
        applied = next(p for p in manifest.programs if p.normalized_program_name == "Applied Statistics")
        program, _ = normalize_program(applied, index_source_id="src-index", program_facts=None,
                                       program_source_id=None, sources=[_index_source()], now=NOW)
        terms = {t.term: t for t in program.application.terms.value}
        fall = terms["fall"]
        self.assertEqual(fall.deadline_kind, DeadlineKind.FINAL)
        self.assertIsNone(fall.deadline)                       # no fabricated ISO date
        self.assertEqual(fall.deadline_text, "February 15")    # published text preserved
        self.assertEqual(fall.accept_decline_deadline_text, "March 15")
        self.assertIsNone(fall.accept_decline_deadline)

    def test_not_accepting_term_has_no_dates(self):
        manifest = discover_from_html(INDEX, source_url="https://example.edu/index", discovered_at=NOW)
        ds = next(p for p in manifest.programs if p.normalized_program_name == "Data Science")
        program, _ = normalize_program(ds, index_source_id="src-index", program_facts=None,
                                       program_source_id=None, sources=[_index_source()], now=NOW)
        spring = next(t for t in program.application.terms.value if t.term == "spring")
        self.assertEqual(spring.deadline_kind, DeadlineKind.NOT_ACCEPTING)
        self.assertIsNone(spring.deadline)
        self.assertIsNone(spring.deadline_text)


if __name__ == "__main__":
    unittest.main()
