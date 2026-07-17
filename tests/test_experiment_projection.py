"""
tests/test_experiment_projection.py
Projection tests (Phase P5). Synthetic domain fixtures; offline; deterministic.

Run: pytest tests/test_experiment_projection.py -v
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.programs.models import CanonicalProgram
from experiments.rag_vs_finetuning.projection.models import RetrievalDocument
from experiments.rag_vs_finetuning.projection.project import (
    project_program, projection_checksum,
)

FIXTURES = Path(__file__).parent / "fixtures" / "masters_programs"


def _raw(name: str = "well_documented") -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _project(d: dict):
    program = CanonicalProgram.model_validate(d)
    return project_program(program, record_hash="sha256:testhash", projection_version="projection-0.1")


def _sections(res):
    return {doc.section: doc for doc in res.documents}


class TestHappyPath(unittest.TestCase):
    def test_overview_admissions_application_contact(self):
        res = _project(_raw())
        secs = _sections(res)
        self.assertIn("overview", secs)
        self.assertIn("admissions", secs)
        self.assertIn("application", secs)
        self.assertIn("contact", secs)
        self.assertIn("Master of Science in Computer Science", secs["overview"].content)
        self.assertIn("3.0", secs["admissions"].content)

    def test_deterministic_document_ids(self):
        secs = _sections(_project(_raw()))
        self.assertEqual(secs["overview"].document_id, "ms-computer-science::overview")

    def test_contact_projected(self):
        secs = _sections(_project(_raw()))
        self.assertIn("cs.grad@example.edu", secs["contact"].content)

    def test_deterministic_source_ordering(self):
        secs = _sections(_project(_raw()))
        ids = [s.source_id for s in secs["overview"].source_references]
        self.assertEqual(ids, sorted(ids))

    def test_document_json_round_trip(self):
        doc = _sections(_project(_raw()))["overview"]
        back = RetrievalDocument.model_validate_json(doc.model_dump_json())
        self.assertEqual(back, doc)

    def test_identical_input_identical_checksum(self):
        a = _project(_raw()).documents
        b = _project(_raw()).documents
        self.assertEqual(projection_checksum(a), projection_checksum(b))


_TERM = {"audience": "domestic", "deadline": None, "accept_decline_deadline": None}


class TestDeadlineProjection(unittest.TestCase):
    def _with_terms(self, terms):
        d = _raw()
        d["application"]["terms"]["value"] = terms
        d["application"]["terms"]["data_status"] = "available"
        return d

    def test_published_deadline_text_preserved(self):
        d = self._with_terms([
            {**_TERM, "term": "fall", "deadline_kind": "final",
             "deadline_text": "February 15", "accept_decline_deadline_text": "May 18", "notes": None},
        ])
        app = _sections(_project(d))["application"].content
        self.assertIn("February 15", app)
        self.assertIn("May 18", app)
        self.assertNotIn("2027", app)  # no fabricated ISO year

    def test_not_accepting_projected(self):
        d = self._with_terms([
            {**_TERM, "term": "spring", "deadline_kind": "not_accepting",
             "deadline_text": None, "accept_decline_deadline_text": None, "notes": "Not Accepting"},
        ])
        app = _sections(_project(d))["application"].content
        self.assertIn("Not Accepting", app)


class TestMissingValueBehavior(unittest.TestCase):
    def test_unknown_fact_omitted(self):
        d = _raw()
        d["admissions"]["minimum_gpa"] = {
            "value": None, "data_status": "unknown", "volatility": "moderate",
            "primary_source_ref": None, "supporting_source_refs": [],
            "official_text": None, "notes": None}
        secs = _sections(_project(d))
        # gpa no longer appears in admissions (may drop the admissions doc if it was the only fact)
        if "admissions" in secs:
            self.assertNotIn("Minimum GPA", secs["admissions"].content)

    def test_source_missing_fact_omitted(self):
        d = _raw()
        d["admissions"]["tests"] = {
            "value": None, "data_status": "source_missing", "volatility": "moderate",
            "primary_source_ref": "src-prog", "supporting_source_refs": [],
            "official_text": None, "notes": None}
        secs = _sections(_project(d))
        if "admissions" in secs:
            self.assertNotIn("GRE", secs["admissions"].content)

    def test_stale_fact_includes_caveat(self):
        d = _raw()
        d["overview"]["official_summary"]["data_status"] = "stale"
        secs = _sections(_project(d))
        self.assertIn("may be outdated", secs["overview"].content)
        self.assertEqual(secs["overview"].freshness_status, "stale")

    def test_conflicting_sources_omitted_and_warned(self):
        d = _raw()
        d["overview"]["official_summary"] = {
            "value": None, "data_status": "conflicting_sources", "volatility": "stable",
            "primary_source_ref": "src-prog", "supporting_source_refs": ["src-adm"],
            "official_text": None, "notes": "sources disagree"}
        res = _project(d)
        secs = _sections(res)
        self.assertNotIn("overview", secs)  # not projected as resolved fact
        self.assertTrue(any("conflicting" in w for w in res.warnings))


if __name__ == "__main__":
    unittest.main()
