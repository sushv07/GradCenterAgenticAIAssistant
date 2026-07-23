"""
tests/test_masters_corpus_hygiene.py
Phase 9A — corpus hygiene filters (offline, deterministic).

Covers the two evidence-driven exclusion rules from the Phase 8 audit:
  1. unsupported (non-HTML) resource types — the MSCCJ application PDF alone
     contributed 512 garbled chunks (~15 % of the store);
  2. term-year archive pages — `…/fall-2021` (67 chunks of stale COVID-era
     content, top hit for a negative eval case).
Plus: skip reporting propagates to the discovery result, seeds are exempt,
and fetch_page_final rejects non-HTML Content-Types (defense in depth for
extensionless URLs).

No network: synthetic HTML, injected fetchers, mocked requests.

Run: pytest tests/test_masters_corpus_hygiene.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.manifest import DiscoveredProgram
from rag.masters_discovery import (
    discover_masters_program_pages, is_obsolete_term_page, is_supported_resource,
)

B = "https://www.csulb.edu"


class TestSupportedResource(unittest.TestCase):
    def test_binary_document_types_rejected(self):
        for ext in ("pdf", "doc", "docx", "ppt", "pptx"):
            self.assertFalse(is_supported_resource(f"{B}/files/form.{ext}"),
                             msg=ext)

    def test_case_insensitive_and_percent_encoded(self):
        # the actual Phase 8 offender: %20 in the filename
        self.assertFalse(is_supported_resource(
            f"{B}/sites/default/files/2026/documents/"
            "MSCCJ%20Program%20Application%20Form_0.pdf"))
        self.assertFalse(is_supported_resource(f"{B}/x/FORM.PDF"))

    def test_html_pages_and_lookalikes_kept(self):
        self.assertTrue(is_supported_resource(f"{B}/admissions"))
        self.assertTrue(is_supported_resource(f"{B}/page.html"))
        self.assertTrue(is_supported_resource(f"{B}/pdf-guidelines"))  # not an ext
        self.assertTrue(is_supported_resource(f"{B}/documents/"))
        self.assertTrue(is_supported_resource(""))


class TestObsoleteTermPage(unittest.TestCase):
    def test_exact_term_year_slug_rejected(self):
        # the actual Phase 8 offender
        self.assertTrue(is_obsolete_term_page(
            f"{B}/college-of-health-human-services/fall-2021"))
        self.assertTrue(is_obsolete_term_page(f"{B}/dept/spring-2020/"))

    def test_containing_slugs_kept(self):
        # a term-year INSIDE a longer slug is a legitimate page, not an archive
        self.assertFalse(is_obsolete_term_page(f"{B}/cob/fall-2026-deadlines"))
        self.assertFalse(is_obsolete_term_page(f"{B}/apply-by-fall-2026"))
        self.assertFalse(is_obsolete_term_page(f"{B}/fall-preview"))
        self.assertFalse(is_obsolete_term_page(f"{B}/admissions"))
        self.assertFalse(is_obsolete_term_page(""))


class TestDiscoveryAppliesGuards(unittest.TestCase):
    def _crawl(self):
        seed = f"{B}/dept"
        site = {
            seed: f'<html><head><title>D</title></head><body><main>'
                  f'<a href="{B}/dept/apply">how to apply</a>'
                  f'<a href="{B}/dept/Application%20Form.pdf">application form requirements</a>'
                  f'<a href="{B}/dept/fall-2021">fall 2021 application updates</a>'
                  f'</main></body></html>',
            f"{B}/dept/apply":
                "<html><body><main><p>Admission requirements: apply via Cal "
                "State Apply. Application checklist.</p></main></body></html>",
            f"{B}/dept/Application%20Form.pdf":
                "%PDF-1.7 admission requirements prerequisites binary payload",
            f"{B}/dept/fall-2021":
                "<html><body><main><p>Fall 2021 application updates and "
                "admission requirements changes.</p></main></body></html>",
        }
        prog = DiscoveredProgram(
            raw_listing_name="Dept (MS)", normalized_program_name="Dept",
            degree_label="MS", official_program_url=seed)
        with mock.patch("rag.discovery.time.sleep", lambda *_: None):
            return discover_masters_program_pages([prog], depth=1,
                                                  fetch_fn=site.get)

    def test_pdf_and_archive_dropped_legit_kept(self):
        result = self._crawl()
        urls = {p.url for p in result.pages}
        self.assertIn(f"{B}/dept", urls)                    # seed kept
        self.assertIn(f"{B}/dept/apply", urls)              # legit child kept
        self.assertFalse(any(u.lower().endswith(".pdf") for u in urls))
        self.assertFalse(any(u.endswith("fall-2021") for u in urls))

    def test_skips_reported_with_reasons(self):
        result = self._crawl()
        self.assertEqual(
            result.skipped_pages.get(f"{B}/dept/Application%20Form.pdf"),
            "unsupported_resource_type")
        self.assertEqual(result.skipped_pages.get(f"{B}/dept/fall-2021"),
                         "obsolete_term_archive")
        agg = result.aggregate()
        self.assertEqual(agg["skipped_pages"],
                         {"unsupported_resource_type": 1,
                          "obsolete_term_archive": 1})

    def test_seed_pages_exempt_from_guards(self):
        # A seed whose URL matches a guard is still kept: seeds come from the
        # official directory and are never silently dropped.
        seed = f"{B}/dept/fall-2021"
        site = {seed: "<html><body><main><p>Admission requirements page "
                      "listed as official directory seed.</p></main></body></html>"}
        prog = DiscoveredProgram(
            raw_listing_name="Odd (MS)", normalized_program_name="Odd",
            degree_label="MS", official_program_url=seed)
        result = discover_masters_program_pages([prog], depth=0,
                                                fetch_fn=site.get)
        self.assertEqual([p.url for p in result.pages], [seed])
        self.assertEqual(result.skipped_pages, {})


class TestFetchFinalContentType(unittest.TestCase):
    def _resp(self, ctype, text="<html>x</html>", url=f"{B}/x"):
        r = mock.Mock()
        r.status_code = 200
        r.text = text
        r.url = url
        r.headers = {"Content-Type": ctype} if ctype is not None else {}
        return r

    def test_non_html_content_type_rejected(self):
        from rag.masters_extraction import fetch_page_final
        for ctype in ("application/pdf", "application/msword",
                      "application/vnd.openxmlformats-officedocument"
                      ".wordprocessingml.document"):
            with mock.patch("requests.get", return_value=self._resp(ctype)):
                html, final = fetch_page_final(f"{B}/x")
            self.assertIsNone(html, msg=ctype)
            self.assertEqual(final, f"{B}/x")   # final url still truthful

    def test_html_content_types_accepted(self):
        from rag.masters_extraction import fetch_page_final
        for ctype in ("text/html", "text/html; charset=utf-8",
                      "application/xhtml+xml", None):
            with mock.patch("requests.get", return_value=self._resp(ctype)):
                html, _ = fetch_page_final(f"{B}/x")
            self.assertEqual(html, "<html>x</html>", msg=str(ctype))


if __name__ == "__main__":
    unittest.main()
