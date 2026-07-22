"""
tests/test_masters_nested_discovery.py
Phase 2 — master's nested page discovery orchestration (deterministic, offline).

Drives rag.masters_discovery with a FAKE fetch_fn that serves small synthetic
HTML, so classification, cross-program deduplication, and exclusion behaviour are
verified without any network. The live pilot crawl is captured separately in
rag/MASTERS_NESTED_DISCOVERY_PILOT.md.

Run: pytest tests/test_masters_nested_discovery.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.manifest import DiscoveredProgram
from rag.masters_discovery import discover_masters_program_pages

B = "https://www.csulb.edu"


def _page(links: list[tuple[str, str]] = (), body: str = "") -> str:
    hrefs = "".join(f'<a href="{href}">{text}</a>' for text, href in links)
    return f"<html><head><title>T</title></head><body>{body}{hrefs}</body></html>"


# Synthetic site. Seed pages link to nested pages; classification is driven by
# body text signals (see rag/discovery._SIGNALS).
_SITE = {
    f"{B}/alpha": _page(
        links=[
            ("admission requirements", f"{B}/alpha/admissions"),
            ("application process", f"{B}/alpha/apply"),
            ("how to apply", f"{B}/shared/apply"),
            ("graduate admissions overview", f"{B}/alpha/about"),
            ("Latest news", f"{B}/alpha/news"),                # no keyword → not followed
            ("Follow us on Twitter", "https://twitter.com/x"),  # off-domain → filtered
            ("Email us", "mailto:x@csulb.edu"),                 # mailto → skipped
        ],
        body="Alpha graduate program.",
    ),
    f"{B}/alpha/admissions": _page(body="Admission requirements: letters of recommendation, statement of purpose."),
    f"{B}/alpha/apply": _page(body="Apply through Cal State Apply. Steps to apply and application checklist."),
    f"{B}/shared/apply": _page(body="Cal State Apply application checklist for graduate applicants."),
    f"{B}/alpha/about": _page(body="A welcoming program with a long history."),  # overview_only → discarded
    f"{B}/alpha/news": _page(body="Latest news and events."),
    f"{B}/beta": _page(
        links=[
            ("how to apply", f"{B}/shared/apply"),              # SAME nested url as alpha
            ("eligibility criteria", f"{B}/beta/eligibility"),
        ],
        body="Beta program.",
    ),
    # Note: avoid "minimum GPA" here — the reused classifier checks
    # program_requirements BEFORE program_eligibility, and "minimum GPA" is a
    # requirements signal, so it would win. This tests a clean eligibility page.
    f"{B}/beta/eligibility": _page(body="Eligibility criteria: who can apply. Eligible applicants must hold a bachelor's degree."),
}


def _fetch(url: str):
    return _SITE.get(url)


def _prog(name, degree, url):
    return DiscoveredProgram(raw_listing_name=f"{name} ({degree})",
                             normalized_program_name=name, degree_label=degree,
                             official_program_url=url)


class TestNestedDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Alpha + Gamma SHARE a seed (cross-program shared-seed dedup);
        # Beta has its own seed but a shared nested page (global nested dedup).
        programs = [
            _prog("Alpha", "MS", f"{B}/alpha"),
            _prog("Beta", "MA", f"{B}/beta"),
            _prog("Gamma", "MS", f"{B}/alpha"),   # same seed as Alpha
        ]
        cls.result = discover_masters_program_pages(programs, depth=1, fetch_fn=_fetch)
        cls.by_url = {p.url: p for p in cls.result.pages}

    def test_shared_seed_crawled_once_and_associated(self):
        gamma = next(s for s in self.result.programs if s.program_name == "Gamma")
        self.assertTrue(gamma.reused_shared_seed)              # not re-crawled
        seed = self.by_url[f"{B}/alpha"]
        self.assertCountEqual(seed.programs, ["Alpha (MS)", "Gamma (MS)"])

    def test_shared_nested_page_deduped_across_programs(self):
        shared = self.by_url[f"{B}/shared/apply"]
        # reached by Alpha, Gamma (via shared seed), and Beta → one page, all three
        self.assertCountEqual(shared.programs, ["Alpha (MS)", "Gamma (MS)", "Beta (MA)"])
        self.assertEqual(sum(1 for p in self.result.pages if p.url == f"{B}/shared/apply"), 1)

    def test_classifications(self):
        self.assertEqual(self.by_url[f"{B}/alpha/admissions"].content_category, "program_requirements")
        self.assertEqual(self.by_url[f"{B}/beta/eligibility"].content_category, "program_eligibility")
        self.assertEqual(self.by_url[f"{B}/alpha/apply"].content_category, "generic_application")

    def test_exclusions(self):
        urls = set(self.by_url)
        self.assertNotIn("https://twitter.com/x", urls)        # off-domain
        self.assertNotIn(f"{B}/alpha/news", urls)              # no app keyword → not followed
        self.assertFalse(any("mailto:" in u for u in urls))    # mailto skipped
        self.assertNotIn(f"{B}/alpha/about", urls)             # overview_only nested → discarded

    def test_seed_always_kept_and_depth(self):
        self.assertIn(f"{B}/alpha", self.by_url)
        self.assertEqual(self.by_url[f"{B}/alpha"].depth, 0)
        self.assertEqual(self.by_url[f"{B}/alpha/admissions"].depth, 1)

    def test_missing_seed_skipped_gracefully(self):
        res = discover_masters_program_pages(
            [_prog("NoSeed", "MS", None)], depth=1, fetch_fn=_fetch)
        self.assertEqual(res.pages, [])
        self.assertEqual(res.skipped_no_seed, ["NoSeed (MS)"])

    def test_aggregate_shape(self):
        agg = self.result.aggregate()
        self.assertEqual(agg["pilot_programs"], 3)
        self.assertGreaterEqual(agg["shared_pages"], 1)
        self.assertEqual(agg["skipped_no_seed"], 0)
        self.assertIn("program_requirements", agg["by_category"])


if __name__ == "__main__":
    unittest.main()
