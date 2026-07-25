"""
tests/test_application_links.py
Structured application-link classifier + kind-driven workflow (Option A).

Offline, deterministic, no store. Proves the behavior is generic across
programs (DNP + a second program with a different portal type) and never
hard-codes a per-program renderer. `section` is inferred from kind (documented
in tools/application_links.py); no ingestion change / store rebuild.

Run: pytest tests/test_application_links.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.application_links import (
    ALL_KINDS, classify_link, section_for_kind, structured_links,
)
from tools.application_steps_tool import (
    _clean_requirement_bullets, build_application_workflow,
)

# ── Program 1: DNP (PDF info sheet + Qualtrics dept app + Cal State Apply) ────
DNP_LINKS = [
    {"text": "Document", "url": "https://www.csulb.edu/sites/default/files/2025/documents/BSN-DNP%20Information%20Sheet.pdf"},
    {"text": "APPLY NOW", "url": "https://www.csulb.edu/apply"},
    {"text": "Cal Apply", "url": "https://www2.calstate.edu/apply"},
    {"text": "DNP APPLICATION HERE", "url": "https://csulb.qualtrics.com/jfe/form/SV_1YzHbrPlhknZ0rQ"},
    {"text": "Resource", "url": "https://www.csulb.edu/college-of-health-human-services/school-of-nursing/bsn-dnp-program"},
    {"text": "official transcripts", "url": "https://www.csulb.edu/transcripts"},
    {"text": "Applicant Self-Service", "url": "https://www.csulb.edu/student-records/applicant-self-service"},
]

# ── Program 2: DPT (PDF info sheet + PTCAS centralized service + Cal State Apply) ─
DPT_LINKS = [
    {"text": "Document", "url": "https://www.csulb.edu/sites/default/files/2024/documents/DPT%20Program%20Fact%20Sheet.pdf"},
    {"text": "PTCAS", "url": "https://ptcas.liaisoncas.com/"},
    {"text": "Apply", "url": "https://www.csulb.edu/apply"},
    {"text": "official transcripts", "url": "https://www.csulb.edu/transcripts"},
]


def _by_kind(links):
    d = {}
    for l in links:
        d.setdefault(l["kind"], []).append(l)
    return d


class TestA_NestedLinkExtraction(unittest.TestCase):
    def test_distinct_structured_links_dnp(self):
        links = structured_links(DNP_LINKS)
        kinds = _by_kind(links)
        self.assertIn("information_sheet", kinds)
        self.assertIn("department_application", kinds)
        self.assertIn("university_application", kinds)
        self.assertEqual(kinds["information_sheet"][0]["label"], "BSN-DNP Information Sheet")
        self.assertIn("qualtrics", kinds["department_application"][0]["url"])

    def test_distinct_structured_links_second_program(self):
        links = structured_links(DPT_LINKS)
        kinds = _by_kind(links)
        self.assertIn("information_sheet", kinds)       # the fact-sheet PDF
        self.assertIn("department_application", kinds)  # PTCAS centralized service
        self.assertIn("university_application", kinds)
        self.assertIn("ptcas", kinds["department_application"][0]["url"])


class TestB_LinkSectionAssociation(unittest.TestCase):
    def test_kind_to_section_inference(self):
        self.assertEqual(section_for_kind("information_sheet"), "supporting_documents")
        self.assertEqual(section_for_kind("department_application"), "application_process")
        self.assertEqual(section_for_kind("university_application"), "application_process")
        self.assertEqual(section_for_kind("transcript_information"), "supporting_documents")
        self.assertEqual(section_for_kind("applicant_portal"), "post_submission")

    def test_every_link_has_all_four_fields(self):
        for e in DNP_LINKS:
            link = classify_link(e["text"], e["url"])
            self.assertEqual(set(link), {"label", "url", "kind", "section"})
            self.assertIn(link["kind"], ALL_KINDS)


class TestC_Deduplication(unittest.TestCase):
    def test_multiple_cal_apply_collapse_to_one(self):
        links = structured_links(DNP_LINKS)  # has APPLY NOW + Cal Apply
        uni = [l for l in links if l["kind"] == "university_application"]
        self.assertEqual(len(uni), 1)
        self.assertEqual(uni[0]["label"], "Cal State Apply")

    def test_exact_duplicate_urls_collapse(self):
        dup = [{"text": "Apply", "url": "https://www.csulb.edu/apply"},
               {"text": "APPLY NOW", "url": "https://www.csulb.edu/apply/"}]
        self.assertEqual(len(structured_links(dup)), 1)


class TestD_NoAnchorTextInBullets(unittest.TestCase):
    def test_leakage_removed_requirements_kept(self):
        raw = [
            "Applicants must hold an accredited BSN.",
            "Minimum GPA of 3.0 required.",
            "Document BSN-DNP Information Sheet.pdf DNP APPLICATION HERE Please fill out the form.",
            "Apply now at https://www.csulb.edu/apply",
            "See the qualtrics form to apply.",
        ]
        cleaned = _clean_requirement_bullets(raw)
        self.assertIn("Applicants must hold an accredited BSN.", cleaned)
        self.assertIn("Minimum GPA of 3.0 required.", cleaned)
        for b in cleaned:
            self.assertNotIn(".pdf", b.lower())
            self.assertNotIn("http", b.lower())
            self.assertNotIn("apply now", b.lower())
            self.assertNotIn("qualtrics", b.lower())
            self.assertFalse(b.lower().startswith("document"))


class TestE_DNPWorkflow(unittest.TestCase):
    def setUp(self):
        self.links = structured_links(DNP_LINKS)
        bullets = _clean_requirement_bullets([
            "An accredited BSN is required.", "Minimum GPA of 3.0.",
            "Submit official transcripts.", "Employment verification required.",
            "An interview and writing assessment may be required.",
        ])
        self.wf = build_application_workflow(bullets, self.links,
                                             "https://www.csulb.edu/.../bsn-dnp-program")

    def _step(self, title_part):
        return next((s for s in self.wf if title_part in s["title"]), None)

    def test_info_sheet_under_review_requirements(self):
        s = self._step("Review admission requirements")
        self.assertTrue(any(l["kind"] == "information_sheet" for l in s["links"]))

    def test_qualtrics_under_department_application(self):
        s = self._step("department application")
        self.assertTrue(any("qualtrics" in l["url"] for l in s["links"]))

    def test_apply_under_university_application(self):
        s = self._step("university application")
        self.assertTrue(any(l["kind"] == "university_application" for l in s["links"]))

    def test_steps_renumbered_and_only_with_content(self):
        nums = [s["step"] for s in self.wf]
        self.assertEqual(nums, list(range(1, len(self.wf) + 1)))
        for s in self.wf:
            self.assertTrue(s["summary_points"] or s["links"])


class TestF_GenericSecondProgram(unittest.TestCase):
    def test_second_program_workflow_no_special_case(self):
        links = structured_links(DPT_LINKS)
        wf = build_application_workflow(
            _clean_requirement_bullets(["A bachelor's degree is required.",
                                        "Submit official transcripts."]),
            links, "https://www.csulb.edu/.../dpt-program")
        titles = " ".join(s["title"] for s in wf)
        self.assertIn("department application", titles)   # PTCAS
        self.assertIn("university application", titles)   # Cal State Apply
        dept = next(s for s in wf if "department application" in s["title"])
        self.assertTrue(any("ptcas" in l["url"] for l in dept["links"]))


class TestG_SourcePreservation(unittest.TestCase):
    def test_original_urls_preserved(self):
        links = structured_links(DNP_LINKS)
        urls = {l["url"] for l in links}
        for required in (
            "https://www.csulb.edu/sites/default/files/2025/documents/BSN-DNP%20Information%20Sheet.pdf",
            "https://csulb.qualtrics.com/jfe/form/SV_1YzHbrPlhknZ0rQ",
        ):
            self.assertIn(required, urls)
        # a university-application URL survives (one of the apply variants)
        self.assertTrue(any(l["kind"] == "university_application" for l in links))


if __name__ == "__main__":
    unittest.main()
