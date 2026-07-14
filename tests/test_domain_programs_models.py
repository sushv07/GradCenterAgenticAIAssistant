"""
tests/test_domain_programs_models.py
Model construction, enum serialization, JSON round-trip, schema version,
and Source rules (Phase P1).

Run: pytest tests/test_domain_programs_models.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError

from domain.programs.enums import (
    DataStatus, DegreeType, ExtractionMethod, SourceType, Volatility,
)
from domain.programs.facts import Fact
from domain.programs.models import CURRENT_SCHEMA_VERSION, CanonicalProgram
from domain.programs.sources import Source

FIXTURES = Path(__file__).parent / "fixtures" / "masters_programs"


def _load(name: str) -> CanonicalProgram:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return CanonicalProgram.model_validate(data)


class TestFixtureConstruction(unittest.TestCase):
    def test_well_documented_loads(self):
        p = _load("well_documented")
        self.assertEqual(p.identity.program_id, "ms-computer-science")
        self.assertEqual(p.identity.degree_type, DegreeType.MS)

    def test_sparse_loads(self):
        p = _load("sparse")
        self.assertEqual(p.overview.official_summary.data_status, DataStatus.SOURCE_MISSING)
        self.assertIsNone(p.overview.official_summary.value)

    def test_domestic_international_loads(self):
        p = _load("domestic_international")
        audiences = {t.audience.value for t in p.application.terms.value}
        self.assertEqual(audiences, {"domestic", "international"})


class TestSerialization(unittest.TestCase):
    def test_enum_serializes_to_value(self):
        p = _load("well_documented")
        dumped = p.model_dump(mode="json")
        self.assertEqual(dumped["program_level"], "masters")
        self.assertEqual(dumped["identity"]["degree_type"], "MS")

    def test_json_round_trip_is_stable(self):
        for name in ("well_documented", "sparse", "domestic_international"):
            p = _load(name)
            once = p.model_dump(mode="json")
            twice = CanonicalProgram.model_validate(once).model_dump(mode="json")
            self.assertEqual(once, twice, f"round-trip differs for {name}")

    def test_schema_version_constant(self):
        p = _load("well_documented")
        self.assertEqual(p.schema_version, CURRENT_SCHEMA_VERSION)


class TestSourceRules(unittest.TestCase):
    def _src(self, **kw):
        base = dict(source_id="s1", source_url="https://example.edu/p",
                    source_type=SourceType.PROGRAM_PAGE, official=False,
                    fetched_at="2026-07-10T00:00:00Z", content_hash="sha256:abc",
                    extraction_method=ExtractionMethod.HTML_PARSE)
        base.update(kw)
        return Source(**base)

    def test_valid_source(self):
        self.assertEqual(self._src().source_id, "s1")

    def test_non_http_url_fails(self):
        with self.assertRaises(ValidationError):
            self._src(source_url="ftp://example.edu/x")

    def test_empty_content_hash_fails(self):
        with self.assertRaises(ValidationError):
            self._src(content_hash="")

    def test_bad_source_id_fails(self):
        with self.assertRaises(ValidationError):
            self._src(source_id="has space")


if __name__ == "__main__":
    unittest.main()
