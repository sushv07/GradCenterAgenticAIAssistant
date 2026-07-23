"""
tests/test_masters_corpus_quality.py
Phase 7 — corpus-quality improvements (offline, deterministic).

Covers the three evidence-driven fixes:
  1. Drupal widget stripping in extract_main_content_text (CLA landing pages)
  2. Directory-card documents (advisor/deadline facts become retrievable)
  3. Navigation-bleed reduction (canonical URLs + nested host rule) and
     redirect-aware conversion (truthful final-URL provenance + dedup)

No network: synthetic HTML, injected fetchers.

Run: pytest tests/test_masters_corpus_quality.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.extraction import extract_main_content_text
from ingestion.masters.manifest import DiscoveredProgram
from rag.masters_discovery import (
    DiscoveredPage, _nested_host_allowed, canonical_url,
    discover_masters_program_pages,
)
from rag.masters_extraction import build_masters_documents, directory_card_documents

B = "https://www.csulb.edu"
INDEX = f"{B}/graduate-studies-csulb/article/programs-advisors-and-deadlines-masters"

# Mimics the live CLA college landing page: real content + Drupal news widgets.
_CLA_LANDING = """<html><head><title>College of Liberal Arts | CSULB</title></head>
<body><main>
  <h1>College of Liberal Arts</h1>
  <p>The College of Liberal Arts offers graduate programs across many departments,
  with dedicated advising and research opportunities for master's students.</p>
  <div class="views-element-container">
    <div class="view view-group-news"><div class="view-content">
      <div class="views-row"><div class="node node--type-article">
        <h2 class="article-title">Beach alumni leave gift to inspire journalists</h2>
      </div></div>
      <div class="views-row"><div class="node node--type-article">
        <h2 class="article-title">Remembering Frank Fata, Former CLA Associate Dean</h2>
      </div></div>
    </div></div>
  </div>
  <div class="slick-carousel-wrapper"><p>This is a carousel. Go to slide 1.</p></div>
</main></body></html>"""


class TestWidgetStripping(unittest.TestCase):
    def test_news_widgets_removed_content_kept(self):
        title, text = extract_main_content_text(_CLA_LANDING)
        self.assertEqual(title, "College of Liberal Arts")
        self.assertIn("graduate programs across many departments", text)
        self.assertNotIn("Beach alumni", text)               # views container gone
        self.assertNotIn("Frank Fata", text)
        self.assertNotIn("carousel", text)                   # slick wrapper gone

    def test_plain_page_unaffected(self):
        html = "<html><body><main><p>Admission requirements: transcripts.</p></main></body></html>"
        _, text = extract_main_content_text(html)
        self.assertIn("Admission requirements", text)


class TestCanonicalAndHostRules(unittest.TestCase):
    def test_canonical_strips_utm_and_fragment(self):
        u = "http://www.ccpe.csulb.edu/international/?utm_source=website&utm_medium=homepage#top"
        self.assertEqual(canonical_url(u), "http://www.ccpe.csulb.edu/international/")
        # non-tracking params preserved
        self.assertIn("page=2", canonical_url(f"{B}/x?page=2&utm_campaign=z"))

    def test_nested_host_rule(self):
        seed = "https://cla.csulb.edu/departments/linguistics/ma-program/"
        self.assertTrue(_nested_host_allowed(seed, "https://cla.csulb.edu/anything"))
        self.assertTrue(_nested_host_allowed(seed, f"{B}/admissions"))
        self.assertFalse(_nested_host_allowed(seed, "https://www.cpace.csulb.edu/courses/x"))
        self.assertFalse(_nested_host_allowed(seed, "http://www.ccpe.csulb.edu/international/"))

    def test_discovery_drops_bleed_and_dedups_utm(self):
        seed = f"{B}/dept"
        site = {
            seed: f'<html><head><title>D</title></head><body><main>'
                  f'<a href="{B}/dept/apply">how to apply</a>'
                  f'<a href="https://www.cpace.csulb.edu/courses/degree-x">degree application</a>'
                  f'<a href="http://www.ccpe.csulb.edu/international/?utm_source=w">international applicants</a>'
                  f'</main></body></html>',
            f"{B}/dept/apply": "<html><body><main><p>Apply via Cal State Apply. "
                               "Application checklist and steps to apply.</p></main></body></html>",
            "https://www.cpace.csulb.edu/courses/degree-x":
                "<html><body><main><p>Apply now! Application portal external system.</p></main></body></html>",
            "http://www.ccpe.csulb.edu/international/?utm_source=w":
                "<html><body><main><p>International applicants TOEFL requirements.</p></main></body></html>",
        }
        prog = DiscoveredProgram(raw_listing_name="Dept (MS)", normalized_program_name="Dept",
                                 degree_label="MS", official_program_url=seed)
        result = discover_masters_program_pages([prog], depth=1, fetch_fn=site.get)
        urls = {p.url for p in result.pages}
        self.assertIn(f"{B}/dept/apply", urls)               # legit child kept
        self.assertNotIn("https://www.cpace.csulb.edu/courses/degree-x", urls)
        self.assertFalse(any("ccpe.csulb.edu" in u for u in urls))  # bleed dropped


class TestRedirectProvenance(unittest.TestCase):
    def test_final_url_stored_and_redirects_deduped(self):
        landing = f"{B}/college-of-liberal-arts"
        pages = [
            DiscoveredPage(url="https://cla.csulb.edu/departments/ling/", title="",
                           content_category="overview_only", workflow_priority=6,
                           parent_program_url="", discovered_from=INDEX, depth=0,
                           programs=["Ling (MA)"]),
            DiscoveredPage(url="https://cla.csulb.edu/departments/polisci/", title="",
                           content_category="overview_only", workflow_priority=6,
                           parent_program_url="", discovered_from=INDEX, depth=0,
                           programs=["PoliSci (MA)"]),
        ]
        html = ("<html><head><title>CLA</title></head><body><main><p>"
                "College of Liberal Arts graduate programs and advising overview "
                "for prospective master's students.</p></main></body></html>")

        def fetch_final(url):
            return html, landing          # both stale URLs redirect to landing

        docs, summary = build_masters_documents(pages, [], fetch_final_fn=fetch_final)
        self.assertEqual(len(docs), 1)                        # deduped at final URL
        self.assertEqual(docs[0].metadata["source_url"], landing)   # truthful
        self.assertEqual(summary.documents_rejected, 1)
        self.assertTrue(summary.rejections[0][1].startswith("redirect_duplicate"))


class TestDirectoryCards(unittest.TestCase):
    PROG = DiscoveredProgram(
        raw_listing_name="Linguistics (MA)", normalized_program_name="Linguistics",
        degree_label="MA", official_program_url="https://cla.csulb.edu/x",
        advisor_office="Dr. Example Advisor", advisor_email="ling-gradadvising@csulb.edu",
        phone="562-985-0000", fall_application_deadline="April 01",
        spring_application_deadline="November 01", term_availability=["fall", "spring"])

    def test_card_document_contains_facts(self):
        docs = directory_card_documents([self.PROG], INDEX)
        self.assertEqual(len(docs), 1)
        d = docs[0]
        for fact in ("Dr. Example Advisor", "ling-gradadvising@csulb.edu",
                     "Fall application deadline: April 01",
                     "Spring application deadline: November 01"):
            self.assertIn(fact, d.text)
        self.assertEqual(d.metadata["program_name"], "Linguistics")
        self.assertEqual(d.metadata["content_type"], "directory_card")
        self.assertTrue(d.metadata["source_url"].startswith(INDEX + "#"))

    def test_deterministic_distinct_ids(self):
        other = DiscoveredProgram(
            raw_listing_name="Dance (MFA)", normalized_program_name="Dance",
            degree_label="MFA", advisor_email="dance@csulb.edu")
        d1 = directory_card_documents([self.PROG], INDEX)[0]
        d1_again = directory_card_documents([self.PROG], INDEX)[0]
        d2 = directory_card_documents([other], INDEX)[0]
        self.assertEqual(d1.document_id, d1_again.document_id)   # deterministic
        self.assertNotEqual(d1.document_id, d2.document_id)      # distinct per card

    def test_factless_card_not_indexed(self):
        empty = DiscoveredProgram(raw_listing_name="X (MS)", normalized_program_name="X",
                                  degree_label="MS", official_program_url="https://x")
        self.assertEqual(directory_card_documents([empty], INDEX), [])


if __name__ == "__main__":
    unittest.main()
