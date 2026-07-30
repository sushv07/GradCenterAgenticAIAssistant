"""
tests/test_faq_dispatch.py
Phase 4.1 — production-dispatch integration for the FAQ specialist.

Exercises rag.ingestion.ingest_pages() with network fetching MOCKED (offline),
verifying the specialist wiring:
  * FAQ specialist success → multiple atomic page dicts (not one coarse page)
  * generic parse_page() is NOT called for the FAQ URL when the specialist wins
  * specialist returning [] → falls back to the generic parse_page()
  * non-FAQ page ingestion is unchanged

Run: pytest tests/test_faq_dispatch.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import rag.ingestion as ing

FAQ_URL = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"
ELIG_URL = "https://www.csulb.edu/graduate-center/eligibility"

FAQ_HTML = """
<html><body>
  <h2>Graduate Admissions</h2>
  <div class="card"><div class="card-header"><h2 class="accordion-heading">How do I submit transcripts?</h2></div>
    <div class="collapse" id="accordion-1001">Submit to Enrollment Services.</div></div>
  <div class="card"><div class="card-header"><h2 class="accordion-heading">Are fee waivers available?</h2></div>
    <div class="collapse" id="accordion-1002">No. The fee is $70.</div></div>
</body></html>
"""

# A generic (non-accordion) page with enough body text to clear parse_page's
# 150-char minimum, used both for the eligibility source and the FAQ-fallback case.
GENERIC_HTML = (
    "<html><body><main><h1>Eligibility</h1><p>"
    + ("Graduate admission eligibility requires a bachelor's degree and a minimum GPA. " * 6)
    + "</p></main></body></html>"
)


def _ingest(sources, html_by_url, parse_spy=False):
    fetch = mock.Mock(side_effect=lambda url: html_by_url.get(url))
    ctx_parse = (mock.patch.object(ing, "parse_page", side_effect=ing.parse_page)
                 if parse_spy else None)
    with mock.patch.object(ing, "fetch_page", fetch):
        if ctx_parse is not None:
            with ctx_parse as spy:
                pages = ing.ingest_pages(sources=sources, use_discovery=False)
                return pages, spy
        pages = ing.ingest_pages(sources=sources, use_discovery=False)
        return pages, None


class TestFaqDispatch(unittest.TestCase):
    def test_specialist_success_produces_atomic_pages(self):
        pages, _ = _ingest(
            [{"url": FAQ_URL, "page_type": "faq", "title": "FAQ"}],
            {FAQ_URL: FAQ_HTML},
        )
        faq_pages = [p for p in pages if p["page_type"] == "faq"]
        self.assertEqual(len(faq_pages), 2)                       # atomic, not 1 coarse page
        self.assertTrue(all(p.get("faq_question") for p in faq_pages))  # specialist signature
        self.assertEqual(len({p["url"] for p in faq_pages}), 2)   # unique identities

    def test_generic_parser_not_used_when_specialist_succeeds(self):
        pages, spy = _ingest(
            [{"url": FAQ_URL, "page_type": "faq", "title": "FAQ"}],
            {FAQ_URL: FAQ_HTML},
            parse_spy=True,
        )
        called_urls = [c.args[1] for c in spy.call_args_list]      # parse_page(html, url, ...)
        self.assertNotIn(FAQ_URL, called_urls)                    # specialist won → parse_page skipped

    def test_specialist_empty_falls_back_to_generic(self):
        pages, spy = _ingest(
            [{"url": FAQ_URL, "page_type": "faq", "title": "FAQ"}],
            {FAQ_URL: GENERIC_HTML},                               # no accordion → specialist []
            parse_spy=True,
        )
        faq_pages = [p for p in pages if p["page_type"] == "faq"]
        self.assertEqual(len(faq_pages), 1)                       # one coarse page (legacy behavior)
        self.assertFalse(faq_pages[0].get("faq_question"))        # generic, not specialist
        self.assertIn(FAQ_URL, [c.args[1] for c in spy.call_args_list])  # parse_page WAS used

    def test_non_faq_ingestion_unchanged(self):
        pages, spy = _ingest(
            [{"url": ELIG_URL, "page_type": "eligibility", "title": "Eligibility"}],
            {ELIG_URL: GENERIC_HTML},
            parse_spy=True,
        )
        elig = [p for p in pages if p["page_type"] == "eligibility"]
        self.assertEqual(len(elig), 1)
        self.assertFalse(elig[0].get("faq_question"))             # untouched by FAQ logic
        self.assertIn(ELIG_URL, [c.args[1] for c in spy.call_args_list])  # normal parse_page path

    def test_mixed_sources_dispatch_independently(self):
        pages, _ = _ingest(
            [{"url": FAQ_URL, "page_type": "faq", "title": "FAQ"},
             {"url": ELIG_URL, "page_type": "eligibility", "title": "Eligibility"}],
            {FAQ_URL: FAQ_HTML, ELIG_URL: GENERIC_HTML},
        )
        self.assertEqual(len([p for p in pages if p["page_type"] == "faq"]), 2)
        self.assertEqual(len([p for p in pages if p["page_type"] == "eligibility"]), 1)


if __name__ == "__main__":
    unittest.main()
