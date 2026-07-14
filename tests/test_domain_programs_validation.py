"""
tests/test_domain_programs_validation.py
Deterministic CanonicalProgram validation findings (Phase P1).

Findings are injected by loading a fixture as a dict, mutating it, and
re-validating — this keeps the structural models permissive while proving the
validator is the reachable gate.

Run: pytest tests/test_domain_programs_validation.py -v
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.config import FreshnessPolicy
from domain.programs.models import CanonicalProgram
from domain.programs.validation import validate_corpus, validate_program

FIXTURES = Path(__file__).parent / "fixtures" / "masters_programs"


def _raw(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _program(data: dict) -> CanonicalProgram:
    return CanonicalProgram.model_validate(data)


def _ids(findings, severity=None):
    return {
        f.rule_id for f in findings
        if severity is None or f.severity.value == severity
    }


class TestErrors(unittest.TestCase):
    def test_unresolved_source_reference(self):
        d = _raw("well_documented")
        d["overview"]["official_summary"]["primary_source_ref"] = "src-does-not-exist"
        findings = validate_program(_program(d))
        self.assertIn("CP-E007", _ids(findings, "error"))

    def test_duplicate_aliases(self):
        d = _raw("well_documented")
        d["identity"]["aliases"] = ["DUP", "DUP"]
        self.assertIn("CP-E005", _ids(validate_program(_program(d)), "error"))

    def test_alias_equals_canonical_name(self):
        d = _raw("well_documented")
        d["identity"]["aliases"] = [d["identity"]["canonical_name"]]
        self.assertIn("CP-E006", _ids(validate_program(_program(d)), "error"))

    def test_invalid_official_url(self):
        d = _raw("well_documented")
        d["identity"]["official_program_url"] = "not-a-url"
        self.assertIn("CP-E004", _ids(validate_program(_program(d)), "error"))

    def test_empty_string_missing_value(self):
        d = _raw("domestic_international")
        d["contact"]["department_contact"]["value"]["email"] = ""
        self.assertIn("CP-E009", _ids(validate_program(_program(d)), "error"))

    def test_available_contact_all_null(self):
        d = _raw("domestic_international")
        d["contact"]["department_contact"]["value"] = {
            "name": None, "email": None, "phone": None, "office": None, "source_ref": None,
        }
        self.assertIn("CP-E010", _ids(validate_program(_program(d)), "error"))

    def test_unrecognized_schema_version(self):
        d = _raw("well_documented")
        d["schema_version"] = "masters-9.9"
        self.assertIn("CP-E008", _ids(validate_program(_program(d)), "error"))

    def test_duplicate_program_id_in_corpus(self):
        a = _program(_raw("well_documented"))
        b = _program(_raw("well_documented"))
        results = validate_corpus([a, b])
        self.assertIn("CP-E002", _ids(results[a.identity.program_id], "error"))

    def test_clean_record_has_no_errors(self):
        for name in ("well_documented", "sparse", "domestic_international"):
            errs = _ids(validate_program(_program(_raw(name))), "error")
            self.assertEqual(errs, set(), f"{name} produced errors {errs}")


class TestWarnings(unittest.TestCase):
    def test_sparse_completeness_warning(self):
        self.assertIn("CP-W003", _ids(validate_program(_program(_raw("sparse"))), "warning"))

    def test_stale_warning_via_injected_policy(self):
        d = _raw("well_documented")
        policy = FreshnessPolicy(stable_days=3650, moderate_days=3650, time_sensitive_days=1)
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)  # well past a 1-day window
        findings = validate_program(_program(d), freshness_policy=policy, now=now)
        self.assertIn("CP-W002", _ids(findings, "warning"))

    def test_other_degree_warning_preserves_official_value(self):
        d = _raw("well_documented")
        d["identity"]["degree_type"] = "Other"
        d["identity"]["degree_type_official"] = "Master of Special Studies"
        p = _program(d)
        findings = validate_program(p)
        self.assertIn("CP-W006", _ids(findings, "warning"))
        self.assertEqual(p.identity.degree_type_official, "Master of Special Studies")


class TestInformational(unittest.TestCase):
    def test_archived_lifecycle_informational(self):
        d = _raw("well_documented")
        d["quality"]["lifecycle_state"] = "archived"
        self.assertIn("CP-I003", _ids(validate_program(_program(d)), "informational"))


if __name__ == "__main__":
    unittest.main()
