"""
tests/test_domain_programs_facts.py
Construction-time consistency rules for the Fact[T] envelope (Phase P1).

Run: pytest tests/test_domain_programs_facts.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError

from domain.programs.enums import DataStatus, Volatility
from domain.programs.facts import Fact


def _fact(**kw):
    base = dict(volatility=Volatility.MODERATE)
    base.update(kw)
    return Fact[str](**base)


class TestFactPasses(unittest.TestCase):
    def test_available_with_value_and_provenance(self):
        f = _fact(value="x", data_status=DataStatus.AVAILABLE, primary_source_ref="s1")
        self.assertEqual(f.value, "x")

    def test_stale_retains_value_and_provenance(self):
        f = _fact(value="old", data_status=DataStatus.STALE, primary_source_ref="s1")
        self.assertEqual(f.value, "old")
        self.assertEqual(f.primary_source_ref, "s1")

    def test_unknown_without_sources(self):
        f = _fact(value=None, data_status=DataStatus.UNKNOWN)
        self.assertIsNone(f.value)

    def test_conflicting_sources_valid(self):
        f = _fact(value=None, data_status=DataStatus.CONFLICTING_SOURCES,
                  primary_source_ref="s1", supporting_source_refs=["s2"],
                  notes="s1 and s2 disagree")
        self.assertEqual(f.all_source_refs(), ["s1", "s2"])

    def test_confirmed_empty_list_available(self):
        f = Fact[list](value=[], data_status=DataStatus.AVAILABLE,
                       volatility=Volatility.STABLE, primary_source_ref="s1")
        self.assertEqual(f.value, [])


class TestFactFails(unittest.TestCase):
    def test_available_with_null_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value=None, data_status=DataStatus.AVAILABLE, primary_source_ref="s1")

    def test_available_without_provenance_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value="x", data_status=DataStatus.AVAILABLE)

    def test_stale_without_provenance_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value="x", data_status=DataStatus.STALE)

    def test_unknown_with_provenance_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value=None, data_status=DataStatus.UNKNOWN, primary_source_ref="s1")

    def test_not_applicable_with_provenance_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value=None, data_status=DataStatus.NOT_APPLICABLE,
                  supporting_source_refs=["s1"])

    def test_manual_curated_without_notes_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value="x", data_status=DataStatus.MANUAL_CURATED, primary_source_ref="s1")

    def test_conflicting_sources_needs_two_refs(self):
        with self.assertRaises(ValidationError):
            _fact(value=None, data_status=DataStatus.CONFLICTING_SOURCES,
                  primary_source_ref="s1", notes="only one source")

    def test_duplicate_primary_and_supporting_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value="x", data_status=DataStatus.AVAILABLE,
                  primary_source_ref="s1", supporting_source_refs=["s1"])

    def test_duplicate_supporting_refs_fail(self):
        with self.assertRaises(ValidationError):
            _fact(value="x", data_status=DataStatus.AVAILABLE,
                  primary_source_ref="s1", supporting_source_refs=["s2", "s2"])

    def test_empty_string_value_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value="   ", data_status=DataStatus.AVAILABLE, primary_source_ref="s1")

    def test_empty_string_notes_fails(self):
        with self.assertRaises(ValidationError):
            _fact(value="x", data_status=DataStatus.AVAILABLE, primary_source_ref="s1", notes="")

    def test_unknown_list_as_empty_list_fails(self):
        with self.assertRaises(ValidationError):
            Fact[list](value=[], data_status=DataStatus.UNKNOWN, volatility=Volatility.MODERATE)


if __name__ == "__main__":
    unittest.main()
