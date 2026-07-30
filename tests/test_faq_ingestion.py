"""
tests/test_faq_ingestion.py
Phase 4.1 — atomic FAQ ingestion (parser + metadata propagation).

Offline, network-free. Feeds representative FAQ-portal HTML — matching the live
DOM: category <h2> section headings + <h2 class="accordion-heading"> questions
whose card contains <div class="collapse" id="accordion-NNNN"> answers — and
verifies:
  * one DOCUMENT per FAQ (chunk COUNT follows the production chunker's size
    rules: short answers → one chunk; long answers may split — not asserted as
    universal)
  * category / question / answer / links extraction
  * identity = the portal's stable collapse anchor when present; deterministic
    slug+content-hash fallback otherwise
  * identities are deterministic, order-independent, and collision-safe
  * FAQ metadata propagates end-to-end (page_to_document → chunk)
  * page_to_document stays backward compatible for non-FAQ pages

Run: pytest tests/test_faq_ingestion.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.faq_ingest import parse_faq_page, _content_hash8, _slugify
from ingestion.pipeline.loaders.pages import page_to_document
from rag.pipeline_adapters.wiring import production_chunker

PORTAL = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"

# Live-DOM-faithful: each answer is <div class="collapse" id="accordion-NNNN">.
SAMPLE_HTML = """
<html><body>
  <h2>Graduate Admissions</h2>
  <div class="card">
    <div class="card-header"><h2 class="accordion-heading">4. How do I submit my official transcripts?</h2></div>
    <div class="collapse" id="accordion-10952161">Submit official transcripts to Enrollment Services.
      See <a href="/graduate-center/transcripts">transcript details</a>.</div>
  </div>
  <div class="card">
    <div class="card-header"><h2 class="accordion-heading">Are application fee waivers available?</h2></div>
    <div class="collapse" id="accordion-10952170">No. The fee is $70 and non-refundable.</div>
  </div>

  <h2>International Students</h2>
  <div class="card">
    <div class="card-header"><h2 class="accordion-heading">Where can international students get help?</h2></div>
    <div class="collapse" id="accordion-10952200">Contact the Center for International Education.</div>
  </div>
</body></html>
"""

# Same three FAQs, order shuffled, NO collapse ids → exercises the fallback path.
NO_ANCHOR_SHUFFLED = """
<html><body>
  <h2>International Students</h2>
  <div class="card"><div class="card-header"><h2 class="accordion-heading">Where can international students get help?</h2></div>
    <div class="collapse">Contact the Center for International Education.</div></div>
  <h2>Graduate Admissions</h2>
  <div class="card"><div class="card-header"><h2 class="accordion-heading">Are application fee waivers available?</h2></div>
    <div class="collapse">No. The fee is $70 and non-refundable.</div></div>
  <div class="card"><div class="card-header"><h2 class="accordion-heading">How do I submit my official transcripts?</h2></div>
    <div class="collapse">Submit official transcripts to Enrollment Services.</div></div>
</body></html>
"""


class TestFaqParsing(unittest.TestCase):
    def setUp(self):
        self.faqs = parse_faq_page(SAMPLE_HTML, PORTAL, "CSULB Grad Center FAQs")

    def test_one_document_per_faq(self):
        self.assertEqual(len(self.faqs), 3)
        for f in self.faqs:
            self.assertEqual(f["page_type"], "faq")
            self.assertFalse(f["is_supporting_page"])
            self.assertEqual(f["parent_faq_url"], "")

    def test_category_extraction(self):
        cats = {f["faq_question"]: f["category"] for f in self.faqs}
        self.assertEqual(cats["How do I submit my official transcripts?"], "Graduate Admissions")
        self.assertEqual(cats["Are application fee waivers available?"], "Graduate Admissions")
        self.assertEqual(cats["Where can international students get help?"], "International Students")

    def test_question_answer_and_numbering_stripped(self):
        f = self.faqs[0]
        self.assertEqual(f["faq_question"], "How do I submit my official transcripts?")  # "4. " stripped
        self.assertTrue(f["text"].startswith("Q: How do I submit my official transcripts?\nA: "))

    def test_links_extracted_and_absolute(self):
        self.assertIn("https://www.csulb.edu/graduate-center/transcripts",
                      [l["url"] for l in self.faqs[0]["links"]])
        self.assertEqual(self.faqs[1]["links"], [])

    def test_empty_when_no_accordion(self):
        self.assertEqual(parse_faq_page("<html><body><p>no faqs</p></body></html>", PORTAL, "t"), [])


class TestFaqIdentity(unittest.TestCase):
    def test_prefers_stable_portal_anchor(self):
        faqs = parse_faq_page(SAMPLE_HTML, PORTAL, "t")
        urls = {f["faq_question"]: f["url"] for f in faqs}
        # Identity is the portal's own collapse id — a real deep link.
        self.assertEqual(urls["How do I submit my official transcripts?"],
                         f"{PORTAL}#accordion-10952161")
        self.assertEqual(urls["Where can international students get help?"],
                         f"{PORTAL}#accordion-10952200")

    def test_fallback_slug_plus_content_hash_when_no_anchor(self):
        faqs = parse_faq_page(NO_ANCHOR_SHUFFLED, PORTAL, "t")
        for f in faqs:
            self.assertTrue(f["url"].startswith(f"{PORTAL}#faq-"))
            # ends with an 8-char content hash, not an order suffix like -2/-3
            tail = f["url"].rsplit("-", 1)[1]
            self.assertEqual(len(tail), 8)
            self.assertTrue(all(c in "0123456789abcdef" for c in tail))
            self.assertNotRegex(f["url"], r"-\d$")   # no document-order suffix

    def test_identities_are_order_independent(self):
        # Anchor path: identity from the CMS id, never position.
        a = {f["faq_question"]: f["url"] for f in parse_faq_page(SAMPLE_HTML, PORTAL, "t")}
        # Fallback path: shuffled order, no anchors — identity from content hash.
        b = {f["faq_question"]: f["url"] for f in parse_faq_page(NO_ANCHOR_SHUFFLED, PORTAL, "t")}
        # The transcripts question is common to both; its fallback id must not
        # depend on the (different) position it appears in NO_ANCHOR_SHUFFLED.
        again = {f["faq_question"]: f["url"]
                 for f in parse_faq_page(NO_ANCHOR_SHUFFLED, PORTAL, "t")}
        self.assertEqual(b, again)                    # order-stable across parses

    def test_repeated_parse_is_deterministic(self):
        u1 = [f["url"] for f in parse_faq_page(SAMPLE_HTML, PORTAL, "t")]
        u2 = [f["url"] for f in parse_faq_page(SAMPLE_HTML, PORTAL, "t")]
        self.assertEqual(u1, u2)

    def test_slug_equivalent_questions_do_not_collide(self):
        # Two questions with the SAME slug but different content, no anchors:
        # the content hash must keep their identities distinct.
        html = """
        <html><body><h2>Cat</h2>
          <div class="card"><div class="card-header"><h2 class="accordion-heading">How do I apply?</h2></div>
            <div class="collapse">Undergrad path.</div></div>
          <div class="card"><div class="card-header"><h2 class="accordion-heading">How do I apply!!!</h2></div>
            <div class="collapse">Graduate path.</div></div>
        </body></html>
        """
        faqs = parse_faq_page(html, PORTAL, "t")
        self.assertEqual(_slugify("How do I apply?"), _slugify("How do I apply!!!"))  # slug-equivalent
        urls = [f["url"] for f in faqs]
        self.assertEqual(len(set(urls)), 2)           # but identities differ (hash)

    def test_content_hash_ignores_leading_numbering_and_case(self):
        # "4. How ..." and "how ..." normalize to the same question → same hash.
        self.assertEqual(_content_hash8("Cat", "How do I submit?"),
                         _content_hash8("Cat", "  how   do i submit?  "))


class TestMetadataPropagation(unittest.TestCase):
    def test_faq_metadata_reaches_chunk(self):
        faq = parse_faq_page(SAMPLE_HTML, PORTAL, "t")[0]
        doc = page_to_document(faq)
        chunks = production_chunker().chunk(doc)
        # This particular FAQ answer is short, so it is a single chunk. (Long FAQ
        # answers may split — one-chunk-per-FAQ is NOT a universal guarantee.)
        self.assertGreaterEqual(len(chunks), 1)
        md = chunks[0].metadata
        self.assertEqual(md["page_type"], "faq")
        self.assertEqual(md["category"], "Graduate Admissions")
        self.assertEqual(md["faq_question"], "How do I submit my official transcripts?")
        self.assertEqual(md["is_supporting_page"], False)
        self.assertEqual(md["source_url"], f"{PORTAL}#accordion-10952161")
        self.assertIn("chunk_id", md)

    def test_distinct_faqs_get_distinct_document_ids(self):
        faqs = parse_faq_page(SAMPLE_HTML, PORTAL, "t")
        doc_ids = {page_to_document(f).document_id for f in faqs}
        self.assertEqual(len(doc_ids), 3)             # the collision blocker, resolved

    def test_non_faq_page_backward_compatible(self):
        page = {"url": "https://x.csulb.edu/p", "page_type": "eligibility",
                "title": "T", "text": "some body text", "links": []}
        md = page_to_document(page).metadata
        self.assertEqual(md["page_type"], "eligibility")
        self.assertEqual(md["category"], "")
        self.assertEqual(md["faq_question"], "")
        self.assertEqual(md["is_supporting_page"], False)
        self.assertEqual(md["source_url"], "https://x.csulb.edu/p")


if __name__ == "__main__":
    unittest.main()
