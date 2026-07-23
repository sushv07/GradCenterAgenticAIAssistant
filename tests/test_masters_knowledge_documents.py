"""
tests/test_masters_knowledge_documents.py
Phase 3 — master's content extraction → KnowledgeDocument conversion (offline).

Deterministic, fixture-based: a fake fetch_fn serves synthetic HTML, so
extraction (chrome stripping), metadata generation, deterministic IDs, and
validation are verified without network. No chunking / embedding / indexing.

Run: pytest tests/test_masters_knowledge_documents.py -v
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.manifest import DiscoveredProgram
from rag.masters_discovery import DiscoveredPage
from rag.masters_extraction import build_masters_documents

B = "https://www.csulb.edu"

_GOOD = f"""<html><head><title>Admission Requirements | CSULB</title></head>
<body>
  <nav>Home About Give Apply</nav>
  <header>CSULB Graduate Studies</header>
  <main>
    <h1>Admission Requirements</h1>
    <p>Submit letters of recommendation, a statement of purpose, official
    transcripts, and GRE scores. The admissions committee reviews complete
    applications on a rolling basis for both fall and spring entry, and notifies
    applicants of decisions by email within several weeks of the deadline.</p>
    <p>This is a carousel. Use next and previous buttons to navigate.</p>
  </main>
  <footer>1250 Bellflower Boulevard, Long Beach, California 90840</footer>
</body></html>"""

_EMPTY = "<html><head><title>Empty</title></head><body><main></main></body></html>"
_MALFORMED = "<html><body><main><p>Partial content about admissions<p>and more text"

_SITE = {f"{B}/ling/admissions": _GOOD, f"{B}/empty": _EMPTY, f"{B}/malformed": _MALFORMED}


def _fetch(url):
    return _SITE.get(url)


def _page(url, category="program_requirements", programs=("Linguistics (MA)",), depth=1):
    return DiscoveredPage(url=url, title="", content_category=category, workflow_priority=3,
                          parent_program_url=f"{B}/ling", discovered_from=f"{B}/ling",
                          depth=depth, programs=list(programs))


PROGRAMS = [DiscoveredProgram(raw_listing_name="Linguistics (MA)",
                              normalized_program_name="Linguistics", degree_label="MA",
                              official_program_url=f"{B}/ling"),
            DiscoveredProgram(raw_listing_name="Asian Studies (MA)",
                              normalized_program_name="Asian Studies", degree_label="MA",
                              official_program_url=f"{B}/asian")]


class TestExtractionAndConversion(unittest.TestCase):
    def test_extraction_strips_chrome_and_boilerplate(self):
        docs, _ = build_masters_documents([_page(f"{B}/ling/admissions")], PROGRAMS, fetch_fn=_fetch)
        self.assertEqual(len(docs), 1)
        text = docs[0].text
        self.assertIn("Admission Requirements", text)
        self.assertIn("letters of recommendation", text)
        self.assertNotIn("Give Apply", text)                 # nav removed
        self.assertNotIn("Bellflower", text)                 # footer address removed
        self.assertNotIn("carousel", text)                   # boilerplate line dropped

    def test_metadata_generation(self):
        docs, _ = build_masters_documents([_page(f"{B}/ling/admissions")], PROGRAMS, fetch_fn=_fetch)
        md = docs[0].metadata
        self.assertEqual(md["program_name"], "Linguistics")   # single program → tagged
        self.assertEqual(md["degree"], "MA")
        self.assertEqual(md["degree_level"], "Masters")
        self.assertEqual(md["content_type"], "program_requirements")
        self.assertEqual(md["page_type"], "masters_program")
        self.assertEqual(md["page_title"], "Admission Requirements")
        self.assertEqual(md["crawl_depth"], 1)
        self.assertEqual(md["source_url"], f"{B}/ling/admissions")

    def test_deterministic_document_id(self):
        url = f"{B}/ling/admissions"
        expect = hashlib.md5(url.encode()).hexdigest()[:8]
        d1 = build_masters_documents([_page(url)], PROGRAMS, fetch_fn=_fetch)[0][0]
        d2 = build_masters_documents([_page(url)], PROGRAMS, fetch_fn=_fetch)[0][0]
        self.assertEqual(d1.document_id, expect)
        self.assertEqual(d1.metadata["canonical_document_id"], expect)
        self.assertEqual(d1.document_id, d2.document_id)

    def test_shared_page_is_generic_with_associated_list(self):
        page = _page(f"{B}/ling/admissions", programs=("Linguistics (MA)", "Asian Studies (MA)"))
        docs, _ = build_masters_documents([page], PROGRAMS, fetch_fn=_fetch)
        md = docs[0].metadata
        self.assertNotIn("program_name", md)                  # shared → generic (empty dropped)
        self.assertEqual(md["associated_programs"], "Linguistics (MA), Asian Studies (MA)")

    def test_empty_page_rejected(self):
        docs, summary = build_masters_documents([_page(f"{B}/empty")], PROGRAMS, fetch_fn=_fetch)
        self.assertEqual(docs, [])
        self.assertEqual(summary.documents_rejected, 1)
        self.assertEqual(summary.empty_pages, 1)
        self.assertIn("empty_document", summary.rejections[0][1])

    def test_malformed_html_does_not_crash(self):
        docs, _ = build_masters_documents([_page(f"{B}/malformed")], PROGRAMS, fetch_fn=_fetch)
        self.assertEqual(len(docs), 1)
        self.assertIn("admissions", docs[0].text.lower())

    def test_fetch_failure_rejected(self):
        docs, summary = build_masters_documents([_page(f"{B}/missing")], PROGRAMS, fetch_fn=_fetch)
        self.assertEqual(docs, [])
        self.assertEqual(summary.rejections[0][1], "fetch_failed")

    def test_duplicate_pages_deduplicated(self):
        # Phase 7: pages resolving to the same canonical final URL are converted
        # once; the duplicate is rejected as redirect_duplicate (previously both
        # were converted and flagged via duplicate_document_ids).
        p = _page(f"{B}/ling/admissions")
        docs, summary = build_masters_documents([p, p], PROGRAMS, fetch_fn=_fetch)
        self.assertEqual(len(docs), 1)
        self.assertEqual(summary.documents_rejected, 1)
        self.assertTrue(summary.rejections[0][1].startswith("redirect_duplicate"))

    def test_summary_shape(self):
        pages = [_page(f"{B}/ling/admissions"), _page(f"{B}/empty")]
        _, summary = build_masters_documents(pages, PROGRAMS, fetch_fn=_fetch)
        self.assertEqual(summary.total_pages, 2)
        self.assertEqual(summary.documents_accepted, 1)
        self.assertGreater(summary.avg_content_length, 0)
        self.assertIn("department", summary.missing_metadata)


if __name__ == "__main__":
    unittest.main()
