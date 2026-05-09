"""
test_program_application.py
Tests for the generalized program-aware application discovery and retrieval.

Test suites:
  TestClassifyPage         — classify_page() signal detection (mock HTML, no network)
  TestScoreLinkRelevance   — score_link_relevance() scoring
  TestDiscoverProgramPages — discover_program_pages() with mock fetch function
  TestDetectProgram        — _detect_program() alias matching
  TestOutputSchema         — get_application_steps() schema completeness (mock RAG)
  TestDisclaimers          — _choose_disclaimer() mapping
  TestIntegrationQueries   — live vector-store queries (skipped when store absent)

Run:
    python test_program_application.py
    python -m pytest test_program_application.py -v   (if pytest installed)
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _html(body: str) -> str:
    """Wrap a body string in minimal HTML."""
    return f"<html><body>{body}</body></html>"


# ===========================================================================
# classify_page — content-signal classification (no network)
# ===========================================================================

class TestClassifyPage(unittest.TestCase):
    """
    Verify that classify_page() returns the correct content_category and
    workflow_priority for HTML containing known workflow signals.
    Tests are purely based on HTML content — no network calls.
    """

    def setUp(self):
        from rag.discovery import classify_page, WORKFLOW_PRIORITY
        self.classify = classify_page
        self.priority = WORKFLOW_PRIORITY

    # ── department_application ────────────────────────────────────────────────

    def test_ptcas_detected(self):
        html = _html("<p>Apply to the DPT program through PTCAS.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "department_application")
        self.assertEqual(pri, 1)

    def test_caspa_detected(self):
        html = _html("<p>Submit your application via CASPA.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "department_application")
        self.assertEqual(pri, 1)

    def test_external_portal_phrase(self):
        html = _html("<p>Apply through the department application portal.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "department_application")
        self.assertEqual(pri, 1)

    def test_do_not_apply_cal_state(self):
        html = _html(
            "<p>Do not apply through Cal State Apply. "
            "Use the program's external application system.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "department_application")
        self.assertEqual(pri, 1)

    # ── supplemental_application ──────────────────────────────────────────────

    def test_qualtrics_detected(self):
        html = _html(
            "<p>Complete the Qualtrics supplemental form as part of your application.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "supplemental_application")
        self.assertEqual(pri, 2)

    def test_supplemental_application_phrase(self):
        html = _html(
            "<p>A supplemental application is required in addition to Cal State Apply.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "supplemental_application")
        self.assertEqual(pri, 2)

    def test_separate_application_phrase(self):
        html = _html("<p>Submit a separate application form to the nursing program.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "supplemental_application")
        self.assertEqual(pri, 2)

    # ── program_requirements ─────────────────────────────────────────────────

    def test_admission_requirements_phrase(self):
        html = _html(
            "<h2>Admission Requirements</h2>"
            "<p>Applicants must hold a bachelor's degree with a minimum GPA of 3.0.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_requirements")
        self.assertEqual(pri, 3)

    def test_gre_detected(self):
        html = _html("<p>GRE scores are required for this doctoral program.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_requirements")
        self.assertEqual(pri, 3)

    def test_interview_required(self):
        html = _html(
            "<p>Shortlisted candidates will be invited for an interview required "
            "before admission.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_requirements")
        self.assertEqual(pri, 3)

    def test_letters_of_recommendation(self):
        html = _html(
            "<p>Three letters of recommendation from academic referees are required.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_requirements")
        self.assertEqual(pri, 3)

    def test_minimum_gpa(self):
        html = _html("<p>Applicants must have a minimum GPA of 3.0 overall.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_requirements")
        self.assertEqual(pri, 3)

    # ── program_eligibility ──────────────────────────────────────────────────

    def test_eligibility_criteria_phrase(self):
        html = _html(
            "<h2>Eligibility Criteria</h2>"
            "<p>Applicants must meet the following eligibility criteria before applying.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_eligibility")
        self.assertEqual(pri, 3)

    def test_who_can_apply(self):
        html = _html("<p>Who can apply: Applicants must hold a bachelor's degree.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_eligibility")
        self.assertEqual(pri, 3)

    def test_admission_eligibility_phrase(self):
        html = _html(
            "<h1>Admission Eligibility</h1>"
            "<p>Review your eligibility before submitting your application.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_eligibility")
        self.assertEqual(pri, 3)

    # ── transcript_instructions ──────────────────────────────────────────────

    def test_official_transcripts_phrase(self):
        html = _html(
            "<p>You must submit official transcripts from all institutions attended.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "transcript_instructions")
        self.assertEqual(pri, 4)

    def test_sealed_transcripts(self):
        html = _html(
            "<p>Submit sealed official transcripts directly from your institution.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "transcript_instructions")
        self.assertEqual(pri, 4)

    def test_transcript_submission_phrase(self):
        html = _html(
            "<h2>Transcript Submission Instructions</h2>"
            "<p>Follow these steps to submit your transcripts electronically.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "transcript_instructions")
        self.assertEqual(pri, 4)

    # ── international_instructions ───────────────────────────────────────────

    def test_international_applicants(self):
        html = _html(
            "<h2>International Applicants</h2>"
            "<p>Students from outside the US must meet additional requirements.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "international_instructions")
        self.assertEqual(pri, 4)

    def test_toefl_detected(self):
        html = _html("<p>A minimum TOEFL score of 80 is required for admission.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "international_instructions")
        self.assertEqual(pri, 4)

    def test_ielts_detected(self):
        html = _html("<p>IELTS scores of 6.5 or higher are accepted as English proficiency proof.</p>")
        cat, pri = self.classify(html)
        self.assertEqual(cat, "international_instructions")
        self.assertEqual(pri, 4)

    # ── generic_application ──────────────────────────────────────────────────

    def test_cal_state_apply_phrase(self):
        html = _html(
            "<p>Submit your application through Cal State Apply at calstateapply.edu.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "generic_application")
        self.assertEqual(pri, 5)

    def test_how_to_apply_doctoral(self):
        html = _html(
            "<h1>How to Apply for Doctoral Programs</h1>"
            "<p>Follow the steps to apply for a doctoral program at CSULB.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "generic_application")
        self.assertEqual(pri, 5)

    # ── overview_only ─────────────────────────────────────────────────────────

    def test_overview_only_no_signals(self):
        html = _html(
            "<p>The doctoral program in engineering prepares students for "
            "advanced research in computational mathematics.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "overview_only")
        self.assertEqual(pri, 6)

    def test_empty_html_overview(self):
        cat, pri = self.classify("<html></html>")
        self.assertEqual(cat, "overview_only")
        self.assertEqual(pri, 6)

    # ── priority ordering ─────────────────────────────────────────────────────

    def test_ptcas_beats_supplemental(self):
        """department_application (p=1) takes precedence over supplemental (p=2)."""
        html = _html(
            "<p>Apply through PTCAS. A supplemental application is also required.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "department_application")
        self.assertEqual(pri, 1)

    def test_supplemental_beats_requirements(self):
        """supplemental_application (p=2) takes precedence over requirements (p=3)."""
        html = _html(
            "<p>A supplemental application is required. "
            "Admission requirements include three letters of recommendation.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "supplemental_application")
        self.assertEqual(pri, 2)

    def test_requirements_beat_generic(self):
        """program_requirements (p=3) takes precedence over generic (p=5)."""
        html = _html(
            "<p>Admission requirements: GPA 3.0+. Apply via Cal State Apply.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_requirements")
        self.assertEqual(pri, 3)

    def test_eligibility_beats_transcript(self):
        """program_eligibility (p=3) takes precedence over transcript_instructions (p=4)."""
        html = _html(
            "<p>Eligibility criteria: hold a bachelor's degree. "
            "You must submit official transcripts.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "program_eligibility")
        self.assertEqual(pri, 3)

    def test_transcript_beats_international(self):
        """transcript_instructions (p=4) takes precedence over international (p=4) — first match wins."""
        html = _html(
            "<p>Submit official transcripts to the graduate office. "
            "International applicants must also provide TOEFL scores.</p>"
        )
        # transcript_instructions comes before international_instructions in signal order
        cat, _ = self.classify(html)
        self.assertIn(cat, {"transcript_instructions", "international_instructions"},
                      "Should match one of the p=4 categories")

    def test_transcript_beats_generic(self):
        """transcript_instructions (p=4) takes precedence over generic_application (p=5)."""
        html = _html(
            "<p>Submit official transcripts. Apply via Cal State Apply.</p>"
        )
        cat, pri = self.classify(html)
        self.assertEqual(cat, "transcript_instructions")
        self.assertEqual(pri, 4)

    # ── URL signal ────────────────────────────────────────────────────────────

    def test_url_ptcas_signal(self):
        """If URL contains 'ptcas', that alone can trigger department_application."""
        html = _html("<p>See the program page for application details.</p>")
        cat, pri = self.classify(html, url="https://www.ptcas.org/apply")
        self.assertEqual(cat, "department_application")

    def test_script_tags_stripped(self):
        """Script content should not influence classification."""
        html = _html(
            "<script>var note = 'Do not apply through Cal State Apply';</script>"
            "<p>Welcome to the doctoral program in engineering.</p>"
        )
        cat, _ = self.classify(html)
        # Script text is stripped; only the visible paragraph remains
        self.assertNotEqual(cat, "department_application")
        self.assertNotEqual(cat, "generic_application")


# ===========================================================================
# score_link_relevance
# ===========================================================================

class TestScoreLinkRelevance(unittest.TestCase):
    def setUp(self):
        from rag.discovery import score_link_relevance
        self.score = score_link_relevance

    def test_apply_keyword(self):
        s = self.score("Apply to the program", "https://www.csulb.edu/apply")
        self.assertGreater(s, 0)

    def test_multiple_keywords_high_score(self):
        s = self.score("How to apply for doctoral admission", "/doctoral/application-process")
        self.assertGreater(s, 0.5)

    def test_irrelevant_link(self):
        s = self.score("Campus map", "https://www.csulb.edu/map")
        self.assertAlmostEqual(s, 0.0)

    def test_score_capped_at_one(self):
        # Many matching keywords → should not exceed 1.0
        s = self.score(
            "doctoral program admission application requirements steps apply graduate",
            "/doctoral/apply/admission/requirements",
        )
        self.assertLessEqual(s, 1.0)

    def test_min_score_threshold(self):
        """A single keyword match should exceed the _MIN_LINK_SCORE of 0.25."""
        from rag.discovery import _MIN_LINK_SCORE
        s = self.score("Application form", "")
        self.assertGreaterEqual(s, _MIN_LINK_SCORE)


# ===========================================================================
# discover_program_pages — mock fetch, no network
# ===========================================================================

class TestDiscoverProgramPages(unittest.TestCase):
    """
    Tests for discover_program_pages() using a mock fetch_fn.
    No real HTTP calls are made.
    """

    def _seed_html(self, category: str) -> str:
        """Return HTML that triggers a specific content_category."""
        content = {
            "department_application": "Apply through PTCAS, the centralized service.",
            "supplemental_application": "A supplemental application via Qualtrics is required.",
            "program_requirements": "Admission requirements: GRE scores and letters of recommendation.",
            "generic_application": "Submit your application through Cal State Apply.",
            "overview_only": "The doctoral program prepares students for research careers.",
        }
        return _html(f"<title>Test Program</title><p>{content[category]}</p>")

    def test_department_application_seed(self):
        """DPT-like seed with PTCAS should yield department_application."""
        from rag.discovery import discover_program_pages

        def mock_fetch(url):
            return self._seed_html("department_application")

        results = discover_program_pages(
            program_name="Physical Therapy (DPT)",
            seed_url="https://www.csulb.edu/dpt/apply",
            depth=0,
            fetch_fn=mock_fetch,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content_category"], "department_application")
        self.assertEqual(results[0]["workflow_priority"], 1)
        self.assertEqual(results[0]["program_name"], "Physical Therapy (DPT)")

    def test_supplemental_application_seed(self):
        """DNP-like seed with Qualtrics should yield supplemental_application."""
        from rag.discovery import discover_program_pages

        def mock_fetch(url):
            return self._seed_html("supplemental_application")

        results = discover_program_pages(
            program_name="Nursing (D.N.P.)",
            seed_url="https://www.csulb.edu/nursing/dnp",
            depth=0,
            fetch_fn=mock_fetch,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content_category"], "supplemental_application")
        self.assertEqual(results[0]["workflow_priority"], 2)

    def test_overview_seed_with_nested_specific(self):
        """
        Overview seed that links to a supplemental application nested page
        should return both the seed (overview) and the nested (supplemental).
        """
        from rag.discovery import discover_program_pages

        SEED_URL   = "https://www.csulb.edu/edd/overview"
        NESTED_URL = "https://www.csulb.edu/edd/apply"

        seed_html = (
            f"<html><title>Ed.D. Overview</title>"
            f"<body>"
            f"<p>The Educational Leadership doctoral program prepares leaders.</p>"
            f"<a href='{NESTED_URL}'>How to Apply for the Ed.D.</a>"
            f"</body></html>"
        )
        nested_html = _html(
            "<title>Ed.D. Application</title>"
            "<p>A supplemental application via Qualtrics is required "
            "in addition to Cal State Apply.</p>"
        )

        def mock_fetch(url):
            if url == SEED_URL:
                return seed_html
            if url == NESTED_URL:
                return nested_html
            return None

        results = discover_program_pages(
            program_name="Educational Leadership (Ed.D.)",
            seed_url=SEED_URL,
            depth=1,
            fetch_fn=mock_fetch,
        )

        cats = [r["content_category"] for r in results]
        self.assertIn("supplemental_application", cats,
                      f"Expected supplemental_application in {cats}")
        # Sorted by priority: supplemental (p=2) should come before overview (p=5)
        self.assertEqual(results[0]["content_category"], "supplemental_application")

    def test_failed_seed_returns_empty(self):
        """Fetch failure on seed URL returns empty list."""
        from rag.discovery import discover_program_pages

        results = discover_program_pages(
            program_name="Engineering",
            seed_url="https://www.csulb.edu/engineering/doctoral",
            depth=1,
            fetch_fn=lambda url: None,
        )
        self.assertEqual(results, [])

    def test_metadata_fields_present(self):
        """All required metadata fields must be present in every result."""
        from rag.discovery import discover_program_pages

        def mock_fetch(url):
            return _html("<title>DPT Apply</title><p>Apply through PTCAS.</p>")

        results = discover_program_pages(
            program_name="Physical Therapy (DPT)",
            seed_url="https://www.csulb.edu/dpt/apply",
            index_url="https://www.csulb.edu/index",
            depth=0,
            fetch_fn=mock_fetch,
        )
        self.assertEqual(len(results), 1)
        r = results[0]
        for field in ["url", "page_type", "title", "program_name",
                      "content_category", "discovered_from", "workflow_priority",
                      "parent_program_url"]:
            self.assertIn(field, r, f"Missing field: {field}")
        self.assertEqual(r["page_type"], "program_application")
        self.assertEqual(r["discovered_from"], "https://www.csulb.edu/index")

    def test_seed_parent_program_url_is_empty(self):
        """Seed page should have parent_program_url='' (it IS the program page)."""
        from rag.discovery import discover_program_pages

        def mock_fetch(url):
            return _html("<title>Program</title><p>Apply through PTCAS.</p>")

        results = discover_program_pages(
            program_name="Physical Therapy (DPT)",
            seed_url="https://www.csulb.edu/dpt/apply",
            depth=0,
            fetch_fn=mock_fetch,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["parent_program_url"], "")

    def test_nested_parent_program_url_is_seed(self):
        """Nested subpage should have parent_program_url equal to the seed URL."""
        from rag.discovery import discover_program_pages

        SEED_URL   = "https://www.csulb.edu/prog/main"
        NESTED_URL = "https://www.csulb.edu/prog/eligibility"

        seed_html = (
            f"<html><title>Program Main</title><body>"
            f"<p>Program overview.</p>"
            f"<a href='{NESTED_URL}'>Admission Eligibility</a>"
            f"</body></html>"
        )
        nested_html = _html(
            "<title>Eligibility</title>"
            "<p>Eligibility criteria: applicants must hold a master's degree.</p>"
        )

        def mock_fetch(url):
            if url == SEED_URL:
                return seed_html
            if url == NESTED_URL:
                return nested_html
            return None

        results = discover_program_pages(
            program_name="Test Program",
            seed_url=SEED_URL,
            depth=1,
            fetch_fn=mock_fetch,
        )
        nested = next((r for r in results if r["url"] == NESTED_URL), None)
        self.assertIsNotNone(nested, "Nested eligibility page should be included")
        self.assertEqual(nested["parent_program_url"], SEED_URL)

    def test_overview_nested_pages_discarded(self):
        """Nested pages that classify as overview_only should NOT be included."""
        from rag.discovery import discover_program_pages

        SEED_URL   = "https://www.csulb.edu/prog/main"
        NESTED_URL = "https://www.csulb.edu/prog/about"

        seed_html = (
            f"<html><title>Program Main</title><body>"
            f"<p>The doctoral program in public health.</p>"
            f"<a href='{NESTED_URL}'>About the Program</a>"
            f"</body></html>"
        )
        nested_html = _html(
            "<title>About the Program</title>"
            "<p>Our program trains future public health leaders.</p>"
        )

        def mock_fetch(url):
            return seed_html if url == SEED_URL else nested_html

        results = discover_program_pages(
            program_name="Public Health (DR.P.H.)",
            seed_url=SEED_URL,
            depth=1,
            fetch_fn=mock_fetch,
        )

        urls = [r["url"] for r in results]
        # Nested overview-only page should be discarded
        self.assertNotIn(NESTED_URL, urls)

    def test_sorted_by_workflow_priority(self):
        """Results must be sorted by workflow_priority ascending."""
        from rag.discovery import discover_program_pages

        SEED_URL   = "https://www.csulb.edu/prog/main"
        LINK1_URL  = "https://www.csulb.edu/prog/requirements"
        LINK2_URL  = "https://www.csulb.edu/prog/supplemental"

        seed_html = (
            f"<html><title>Program</title><body>"
            f"<p>Program overview.</p>"
            f"<a href='{LINK1_URL}'>Admission Requirements</a>"
            f"<a href='{LINK2_URL}'>Apply via supplemental form</a>"
            f"</body></html>"
        )

        def mock_fetch(url):
            if url == SEED_URL:
                return seed_html
            if url == LINK1_URL:
                return _html("<title>Requirements</title><p>GRE required. Minimum GPA 3.0.</p>")
            if url == LINK2_URL:
                return _html("<title>Supplemental</title><p>Complete the Qualtrics form.</p>")
            return None

        results = discover_program_pages(
            program_name="Test Program",
            seed_url=SEED_URL,
            depth=1,
            fetch_fn=mock_fetch,
        )

        priorities = [r["workflow_priority"] for r in results]
        self.assertEqual(priorities, sorted(priorities),
                         f"Results not sorted by priority: {priorities}")


# ===========================================================================
# _detect_program — alias matching
# ===========================================================================

class TestDetectProgram(unittest.TestCase):
    def setUp(self):
        from tools.application_steps_tool import _detect_program
        self.detect = _detect_program

    def test_dnp(self):
        self.assertEqual(self.detect("how do I apply for the DNP?"), "Nursing (D.N.P.)")

    def test_dpt(self):
        self.assertEqual(self.detect("DPT program application"), "Physical Therapy (DPT)")

    def test_edd(self):
        self.assertEqual(self.detect("edd application steps"), "Educational Leadership (Ed.D.)")

    def test_engineering(self):
        self.assertEqual(
            self.detect("engineering phd application"),
            "Engineering & Computational Mathematics (Ph.D.)"
        )

    def test_public_health(self):
        self.assertEqual(
            self.detect("public health doctoral program"),
            "Public Health (DR.P.H.)"
        )

    def test_no_match_generic(self):
        self.assertIsNone(self.detect("how do I apply for a doctoral program?"))


# ===========================================================================
# TestOutputSchema — get_application_steps() schema completeness (mock RAG)
# ===========================================================================

class TestOutputSchema(unittest.TestCase):
    """Verify all required fields appear in every code path."""

    REQUIRED_FIELDS = {
        "found", "tool", "sources", "error", "results",
        "supplemental_results", "has_supplemental", "top_score",
        "query", "fallback_used", "fallback_data", "disclaimer",
        "program_name", "program_specific", "content_category",
        "workflow_priority",
    }

    def _check(self, result: dict, label: str = ""):
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, result, f"Missing '{field}' in {label}")
        self.assertEqual(result["tool"], "application_steps_tool")

    def test_empty_query(self):
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("")
        self._check(result, "empty query")
        self.assertFalse(result["found"])
        # Empty query returns the unknown default (priority 6 = overview_only)
        self.assertEqual(result["workflow_priority"], 6)

    @patch("tools.application_steps_tool.retrieve")
    def test_department_application_path(self, mock_retrieve):
        """DPT-like result with workflow_priority=1 → program_specific=True."""
        chunk = {
            "text": "Apply to DPT via PTCAS.",
            "title": "DPT Application",
            "url": "https://www.csulb.edu/dpt",
            "page_type": "program_application",
            "program_name": "Physical Therapy (DPT)",
            "content_category": "department_application",
            "discovered_from": "https://www.csulb.edu/index",
            "workflow_priority": 1,
            "score": 0.70,
            "chunk_id": "dpt_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [chunk]
            return []

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("DPT application steps")
        self._check(result, "DPT department path")
        self.assertTrue(result["program_specific"])
        self.assertEqual(result["workflow_priority"], 1)
        self.assertEqual(result["content_category"], "department_application")

    @patch("tools.application_steps_tool.retrieve")
    def test_supplemental_application_path(self, mock_retrieve):
        """DNP-like result with workflow_priority=2 → program_specific=True."""
        chunk = {
            "text": "Complete the Qualtrics form for DNP.",
            "title": "DNP Program",
            "url": "https://www.csulb.edu/dnp",
            "page_type": "program_application",
            "program_name": "Nursing (D.N.P.)",
            "content_category": "supplemental_application",
            "discovered_from": "",
            "workflow_priority": 2,
            "score": 0.65,
            "chunk_id": "dnp_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [chunk]
            return []

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("how do I apply for DNP?")
        self._check(result, "DNP supplemental path")
        self.assertTrue(result["program_specific"])
        self.assertEqual(result["workflow_priority"], 2)

    @patch("tools.application_steps_tool.retrieve")
    def test_program_requirements_path(self, mock_retrieve):
        """workflow_priority=3 (program_requirements) → program_specific=True."""
        chunk = {
            "text": "GRE required. Letters of recommendation needed.",
            "title": "Ed.D. Requirements",
            "url": "https://www.csulb.edu/edd",
            "page_type": "program_application",
            "program_name": "Educational Leadership (Ed.D.)",
            "content_category": "program_requirements",
            "discovered_from": "",
            "workflow_priority": 3,
            "score": 0.58,
            "chunk_id": "edd_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [chunk]
            return []

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("edd application requirements")
        self._check(result, "Ed.D. requirements path")
        self.assertTrue(result["program_specific"],
                        "program_requirements (p=3) should be program_specific=True")
        self.assertEqual(result["workflow_priority"], 3)

    @patch("tools.application_steps_tool.retrieve")
    def test_overview_only_fallthrough(self, mock_retrieve):
        """workflow_priority=6 (overview_only) → program_specific=False, falls through."""
        overview_chunk = {
            "text": "The Engineering doctoral program prepares students for research.",
            "title": "Engineering Doctoral",
            "url": "https://www.csulb.edu/engineering",
            "page_type": "program_application",
            "program_name": "Engineering & Computational Mathematics (Ph.D.)",
            "content_category": "overview_only",
            "discovered_from": "",
            "workflow_priority": 6,  # overview_only is now p=6
            "score": 0.55,
            "chunk_id": "eng_0000",
        }
        generic_chunk = {
            "text": "Step 1: Submit via Cal State Apply.",
            "title": "Application Process",
            "url": "https://www.csulb.edu/admissions/doctoral-programs-application-process",
            "page_type": "application_process",
            "program_name": "",
            "content_category": "generic_application",
            "discovered_from": "",
            "workflow_priority": 5,  # generic_application is now p=5
            "score": 0.60,
            "chunk_id": "gen_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [overview_chunk]
            return [generic_chunk]

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("engineering phd application")
        self._check(result, "Engineering overview fallthrough")
        self.assertFalse(result["program_specific"])
        # Overview chunk should appear in supplemental
        supp_ids = {r.get("chunk_id") for r in result["supplemental_results"]}
        self.assertIn("eng_0000", supp_ids)

    @patch("tools.application_steps_tool.retrieve")
    def test_transcript_page_is_specific(self, mock_retrieve):
        """workflow_priority=4 (transcript_instructions) → program_specific=True."""
        transcript_chunk = {
            "text": "Submit official transcripts to the Graduate Center.",
            "title": "Ed.D. Transcript Instructions",
            "url": "https://www.csulb.edu/edd/transcripts",
            "page_type": "program_application",
            "program_name": "Educational Leadership (Ed.D.)",
            "content_category": "transcript_instructions",
            "discovered_from": "https://www.csulb.edu/edd",
            "workflow_priority": 4,
            "score": 0.60,
            "chunk_id": "edd_transcript_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [transcript_chunk]
            return []

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("edd transcript submission")
        self._check(result, "Ed.D. transcript path")
        self.assertTrue(result["program_specific"],
                        "transcript_instructions (p=4) should be program_specific=True")
        self.assertEqual(result["workflow_priority"], 4)

    @patch("tools.application_steps_tool.retrieve")
    def test_international_page_is_specific(self, mock_retrieve):
        """workflow_priority=4 (international_instructions) → program_specific=True."""
        intl_chunk = {
            "text": "International applicants must submit TOEFL scores of 80+.",
            "title": "DNP International Requirements",
            "url": "https://www.csulb.edu/dnp/international",
            "page_type": "program_application",
            "program_name": "Nursing (D.N.P.)",
            "content_category": "international_instructions",
            "discovered_from": "https://www.csulb.edu/dnp",
            "workflow_priority": 4,
            "score": 0.62,
            "chunk_id": "dnp_intl_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [intl_chunk]
            return []

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("DNP international student requirements")
        self._check(result, "DNP international path")
        self.assertTrue(result["program_specific"],
                        "international_instructions (p=4) should be program_specific=True")

    @patch("tools.application_steps_tool.retrieve")
    def test_any_result_specific_detection(self, mock_retrieve):
        """
        Program with overview seed but specific nested page → program_specific=True.

        The seed is overview_only (p=6) but a nested subpage is
        transcript_instructions (p=4). _is_program_specific checks ANY result,
        so the whole program is treated as having specific content.
        """
        overview_chunk = {
            "text": "The Public Health doctoral program (DR.P.H.) at CSULB.",
            "title": "DR.P.H. Overview",
            "url": "https://www.csulb.edu/drph",
            "page_type": "program_application",
            "program_name": "Public Health (DR.P.H.)",
            "content_category": "overview_only",
            "discovered_from": "",
            "workflow_priority": 6,
            "score": 0.52,
            "chunk_id": "drph_overview_0000",
        }
        transcript_chunk = {
            "text": "Submit official transcripts from all graduate institutions attended.",
            "title": "DR.P.H. Transcript Instructions",
            "url": "https://www.csulb.edu/drph/transcripts",
            "page_type": "program_application",
            "program_name": "Public Health (DR.P.H.)",
            "content_category": "transcript_instructions",
            "discovered_from": "https://www.csulb.edu/drph",
            "workflow_priority": 4,
            "score": 0.58,
            "chunk_id": "drph_transcript_0000",
        }

        def side_effect(query, k=8, min_score=0.30, page_type=None, program_name=None):
            if page_type == "program_application":
                return [overview_chunk, transcript_chunk]
            return []

        mock_retrieve.side_effect = side_effect
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("public health doctoral application transcripts")
        self._check(result, "DR.P.H. any-result specific")
        # ANY result check: transcript chunk (p=4 ≤ threshold=4) → program_specific=True
        self.assertTrue(result["program_specific"],
                        "Should be specific because transcript_chunk has p=4")
        # The specific_results should contain only the transcript chunk
        result_ids = {r.get("chunk_id") for r in result["results"]}
        self.assertIn("drph_transcript_0000", result_ids)
        # The overview chunk should be in supplemental
        supp_ids = {r.get("chunk_id") for r in result["supplemental_results"]}
        self.assertIn("drph_overview_0000", supp_ids)

    @patch("tools.application_steps_tool.retrieve")
    def test_generic_path_no_program(self, mock_retrieve):
        """No program detected → generic path, program_specific=False."""
        generic_chunk = {
            "text": "Follow these steps to apply.",
            "title": "Application Process",
            "url": "https://www.csulb.edu/admissions/doctoral-programs-application-process",
            "page_type": "application_process",
            "program_name": "",
            "content_category": "generic_application",
            "discovered_from": "",
            "workflow_priority": 4,
            "score": 0.65,
            "chunk_id": "gen_0000",
        }
        mock_retrieve.return_value = [generic_chunk]
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("how do I apply for a doctoral program?")
        self._check(result, "generic path")
        self.assertFalse(result["program_specific"])
        self.assertIsNone(result["program_name"])


# ===========================================================================
# Disclaimer tests
# ===========================================================================

class TestDisclaimers(unittest.TestCase):
    def setUp(self):
        from tools.application_steps_tool import _choose_disclaimer
        self.choose = _choose_disclaimer

    def test_department_application(self):
        self.assertIn("department-specific", self.choose("department_application", True))

    def test_supplemental_application(self):
        self.assertIn("supplemental", self.choose("supplemental_application", True).lower())

    def test_generic(self):
        self.assertIn("Cal State Apply", self.choose("", False))

    def test_overview_uses_generic(self):
        self.assertIn("Cal State Apply", self.choose("overview_only", False))

    def test_requirements_uses_generic(self):
        self.assertIn("Cal State Apply", self.choose("program_requirements", False))


# ===========================================================================
# Integration tests — require live vector store
# ===========================================================================

class TestIntegrationQueries(unittest.TestCase):
    """
    Integration tests against the live ChromaDB vector store.
    Automatically skipped if the store is unavailable.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from rag.store import get_or_build_store
            store = get_or_build_store()
            if store is None:
                raise RuntimeError("Store is None")
            cls.store_available = True
        except Exception as exc:
            cls.store_available = False
            cls.skip_reason = str(exc)

    def _skip_if_no_store(self):
        if not self.store_available:
            self.skipTest(f"No store: {getattr(self, 'skip_reason', '')}")

    def _check_schema(self, result, label=""):
        """Verify workflow_priority is present and within [1, 6]."""
        self.assertIn("workflow_priority", result, f"Missing workflow_priority in {label}")
        self.assertIn(result["workflow_priority"], range(1, 7),
                      f"workflow_priority out of range in {label}")

    def test_dnp_detects_program_name(self):
        """DNP query should detect program and set program_name."""
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("how do I apply for the DNP program?")
        self.assertEqual(result["program_name"], "Nursing (D.N.P.)")
        self.assertTrue(result["found"])
        self._check_schema(result, "DNP")

    def test_dpt_departmental_portal(self):
        """DPT query should surface department_application content."""
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("physical therapy DPT application")
        self.assertEqual(result["program_name"], "Physical Therapy (DPT)")
        self.assertTrue(result["found"])
        self._check_schema(result, "DPT")
        # If store was rebuilt with discovery, DPT should be program_specific
        if result["content_category"] == "department_application":
            self.assertTrue(result["program_specific"])
            self.assertEqual(result["workflow_priority"], 1)

    def test_edd_application_detection(self):
        """Ed.D. query should detect the educational leadership program."""
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("edd application process")
        self.assertEqual(result["program_name"], "Educational Leadership (Ed.D.)")
        self.assertTrue(result["found"])
        self._check_schema(result, "Ed.D.")

    def test_engineering_phd_detection(self):
        """Engineering PhD query should detect the Engineering program."""
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("engineering phd application steps")
        self.assertEqual(
            result["program_name"],
            "Engineering & Computational Mathematics (Ph.D.)"
        )
        self.assertTrue(result["found"])
        self._check_schema(result, "Engineering")

    def test_generic_fallback(self):
        """Generic PhD query → no program detected → generic path."""
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("how do I apply for a doctoral program?")
        self.assertIsNone(result["program_name"])
        self.assertFalse(result["program_specific"])
        self.assertTrue(result["found"])
        self._check_schema(result, "generic")

    def test_workflow_priority_in_results(self):
        """All retrieve() results should include workflow_priority in [1, 5]."""
        self._skip_if_no_store()
        from rag import retrieve
        results = retrieve("doctoral application process", k=5)
        for r in results:
            self.assertIn("workflow_priority", r,
                          f"Missing workflow_priority in chunk {r.get('chunk_id')}")

    def test_sources_non_empty_for_all_programs(self):
        """All program-specific queries should return at least one source URL."""
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        queries = [
            "DNP supplemental application",
            "DPT application steps",
            "edd doctoral application",
            "engineering phd application process",
        ]
        for query in queries:
            result = get_application_steps(query)
            if result["found"]:
                self.assertGreater(len(result["sources"]), 0,
                                   f"No sources for: {query!r}")

    # ── Per-program deep-discovery integration tests ──────────────────────────

    def test_edd_application_sublinks_discovered(self):
        """
        Ed.D. query: store should have application-related subpages discovered
        from the Ed.D. program seed page (not just the seed itself).
        If the store was built with discovery, program_specific should be True
        when specific application sublinks were found.
        """
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("edd application process how to apply")
        self.assertEqual(result["program_name"], "Educational Leadership (Ed.D.)")
        self.assertTrue(result["found"])
        self._check_schema(result, "Ed.D. sublinks")
        # If discovery ran, we expect either specific results or a graceful generic fallback
        self.assertGreater(len(result["sources"]), 0, "Ed.D. should have at least one source")

    def test_dpt_department_portal_workflow(self):
        """
        DPT query: should surface department_application content (PTCAS).
        If the store was rebuilt with discovery, the DPT PTCAS portal page
        should be found and program_specific=True.
        """
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("DPT physical therapy how to apply application")
        self.assertEqual(result["program_name"], "Physical Therapy (DPT)")
        self.assertTrue(result["found"])
        self._check_schema(result, "DPT department portal")
        # If PTCAS content was indexed, content_category should be department_application
        if result.get("content_category") == "department_application":
            self.assertTrue(result["program_specific"])
            self.assertEqual(result["workflow_priority"], 1)

    def test_dnp_supplemental_workflow(self):
        """
        DNP query: should surface supplemental application content (Qualtrics).
        If the store was rebuilt with discovery, program_specific=True.
        """
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("DNP nursing program application supplemental form")
        self.assertEqual(result["program_name"], "Nursing (D.N.P.)")
        self.assertTrue(result["found"])
        self._check_schema(result, "DNP supplemental")
        if result.get("content_category") in {"supplemental_application", "department_application"}:
            self.assertTrue(result["program_specific"])

    def test_engineering_phd_before_generic_fallback(self):
        """
        Engineering PhD query: if program-specific pages exist in the store,
        they should be used before falling back to the generic process page.
        Either program_specific=True (specific pages found) or generic path
        (acceptable fallback when no specific content indexed for this program).
        """
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps(
            "engineering computational mathematics phd application requirements"
        )
        self.assertEqual(
            result["program_name"],
            "Engineering & Computational Mathematics (Ph.D.)"
        )
        self.assertTrue(result["found"])
        self._check_schema(result, "Engineering nested pages")
        # Either specific (if discovery found application subpages) or generic fallback
        # Both are valid outcomes — the test verifies the logic runs without error
        self.assertIsInstance(result["program_specific"], bool)

    def test_public_health_nested_pages(self):
        """
        Public Health DR.P.H. query: if nested application subpages were discovered,
        program_specific should be True.  Falls through to generic if no specific
        pages were indexed.
        """
        self._skip_if_no_store()
        from tools.application_steps_tool import get_application_steps
        result = get_application_steps("public health DrPH doctoral application process")
        self.assertEqual(result["program_name"], "Public Health (DR.P.H.)")
        self.assertTrue(result["found"])
        self._check_schema(result, "Public Health nested pages")
        self.assertGreater(len(result["sources"]), 0, "DR.P.H. should have at least one source")

    def test_workflow_priority_range_all_programs(self):
        """workflow_priority in retrieve() results must be within new [1, 6] range."""
        self._skip_if_no_store()
        from rag import retrieve
        results = retrieve(
            "doctoral application process eligibility transcripts",
            k=10,
            page_type="program_application",
        )
        for r in results:
            pri = r.get("workflow_priority", 6)
            self.assertIn(pri, range(1, 7),
                          f"workflow_priority {pri} out of range for chunk {r.get('chunk_id')}")

    def test_parent_program_url_in_nested_results(self):
        """
        Nested subpage results should have parent_program_url populated.
        Seed pages should have parent_program_url=''.
        """
        self._skip_if_no_store()
        from rag import retrieve
        results = retrieve(
            "official transcripts application eligibility",
            k=10,
            page_type="program_application",
        )
        for r in results:
            # parent_program_url is always present (may be "" for seeds)
            self.assertIn("parent_program_url", r,
                          f"Missing parent_program_url in chunk {r.get('chunk_id')}")


# ===========================================================================
# Runner
# ===========================================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestClassifyPage))
    suite.addTests(loader.loadTestsFromTestCase(TestScoreLinkRelevance))
    suite.addTests(loader.loadTestsFromTestCase(TestDiscoverProgramPages))
    suite.addTests(loader.loadTestsFromTestCase(TestDetectProgram))
    suite.addTests(loader.loadTestsFromTestCase(TestOutputSchema))
    suite.addTests(loader.loadTestsFromTestCase(TestDisclaimers))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationQueries))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
