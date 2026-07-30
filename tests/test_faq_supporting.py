"""
tests/test_faq_supporting.py
Phase 4.2 — depth-1 supporting-page ingestion.

Two layers, both offline/network-free:
  * PURE discovery (rag.faq_ingest.discover_supporting_links): allowlist,
    non-HTML skip, dedupe, known-source skip, cycle-safety, parent linkage,
    canonicalization, deterministic order.
  * PRODUCTION dispatch (rag.ingestion.ingest_pages) with fetch_page mocked and
    the Phase-4.0 flags patched: supporting pages flow through the SAME
    parse_page pipeline, get faq_supporting metadata, unique identities, and are
    off by default.

Run: pytest tests/test_faq_supporting.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import rag.ingestion as ing
from rag.faq_ingest import discover_supporting_links, _canonical_url
from ingestion.pipeline.loaders.pages import page_to_document

PORTAL = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"
TRANSCRIPTS = "https://www.csulb.edu/enrollment-services/transcripts"
RESIDENCY = "https://www.csulb.edu/registration-records/residency"


def _faq(url, question, links):
    return {"url": url, "page_type": "faq", "faq_question": question, "links": links}


class TestSupportingDiscovery(unittest.TestCase):
    def test_allowlist_rejects_external_domains(self):
        faqs = [_faq(f"{PORTAL}#accordion-1", "Q1", [
            {"text": "transcripts", "url": TRANSCRIPTS},
            {"text": "external", "url": "https://example.com/help"},
            {"text": "calstate", "url": "https://www.calstate.edu/apply"},
        ])]
        out = discover_supporting_links(faqs, allowlist_domain="csulb.edu")
        urls = [s["url"] for s in out]
        self.assertIn(TRANSCRIPTS, urls)
        self.assertNotIn("https://example.com/help", urls)
        self.assertNotIn("https://www.calstate.edu/apply", urls)

    def test_subdomain_is_allowed(self):
        faqs = [_faq(f"{PORTAL}#a", "Q", [{"text": "cie", "url": "https://www.csulb.edu/cie"}])]
        out = discover_supporting_links(faqs, allowlist_domain="csulb.edu")
        self.assertEqual(len(out), 1)

    def test_non_html_resources_skipped(self):
        faqs = [_faq(f"{PORTAL}#a", "Q", [
            {"text": "form", "url": "https://www.csulb.edu/files/app.pdf"},
            {"text": "img", "url": "https://www.csulb.edu/logo.png"},
            {"text": "page", "url": TRANSCRIPTS},
        ])]
        out = discover_supporting_links(faqs, allowlist_domain="csulb.edu")
        self.assertEqual([s["url"] for s in out], [TRANSCRIPTS])

    def test_dedupe_keeps_first_parent_deterministically(self):
        faqs = [
            _faq(f"{PORTAL}#accordion-1", "First Q", [{"text": "t", "url": TRANSCRIPTS}]),
            _faq(f"{PORTAL}#accordion-2", "Second Q", [{"text": "t", "url": TRANSCRIPTS}]),
        ]
        out = discover_supporting_links(faqs, allowlist_domain="csulb.edu")
        self.assertEqual(len(out), 1)                                  # ingested once
        self.assertEqual(out[0]["parent_faq_url"], f"{PORTAL}#accordion-1")  # first FAQ wins
        self.assertEqual(out[0]["parent_faq_question"], "First Q")

    def test_known_source_urls_are_skipped(self):
        # A supporting link that is already a primary ingestion source is skipped
        # (prevents document_id collision with that primary doc).
        faqs = [_faq(f"{PORTAL}#a", "Q", [{"text": "elig", "url": RESIDENCY}])]
        out = discover_supporting_links(
            faqs, allowlist_domain="csulb.edu", known_source_urls={RESIDENCY})
        self.assertEqual(out, [])

    def test_canonicalization_dedupes_slash_and_fragment(self):
        faqs = [_faq(f"{PORTAL}#a", "Q", [
            {"text": "a", "url": TRANSCRIPTS + "/"},
            {"text": "b", "url": TRANSCRIPTS + "#section"},
        ])]
        out = discover_supporting_links(faqs, allowlist_domain="csulb.edu")
        self.assertEqual(len(out), 1)                                  # both canonicalize equal
        self.assertEqual(out[0]["url"], TRANSCRIPTS)

    def test_portal_self_link_skipped_as_known_source(self):
        # Cycle-safety: a link back to the FAQ portal is a known source → skipped.
        faqs = [_faq(f"{PORTAL}#a", "Q", [{"text": "faqs", "url": PORTAL}])]
        out = discover_supporting_links(
            faqs, allowlist_domain="csulb.edu", known_source_urls={PORTAL})
        self.assertEqual(out, [])

    def test_deterministic_order(self):
        faqs = [_faq(f"{PORTAL}#a", "Q", [
            {"text": "t", "url": TRANSCRIPTS}, {"text": "r", "url": RESIDENCY}])]
        a = [s["url"] for s in discover_supporting_links(faqs, allowlist_domain="csulb.edu")]
        b = [s["url"] for s in discover_supporting_links(faqs, allowlist_domain="csulb.edu")]
        self.assertEqual(a, b)
        self.assertEqual(a, [TRANSCRIPTS, RESIDENCY])                  # link order preserved


# ---------------------------------------------------------------------------
# Production dispatch through ingest_pages (fetch mocked, flags patched)
# ---------------------------------------------------------------------------

FAQ_HTML = f"""
<html><body>
  <h2>Graduate Admissions</h2>
  <div class="card"><div class="card-header"><h2 class="accordion-heading">How do I submit transcripts?</h2></div>
    <div class="collapse" id="accordion-2001">Submit official transcripts.
      See <a href="{TRANSCRIPTS}">transcript requirements</a> and
      <a href="https://example.com/x">an external site</a>.</div></div>
</body></html>
"""
SUPPORTING_HTML = (
    "<html><body><main><h1>Transcript Requirements</h1><p>"
    + ("Official transcripts must be sent by your prior institution to Enrollment Services. " * 6)
    + "</p></main></body></html>"
)


def _ingest_faq(html_by_url, supporting=True, depth=1):
    fetch = mock.Mock(side_effect=lambda url: html_by_url.get(url))
    with mock.patch.object(ing, "fetch_page", fetch), \
         mock.patch("config.settings.FAQ_CRAWL_SUPPORTING", supporting), \
         mock.patch("config.settings.FAQ_CRAWL_DEPTH", depth), \
         mock.patch("config.settings.FAQ_DOMAIN_ALLOWLIST", "csulb.edu"):
        return ing.ingest_pages(
            sources=[{"url": PORTAL, "page_type": "faq", "title": "FAQ"}],
            use_discovery=False,
        )


class TestSupportingDispatch(unittest.TestCase):
    def test_supporting_pages_ingested_when_enabled(self):
        pages = _ingest_faq({PORTAL: FAQ_HTML, TRANSCRIPTS: SUPPORTING_HTML}, supporting=True)
        faqs = [p for p in pages if p["page_type"] == "faq"]
        sup = [p for p in pages if p["page_type"] == "faq_supporting"]
        self.assertEqual(len(faqs), 1)
        self.assertEqual(len(sup), 1)                                  # external link excluded
        s = sup[0]
        self.assertTrue(s["is_supporting_page"])
        self.assertEqual(s["parent_faq_url"], f"{PORTAL}#accordion-2001")
        self.assertEqual(s["parent_faq_question"], "How do I submit transcripts?")
        self.assertEqual(s["source_url"], TRANSCRIPTS)

    def test_disabled_by_default_produces_no_supporting_pages(self):
        pages = _ingest_faq({PORTAL: FAQ_HTML, TRANSCRIPTS: SUPPORTING_HTML}, supporting=False)
        self.assertEqual([p for p in pages if p["page_type"] == "faq_supporting"], [])
        self.assertEqual(len([p for p in pages if p["page_type"] == "faq"]), 1)  # FAQ still atomic

    def test_supporting_metadata_and_identity_reach_chunk(self):
        pages = _ingest_faq({PORTAL: FAQ_HTML, TRANSCRIPTS: SUPPORTING_HTML}, supporting=True)
        sup = next(p for p in pages if p["page_type"] == "faq_supporting")
        doc = page_to_document(sup)
        md = doc.metadata
        self.assertEqual(md["page_type"], "faq_supporting")
        self.assertEqual(md["is_supporting_page"], True)
        self.assertEqual(md["parent_faq_question"], "How do I submit transcripts?")
        self.assertEqual(md["source_url"], TRANSCRIPTS)
        # identity reuses the real supporting URL — unique + distinct from the FAQ
        faq_doc = page_to_document(next(p for p in pages if p["page_type"] == "faq"))
        self.assertNotEqual(doc.document_id, faq_doc.document_id)

    def test_fetch_failure_is_skipped_gracefully(self):
        pages = _ingest_faq({PORTAL: FAQ_HTML, TRANSCRIPTS: None}, supporting=True)  # fetch → None
        self.assertEqual([p for p in pages if p["page_type"] == "faq_supporting"], [])
        self.assertEqual(len([p for p in pages if p["page_type"] == "faq"]), 1)  # FAQ unaffected


if __name__ == "__main__":
    unittest.main()
