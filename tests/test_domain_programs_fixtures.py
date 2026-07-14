"""
tests/test_domain_programs_fixtures.py
The three synthetic sample records validate deterministically, live only under
the fixtures tree, and use synthetic hosts (Phase P1).

Run: pytest tests/test_domain_programs_fixtures.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.enums import ProgramLevel
from domain.programs.models import CanonicalProgram
from domain.programs.validation import validate_program

FIXTURES = Path(__file__).parent / "fixtures" / "masters_programs"
NAMES = ("well_documented", "sparse", "domestic_international")


def _load(name: str) -> CanonicalProgram:
    return CanonicalProgram.model_validate(
        json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    )


class TestSampleRecords(unittest.TestCase):
    def test_all_three_exist(self):
        for name in NAMES:
            self.assertTrue((FIXTURES / f"{name}.json").exists(), name)

    def test_all_masters_level_and_error_free(self):
        for name in NAMES:
            p = _load(name)
            self.assertEqual(p.program_level, ProgramLevel.MASTERS)
            errs = [f for f in validate_program(p) if f.severity.value == "error"]
            self.assertEqual(errs, [], f"{name} has errors: {errs}")

    def test_each_has_at_least_one_source(self):
        for name in NAMES:
            self.assertGreaterEqual(len(_load(name).sources), 1, name)

    def test_set_demonstrates_a_warning(self):
        found = False
        for name in NAMES:
            if any(f.severity.value == "warning" for f in validate_program(_load(name))):
                found = True
        self.assertTrue(found, "no warning demonstrated across the sample set")

    def test_uses_synthetic_hosts_only(self):
        for name in NAMES:
            raw = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
            self.assertNotIn("csulb.edu", raw, f"{name} must not reference real CSULB hosts")
            self.assertIn("example.edu", raw, name)

    def test_no_empty_string_values_in_fixtures(self):
        for name in NAMES:
            raw = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
            self.assertNotIn(': ""', raw, f"{name} uses an empty-string value")


if __name__ == "__main__":
    unittest.main()
