"""
tests/test_domain_programs_serialization.py
Full CanonicalProgram serialization round-trip coverage (Phase P1.1).

For every fixture:
    CanonicalProgram -> JSON -> CanonicalProgram -> equality

Both Pydantic v2 paths are exercised (model_dump(mode="json")/model_validate
and model_dump_json/model_validate_json), and equality is asserted at the
MODEL level (not just dict level). Preservation of enums, dates, datetimes,
nested Facts, source references, optional/null fields, aliases, revision
history, volatility, and data_status is asserted explicitly.

Run: pytest tests/test_domain_programs_serialization.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.enums import DataStatus, DegreeType, ProgramLevel, Volatility
from domain.programs.facts import Fact
from domain.programs.models import CanonicalProgram

FIXTURES = Path(__file__).parent / "fixtures" / "masters_programs"
NAMES = ("well_documented", "sparse", "domestic_international")


def _load(name: str) -> CanonicalProgram:
    return CanonicalProgram.model_validate(
        json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    )


class TestRoundTripEquality(unittest.TestCase):
    def test_dict_mode_round_trip_model_equality(self):
        for name in NAMES:
            p = _load(name)
            back = CanonicalProgram.model_validate(p.model_dump(mode="json"))
            self.assertEqual(back, p, f"dict-mode round-trip changed {name}")

    def test_json_string_round_trip_model_equality(self):
        for name in NAMES:
            p = _load(name)
            back = CanonicalProgram.model_validate_json(p.model_dump_json())
            self.assertEqual(back, p, f"json-string round-trip changed {name}")

    def test_json_bytes_are_stable_across_round_trips(self):
        for name in NAMES:
            p = _load(name)
            first = p.model_dump_json()
            second = CanonicalProgram.model_validate_json(first).model_dump_json()
            self.assertEqual(first, second, f"json bytes drift for {name}")


class TestTypePreservation(unittest.TestCase):
    def test_enums_dates_datetimes_preserved(self):
        p = CanonicalProgram.model_validate_json(_load("well_documented").model_dump_json())
        # enums
        self.assertIsInstance(p.program_level, ProgramLevel)
        self.assertIs(p.identity.degree_type, DegreeType.MS)
        self.assertIs(p.overview.official_summary.data_status, DataStatus.AVAILABLE)
        self.assertIs(p.overview.official_summary.volatility, Volatility.STABLE)
        # date + datetime
        self.assertIsInstance(p.quality.last_verified, date)
        self.assertIsInstance(p.sources[0].fetched_at, datetime)
        self.assertIsInstance(p.sources[0].last_verified, date)
        # nested Fact + source references
        self.assertIsInstance(p.overview.official_summary, Fact)
        self.assertEqual(p.overview.official_summary.primary_source_ref, "src-prog")
        # aliases + revision history
        self.assertEqual(p.identity.aliases, ["MSCS", "MS CS"])
        self.assertEqual(len(p.quality.revision_history), 1)
        self.assertIsInstance(p.quality.revision_history[0].at, datetime)

    def test_null_and_optional_fields_preserved(self):
        p = CanonicalProgram.model_validate_json(_load("sparse").model_dump_json())
        # explicit null value + missing-status preserved
        self.assertIsNone(p.overview.official_summary.value)
        self.assertIs(p.overview.official_summary.data_status, DataStatus.SOURCE_MISSING)
        self.assertIsNone(p.admissions.minimum_gpa.value)
        self.assertIs(p.admissions.minimum_gpa.data_status, DataStatus.UNKNOWN)
        # absent optional section stays absent
        self.assertIsNone(p.enrichment)
        # empty aliases list preserved as []
        self.assertEqual(p.identity.aliases, [])

    def test_nested_fact_list_values_preserved(self):
        p = CanonicalProgram.model_validate_json(_load("domestic_international").model_dump_json())
        terms = p.application.terms.value
        self.assertEqual(len(terms), 2)
        self.assertEqual({t.audience.value for t in terms}, {"domestic", "international"})
        self.assertIs(p.application.rolling_admission.value, False)


if __name__ == "__main__":
    unittest.main()
