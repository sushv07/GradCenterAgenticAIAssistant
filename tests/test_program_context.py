"""
tests/test_program_context.py
Unit tests for the generic program-context resolver (state/program_context.py).

Offline, deterministic, no store. Proves the resolver is generic across
programs (uses ≥2) and never hard-codes DrPH/DPT behavior.

Run: pytest tests/test_program_context.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from state.program_context import (
    _catalog, augment_query_with_active_program, detect_explicit_program,
    make_active_program, query_uses_program_reference, resolve_program_context,
)

DRPH = make_active_program("drph-public-health", "Public Health", source="recommendation")
DPT = make_active_program("dpt-physical-therapy", "Physical Therapy", source="recommendation")


class TestBridge(unittest.TestCase):
    def test_every_program_maps_to_a_tool_name(self):
        entries, by_tool = _catalog()
        self.assertGreaterEqual(len(entries), 5)
        for e in entries:
            self.assertTrue(e["tool_name"], e["program_id"])
        # spot-check the generic derivation for two different programs
        self.assertEqual(by_tool.get("Public Health (DR.P.H.)")[0], "drph-public-health")
        self.assertEqual(by_tool.get("Physical Therapy (DPT)")[0], "dpt-physical-therapy")

    def test_make_active_program_fills_tool_name(self):
        self.assertEqual(DRPH["tool_name"], "Public Health (DR.P.H.)")
        self.assertEqual(DPT["tool_name"], "Physical Therapy (DPT)")


class TestReferenceDetection(unittest.TestCase):
    def test_positive_references(self):
        for q in ("what is the deadline for this program", "how do I apply to it",
                  "what is its deadline", "tell me about that program",
                  "requirements for the program", "this degree deadline"):
            self.assertTrue(query_uses_program_reference(q), q)

    def test_negative_references(self):
        for q in ("what is the deadline", "who is the advisor",
                  "eligibility requirements", "application steps"):
            self.assertFalse(query_uses_program_reference(q), q)


class TestExplicitDetection(unittest.TestCase):
    def test_explicit_programs_detected(self):
        self.assertEqual(detect_explicit_program("physical therapy deadline")["tool_name"],
                         "Physical Therapy (DPT)")
        self.assertEqual(detect_explicit_program("drph application")["tool_name"],
                         "Public Health (DR.P.H.)")

    def test_broad_subject_is_not_a_program(self):
        # "healthcare" / "doctoral program" are not aliases → no explicit program
        self.assertIsNone(detect_explicit_program("i'm interested in healthcare"))
        self.assertIsNone(detect_explicit_program("i want a doctoral program"))


class TestAugmentation(unittest.TestCase):
    def test_appends_tool_name(self):
        aug = augment_query_with_active_program("what is the deadline for this program", DRPH)
        self.assertEqual(aug, "what is the deadline for this program Public Health")

    def test_no_active_returns_original(self):
        self.assertEqual(augment_query_with_active_program("x", None), "x")


class TestResolvePrecedence(unittest.TestCase):
    def test_explicit_overrides_active(self):
        js = {"active_program": DRPH}
        res = resolve_program_context("what about physical therapy?", js)
        self.assertEqual(res["active"]["tool_name"], "Physical Therapy (DPT)")
        self.assertTrue(res["changed"])
        self.assertEqual(res["tool_query"], "what about physical therapy?")  # unchanged

    def test_contextual_reference_reuses_active(self):
        js = {"active_program": DRPH}
        res = resolve_program_context("what is the deadline for this program", js)
        self.assertEqual(res["active"]["tool_name"], "Public Health (DR.P.H.)")
        self.assertFalse(res["changed"])
        self.assertIn("Public Health", res["tool_query"])

    def test_no_active_no_reference_unresolved(self):
        res = resolve_program_context("what is the deadline", {})
        self.assertIsNone(res["active"])
        self.assertFalse(res["changed"])
        self.assertEqual(res["tool_query"], "what is the deadline")  # not augmented

    def test_broad_category_does_not_overwrite_active(self):
        js = {"active_program": DRPH}
        res = resolve_program_context("i'm interested in healthcare", js)
        # no explicit program, no contextual reference → active unchanged, no augmentation
        self.assertEqual(res["active"]["tool_name"], "Public Health (DR.P.H.)")
        self.assertFalse(res["changed"])
        self.assertEqual(res["tool_query"], "i'm interested in healthcare")

    def test_pronoun_only_message_keeps_active(self):
        js = {"active_program": DPT}
        res = resolve_program_context("how do I apply to it", js)
        self.assertEqual(res["active"]["tool_name"], "Physical Therapy (DPT)")
        self.assertIn("Physical Therapy", res["tool_query"])


if __name__ == "__main__":
    unittest.main()
