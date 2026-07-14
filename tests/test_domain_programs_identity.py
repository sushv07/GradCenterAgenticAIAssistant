"""
tests/test_domain_programs_identity.py
Identity college/department as Fact[str]: honest missing states, placeholder
rejection, and serialization of the missing state (Phase P2.1).

Run: pytest tests/test_domain_programs_identity.py -v
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.enums import DataStatus
from domain.programs.models import CanonicalProgram
from domain.programs.validation import validate_program

FIXTURES = Path(__file__).parent / "fixtures" / "masters_programs"


def _raw(name: str = "well_documented") -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _fact(value, status, ref=None):
    return {"value": value, "data_status": status, "volatility": "stable",
            "primary_source_ref": ref, "supporting_source_refs": [],
            "official_text": None, "notes": None}


def _errors(program):
    return {f.rule_id for f in validate_program(program) if f.severity.value == "error"}


class TestIdentityMissingStates(unittest.TestCase):
    def test_unknown_college_is_valid_and_null(self):
        d = _raw()
        d["identity"]["college"] = _fact(None, "unknown")
        p = CanonicalProgram.model_validate(d)
        self.assertIsNone(p.identity.college.value)
        self.assertEqual(p.identity.college.data_status, DataStatus.UNKNOWN)
        self.assertEqual(_errors(p), set())

    def test_source_missing_department_is_valid(self):
        d = _raw()
        d["identity"]["department"] = _fact(None, "source_missing", ref="src-prog")
        p = CanonicalProgram.model_validate(d)
        self.assertEqual(p.identity.department.data_status, DataStatus.SOURCE_MISSING)
        self.assertEqual(_errors(p), set())

    def test_source_backed_college_serializes_and_round_trips(self):
        d = _raw()
        d["identity"]["college"] = _fact("college_of_engineering", "available", ref="src-prog")
        p = CanonicalProgram.model_validate(d)
        back = CanonicalProgram.model_validate_json(p.model_dump_json())
        self.assertEqual(back.identity.college.value, "college_of_engineering")
        self.assertEqual(back.identity.college.data_status, DataStatus.AVAILABLE)
        self.assertEqual(back, p)

    def test_round_trip_preserves_missing_state(self):
        d = _raw()
        d["identity"]["college"] = _fact(None, "unknown")
        d["identity"]["department"] = _fact(None, "source_missing", ref="src-prog")
        p = CanonicalProgram.model_validate(d)
        back = CanonicalProgram.model_validate_json(p.model_dump_json())
        self.assertEqual(back.identity.college.data_status, DataStatus.UNKNOWN)
        self.assertEqual(back.identity.department.data_status, DataStatus.SOURCE_MISSING)
        self.assertEqual(back, p)


class TestPlaceholderRejection(unittest.TestCase):
    def test_unspecified_college_rejected(self):
        d = _raw()
        d["identity"]["college"] = _fact("unspecified", "available", ref="src-prog")
        self.assertIn("CP-E011", _errors(CanonicalProgram.model_validate(d)))

    def test_na_canonical_name_rejected(self):
        d = _raw()
        d["identity"]["canonical_name"] = "N/A"
        self.assertIn("CP-E011", _errors(CanonicalProgram.model_validate(d)))

    def test_tbd_department_rejected(self):
        d = _raw()
        d["identity"]["department"] = _fact("TBD", "available", ref="src-prog")
        self.assertIn("CP-E011", _errors(CanonicalProgram.model_validate(d)))

    def test_empty_canonical_name_rejected(self):
        d = _raw()
        d["identity"]["canonical_name"] = ""
        # empty identity value is an error (via CP-E003/CP-E009)
        self.assertTrue(_errors(CanonicalProgram.model_validate(d)))

    def test_clean_fixtures_have_no_placeholder_errors(self):
        for name in ("well_documented", "sparse", "domestic_international"):
            self.assertNotIn("CP-E011", _errors(CanonicalProgram.model_validate(_raw(name))))


if __name__ == "__main__":
    unittest.main()
