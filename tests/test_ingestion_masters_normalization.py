"""
tests/test_ingestion_masters_normalization.py
Stage 2 normalization: parsers, deadline-interpretation rules, and that varied
wording maps to identical canonical fields.

Run: pytest tests/test_ingestion_masters_normalization.py -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.enums import (
    Audience, DataStatus, DeadlineKind, DegreeType, ExtractionMethod, SourceType,
)
from domain.programs.sources import Source
from domain.programs.validation import validate_program
from ingestion.masters.extraction import ExtractedFacts
from ingestion.masters.manifest import DiscoveredProgram
from ingestion.masters.normalization import (
    normalize_program, parse_gpa, parse_gre, parse_month_day, slugify,
)

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _index_source() -> Source:
    return Source(source_id="src-index", source_url="https://www.csulb.edu/masters",
                  source_type=SourceType.DEADLINE_TABLE, official=True, fetched_at=NOW,
                  last_verified=NOW.date(), content_hash="sha256:idx",
                  extraction_method=ExtractionMethod.TABLE_PARSE)


def _program_source() -> Source:
    return Source(source_id="src-program", source_url="https://www.csulb.edu/p",
                  source_type=SourceType.PROGRAM_PAGE, official=True, fetched_at=NOW,
                  last_verified=NOW.date(), content_hash="sha256:pg",
                  extraction_method=ExtractionMethod.HTML_PARSE)


class TestParsers(unittest.TestCase):
    def test_gpa_varied_wording(self):
        self.assertEqual(parse_gpa("Minimum GPA: 3.0 in the last 60 units"), 3.0)
        self.assertEqual(parse_gpa("Applicants should have at least a 3.0 cumulative GPA"), 3.0)
        self.assertIsNone(parse_gpa("No GPA information published"))
        self.assertIsNone(parse_gpa(None))

    def test_gre_varied_wording(self):
        self.assertFalse(parse_gre("The GRE is not required").required)
        self.assertFalse(parse_gre("GRE scores are waived for applicants").required)
        self.assertTrue(parse_gre("The GRE is required for all applicants").required)
        self.assertIsNone(parse_gre(None))

    def test_month_day(self):
        self.assertEqual(parse_month_day("March 1", 2027), date(2027, 3, 1))
        self.assertIsNone(parse_month_day("Not Accepting", 2027))
        self.assertIsNone(parse_month_day(None, 2027))

    def test_slugify(self):
        self.assertEqual(slugify("MS in Data Science"), "ms-in-data-science")


class TestNormalization(unittest.TestCase):
    def _discovered(self, **kw) -> DiscoveredProgram:
        base = dict(
            raw_listing_name="MS in Data Science", normalized_program_name="MS in Data Science",
            degree_label="MS", official_program_url="https://www.csulb.edu/cecs/ms-data-science",
            advisor_office="Dr. Ada Advisor", phone="(562) 985-0001",
            fall_application_deadline="March 1", fall_accept_decline_deadline="April 15",
            spring_application_deadline="Not Accepting", spring_accept_decline_deadline="Not Accepting",
            stem_designated=True,
        )
        base.update(kw)
        return DiscoveredProgram(**base)

    def _normalize(self, discovered):
        facts = ExtractedFacts(source_id="src-program", page_fetched=True,
                               overview_text="An applied analytics program.",
                               gpa_statement="Minimum GPA: 3.0", gre_statement="The GRE is not required")
        return normalize_program(discovered, index_source_id="src-index", program_facts=facts,
                                 program_source_id="src-program",
                                 sources=[_index_source(), _program_source()],
                                 fall_year=2027, spring_year=2028, now=NOW)

    def test_produces_valid_record(self):
        program, _ = self._normalize(self._discovered())
        errors = [f for f in validate_program(program, now=NOW) if f.severity.value == "error"]
        self.assertEqual(errors, [])

    def test_not_accepting_is_preserved_not_unknown(self):
        program, _ = self._normalize(self._discovered())
        terms = {t.term: t for t in program.application.terms.value}
        self.assertEqual(terms["spring_2028"].deadline_kind, DeadlineKind.NOT_ACCEPTING)
        self.assertIsNone(terms["spring_2028"].deadline)
        # the terms fact itself is available (published), never 'unknown'
        self.assertEqual(program.application.terms.data_status, DataStatus.AVAILABLE)

    def test_accept_decline_kept_separate_from_application(self):
        program, _ = self._normalize(self._discovered())
        fall = next(t for t in program.application.terms.value if t.term == "fall_2027")
        self.assertEqual(fall.deadline, date(2027, 3, 1))
        self.assertEqual(fall.accept_decline_deadline, date(2027, 4, 15))
        self.assertNotEqual(fall.deadline, fall.accept_decline_deadline)

    def test_international_never_inferred_from_domestic(self):
        program, _ = self._normalize(self._discovered())
        self.assertEqual(program.admissions.intl_distinctions.data_status, DataStatus.UNKNOWN)

    def test_varied_gpa_wording_same_canonical_value(self):
        p1, _ = self._normalize(self._discovered())
        facts2 = ExtractedFacts(source_id="src-program", page_fetched=True,
                                overview_text="Stats program.",
                                gpa_statement="Applicants should have at least a 3.0 cumulative GPA",
                                gre_statement="GRE scores are waived")
        p2, _ = normalize_program(self._discovered(), index_source_id="src-index", program_facts=facts2,
                                  program_source_id="src-program",
                                  sources=[_index_source(), _program_source()],
                                  fall_year=2027, spring_year=2028, now=NOW)
        self.assertEqual(p1.admissions.minimum_gpa.value, p2.admissions.minimum_gpa.value)

    def test_unknown_degree_preserves_official_value(self):
        program, _ = self._normalize(self._discovered(degree_label="MSpecial"))
        self.assertEqual(program.identity.degree_type, DegreeType.OTHER)
        self.assertEqual(program.identity.degree_type_official, "MSpecial")

    def test_no_program_page_marks_unknown_not_source_missing(self):
        program, _ = normalize_program(
            self._discovered(), index_source_id="src-index", program_facts=None,
            program_source_id=None, sources=[_index_source()],
            fall_year=2027, spring_year=2028, now=NOW)
        self.assertEqual(program.admissions.minimum_gpa.data_status, DataStatus.UNKNOWN)


class TestIdentityMissingValues(unittest.TestCase):
    """college/department must never become placeholder strings."""

    def _discovered(self) -> DiscoveredProgram:
        return DiscoveredProgram(
            raw_listing_name="MS in Data Science", normalized_program_name="MS in Data Science",
            degree_label="MS", official_program_url="https://www.csulb.edu/cecs/ms-data-science",
            fall_application_deadline="March 1", fall_accept_decline_deadline="April 15",
            stem_designated=True)

    def _normalize(self, facts, source_id=None):
        sources = [_index_source()] + ([_program_source()] if facts else [])
        return normalize_program(self._discovered(), index_source_id="src-index",
                                 program_facts=facts, program_source_id="src-program" if facts else None,
                                 sources=sources, fall_year=2027, spring_year=2028, now=NOW)[0]

    def test_missing_college_is_not_a_placeholder_string(self):
        facts = ExtractedFacts(source_id="src-program", page_fetched=True)  # no college
        p = self._normalize(facts)
        self.assertIsNone(p.identity.college.value)
        self.assertNotIn(p.identity.college.value, ("unspecified", "N/A", "TBD", ""))

    def test_page_consulted_but_absent_is_source_missing(self):
        facts = ExtractedFacts(source_id="src-program", page_fetched=True)
        p = self._normalize(facts)
        self.assertEqual(p.identity.college.data_status, DataStatus.SOURCE_MISSING)
        self.assertEqual(p.identity.department.data_status, DataStatus.SOURCE_MISSING)

    def test_source_not_consulted_is_unknown(self):
        p = self._normalize(None)  # no program page fetched
        self.assertEqual(p.identity.college.data_status, DataStatus.UNKNOWN)
        self.assertIsNone(p.identity.college.primary_source_ref)

    def test_source_backed_college_becomes_available(self):
        facts = ExtractedFacts(source_id="src-program", page_fetched=True,
                               college="College of Engineering", department="Computer Science")
        p = self._normalize(facts)
        self.assertEqual(p.identity.college.data_status, DataStatus.AVAILABLE)
        self.assertEqual(p.identity.college.value, "College of Engineering")
        self.assertEqual(p.identity.college.primary_source_ref, "src-program")

    def test_missing_degree_label_is_none_not_placeholder(self):
        discovered = self._discovered().model_copy(update={"degree_label": None})
        program, _ = normalize_program(discovered, index_source_id="src-index",
                                       program_facts=None, program_source_id=None,
                                       sources=[_index_source()], fall_year=2027,
                                       spring_year=2028, now=NOW)
        self.assertIsNone(program.identity.degree_type_official)


if __name__ == "__main__":
    unittest.main()
