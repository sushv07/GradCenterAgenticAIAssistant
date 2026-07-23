"""
tests/test_masters_full_catalog.py
Phase 8 — full-catalog acquisition orchestration (offline, deterministic).

Covers:
  1. the committed live directory snapshot parses to the full catalog
     (67 programs / 55 unique seeds) with no code changes — the "what already
     scales" claim is pinned by a fixture, not an assertion in a report;
  2. build_full_catalog end-to-end over a synthetic catalog with injected
     fetchers and a fake index (no network, no embedding model, no Chroma);
  3. fail-loud invariants (directory shrink, production-store guard);
  4. report rendering is deterministic and complete.

Run: pytest tests/test_masters_full_catalog.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.discovery import discover_from_html
from rag.masters_catalog import (
    CatalogBuildConfig, MIN_EXPECTED_PROGRAMS, build_full_catalog,
)
from rag.masters_catalog_metrics import CatalogBuildStats
from rag.masters_catalog_report import render_report

# offline build config: no live base-source ingestion, no benchmark pass
_OFFLINE = CatalogBuildConfig(include_base_sources=False, measure_embedding=False)

from unittest import mock

FIXTURES = Path(__file__).parent / "fixtures" / "masters_html"

# The reused crawler sleeps _CRAWL_DELAY between nested fetches (politeness for
# the live site). Fixture-backed tests have no site to be polite to.
_SLEEP_PATCH = mock.patch("rag.discovery.time.sleep", lambda *_: None)


def setUpModule():
    _SLEEP_PATCH.start()


def tearDownModule():
    _SLEEP_PATCH.stop()
B = "https://www.csulb.edu"
INDEX = f"{B}/graduate-studies-csulb/article/programs-advisors-and-deadlines-masters"

_PAGE = ("<html><head><title>{title}</title></head><body><main>"
         "<p>Admission requirements: official transcripts, statement of purpose, "
         "letters of recommendation, and a minimum GPA of 3.0. Apply via Cal "
         "State Apply. {extra}</p></main></body></html>")


def _synthetic_catalog(n_programs: int):
    """A synthetic index + program pages large enough to pass the sanity floor.

    Returns (index_html, site_dict). Deterministic: program i lives at
    /prog-i with one nested apply page.
    """
    cards, site = [], {}
    for i in range(n_programs):
        seed = f"{B}/prog-{i}"
        cards.append(
            f'<td><a href="{seed}">Program {i:02d} (MS)</a>'
            f'<a href="mailto:advisor{i}@csulb.edu">Dr. Advisor {i:02d}</a>'
            f"<table><tr><td>Fall: April 01</td><td>Fall: June 01</td></tr>"
            f"</table></td>")
        site[seed] = _PAGE.format(
            title=f"Program {i:02d}",
            extra=f'<a href="{seed}/apply">application requirements</a> '
                  f"Unique program content number {i:02d}.")
        site[f"{seed}/apply"] = _PAGE.format(
            title=f"Program {i:02d} Application",
            extra=f"Supplemental application for program {i:02d}.")
    index_html = ("<html><body><table><tr>" + "".join(cards)
                  + "</tr></table></body></html>")
    return index_html, site


class _FakeIndex:
    """Satisfies build_from_langchain_documents; counts what it indexed."""

    def __init__(self):
        self.docs = []

    def build_from_langchain_documents(self, documents):
        self.docs = list(documents)
        return self

    @property
    def _collection(self):
        outer = self

        class _C:
            def count(self):
                return len(outer.docs)
        return _C()


class TestLiveSnapshotScales(unittest.TestCase):
    """The committed live snapshot proves the parser needs no scale changes."""

    def test_full_catalog_parses_from_snapshot(self):
        html = (FIXTURES / "index_live_snapshot.html").read_bytes()
        manifest = discover_from_html(html, source_url=INDEX)
        self.assertEqual(len(manifest.programs), 67)
        seeds = {p.official_program_url for p in manifest.programs
                 if p.official_program_url}
        self.assertEqual(len(seeds), 55)          # shared seeds collapse
        self.assertGreaterEqual(len(manifest.programs), MIN_EXPECTED_PROGRAMS)
        # every program has a seed — nothing is silently uncrawlable
        self.assertTrue(all(p.official_program_url for p in manifest.programs))


class TestBuildFullCatalog(unittest.TestCase):
    N = 55

    def _run(self, tmp="/tmp-unused-fake"):
        index_html, site = _synthetic_catalog(self.N)
        idx = _FakeIndex()
        handle, stats = build_full_catalog(
            tmp, index_html=index_html, fetch_fn=site.get,
            config=_OFFLINE, indexer=idx)
        return handle, stats, idx

    def test_end_to_end_stats(self):
        _, stats, idx = self._run()
        self.assertEqual(stats.programs_discovered, self.N)
        self.assertEqual(stats.unique_seed_urls, self.N)
        self.assertEqual(stats.seed_pages, self.N)
        self.assertEqual(stats.nested_pages, self.N)      # one apply page each
        self.assertEqual(stats.documents_accepted, 2 * self.N)
        self.assertEqual(stats.directory_card_documents, self.N)
        self.assertEqual(stats.documents_rejected, 0)
        self.assertEqual(stats.duplicate_document_ids, 0)
        self.assertEqual(stats.programs_without_page_content, [])
        self.assertEqual(len(stats.programs_with_page_content), self.N)
        self.assertGreater(stats.masters_chunks, 0)
        self.assertEqual(stats.total_chunks, stats.masters_chunks)   # no base
        self.assertEqual(stats.indexed_vectors, len(idx.docs))
        self.assertEqual(stats.fetch_failures, 0)
        for stage in ("directory_discovery", "nested_discovery",
                      "extraction_conversion", "chunking",
                      "index_fused_embed_and_index", "total"):
            self.assertIn(stage, stats.timings_s)

    def test_deterministic_across_runs(self):
        _, s1, _ = self._run()
        _, s2, _ = self._run()
        self.assertEqual(s1.chunks_per_program, s2.chunks_per_program)
        self.assertEqual(s1.masters_chunks, s2.masters_chunks)
        self.assertEqual(s1.index_content_hash, s2.index_content_hash)

    def test_chunks_attributed_per_program(self):
        _, stats, _ = self._run()
        self.assertNotIn("(unattributed)", stats.chunks_per_program)
        self.assertEqual(len(stats.chunks_per_program), self.N)
        self.assertTrue(all(n > 0 for n in stats.chunks_per_program.values()))

    def test_fetch_failure_counted_and_program_flagged(self):
        index_html, site = _synthetic_catalog(self.N)
        dead_seed = f"{B}/prog-0"
        site.pop(dead_seed)                       # seed fetch fails entirely
        site.pop(f"{dead_seed}/apply")
        idx = _FakeIndex()
        _, stats = build_full_catalog(
            "/tmp-unused-fake", index_html=index_html, fetch_fn=site.get,
            config=_OFFLINE, indexer=idx)
        self.assertGreater(stats.fetch_failures, 0)
        self.assertIn("Program 00 (MS)", stats.programs_without_page_content)


class TestCommaLabels(unittest.TestCase):
    """Live catalog reality: 6 directory labels contain ', ' — the loader's
    associated_programs join separator. Attribution must reconstruct them."""

    LABELS = {"Curriculum and Instruction, Elementary Education (MA)",
              "Equity, Education and Social Justice (MA)",
              "Linguistics (MA)"}

    def test_split_reconstructs_comma_labels(self):
        from rag.masters_catalog_metrics import split_associated_programs
        joined = ("Curriculum and Instruction, Elementary Education (MA), "
                  "Linguistics (MA), Equity, Education and Social Justice (MA)")
        self.assertEqual(
            split_associated_programs(joined, self.LABELS),
            ["Curriculum and Instruction, Elementary Education (MA)",
             "Linguistics (MA)",
             "Equity, Education and Social Justice (MA)"])

    def test_unknown_remainder_surfaced_not_dropped(self):
        from rag.masters_catalog_metrics import split_associated_programs
        got = split_associated_programs("Linguistics (MA), Mystery, Label",
                                        self.LABELS)
        self.assertEqual(got, ["Linguistics (MA)", "Mystery, Label"])

    def test_comma_label_program_not_reported_missing(self):
        index_html, site = _synthetic_catalog(54)
        # add a 55th program whose label contains the join separator
        seed = f"{B}/prog-comma"
        site[seed] = _PAGE.format(
            title="Curriculum and Instruction, Elementary Education",
            extra="Unique comma-label program content.")
        index_html = index_html.replace(
            "</tr></table>",
            f'<td><a href="{seed}">Curriculum and Instruction, Elementary '
            f'Education (MA)</a></td></tr></table>')
        _, stats = build_full_catalog(
            "/tmp-unused-fake", index_html=index_html, fetch_fn=site.get,
            config=_OFFLINE, indexer=_FakeIndex())
        label = "Curriculum and Instruction, Elementary Education (MA)"
        self.assertIn(label, stats.programs_with_page_content)
        self.assertNotIn(label, stats.programs_without_page_content)
        self.assertIn(label, stats.chunks_per_program)
        self.assertNotIn("Elementary Education (MA)", stats.chunks_per_program)


class TestFailLoud(unittest.TestCase):
    def test_directory_shrink_raises(self):
        index_html, site = _synthetic_catalog(5)      # far below the floor
        with self.assertRaises(RuntimeError):
            build_full_catalog(
                "/tmp-unused-fake", index_html=index_html, fetch_fn=site.get,
                config=_OFFLINE,
                indexer=_FakeIndex())

    def test_production_store_dir_refused(self):
        from config.settings import CHROMA_DIR
        with self.assertRaises(RuntimeError):
            build_full_catalog(
                str(CHROMA_DIR), index_html="<html></html>", fetch_fn=dict().get,
                config=_OFFLINE,
                indexer=_FakeIndex())

    def test_unfetchable_index_raises(self):
        with self.assertRaises(RuntimeError):
            build_full_catalog(
                "/tmp-unused-fake", index_html=None, fetch_fn=dict().get,
                config=_OFFLINE,
                indexer=_FakeIndex())


class TestReport(unittest.TestCase):
    def test_report_contains_all_sections(self):
        index_html, site = _synthetic_catalog(55)
        _, stats = build_full_catalog(
            "/tmp-unused-fake", index_html=index_html, fetch_fn=site.get,
            config=_OFFLINE,
            indexer=_FakeIndex())
        report = render_report(stats)
        for heading in ("## Directory discovery", "## Nested page discovery",
                        "## Extraction / validation", "## Program coverage",
                        "## Store", "## Stage timings"):
            self.assertIn(heading, report)
        self.assertIn("programs discovered: 55", report)
        # deterministic rendering
        self.assertEqual(report, render_report(stats))

    def test_report_renders_empty_stats(self):
        self.assertIn("## Store", render_report(CatalogBuildStats()))


if __name__ == "__main__":
    unittest.main()
