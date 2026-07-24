"""
tests/test_masters_seed_overrides.py
Phase 9B — verified seed overrides + dead-seed detection (offline, deterministic).

Covers:
  1. the committed config/masters/seed_overrides.json is well-formed: every
     stale URL is on a legacy host, every replacement is a live-site csulb.edu
     URL, no identity mappings, no duplicate stale keys;
  2. apply_seed_overrides remaps matching seeds (scheme/slash-insensitive),
     passes unaffected programs through bit-identical, and reports what it did;
  3. fail-safe: missing/invalid config means zero behavior change;
  4. the production acquire path (acquire_masters_documents) crawls the
     REPLACEMENT page and the directory card cites it;
  5. dead_seed_candidates flags only the cross-host magnet signature.

Run: pytest tests/test_masters_seed_overrides.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.masters.manifest import DiscoveredProgram
from rag.masters_catalog_metrics import dead_seed_candidates
from rag.masters_discovery import (
    SEED_OVERRIDES_PATH, apply_seed_overrides, load_seed_overrides,
)

B = "https://www.csulb.edu"
CLA = "https://cla.csulb.edu"


def _prog(name, seed, degree="MA"):
    return DiscoveredProgram(
        raw_listing_name=f"{name} ({degree})", normalized_program_name=name,
        degree_label=degree, official_program_url=seed)


class TestCommittedConfig(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(SEED_OVERRIDES_PATH.read_text("utf-8"))
        self.entries = self.data["overrides"]

    def test_shape_and_no_duplicates(self):
        self.assertEqual(len(self.entries), 14)
        stales = [e["stale"] for e in self.entries]
        self.assertEqual(len(stales), len(set(stales)))
        for e in self.entries:
            self.assertIn("stale", e)
            self.assertIn("replacement", e)
            self.assertIn("reason", e)
            self.assertNotEqual(e["stale"], e["replacement"])

    def test_stales_are_legacy_replacements_are_live_site(self):
        for e in self.entries:
            stale_host = urlparse(e["stale"]).netloc.lower()
            repl_host = urlparse(e["replacement"]).netloc.lower()
            self.assertEqual(stale_host, "cla.csulb.edu", msg=e["stale"])
            self.assertEqual(repl_host, "www.csulb.edu", msg=e["replacement"])

    def test_loader_indexes_every_entry(self):
        overrides = load_seed_overrides()
        self.assertEqual(len(overrides), len(self.entries))


class TestApplySeedOverrides(unittest.TestCase):
    OVR = {"stale": f"{CLA}/departments/x/ma-program/",
           "replacement": f"{B}/college-of-liberal-arts/x/master-of-arts"}

    def _overrides(self):
        import rag.masters_discovery as md
        return {md._seed_key(self.OVR["stale"]): self.OVR["replacement"]}

    def test_matching_seed_remapped_and_reported(self):
        progs = [_prog("X", self.OVR["stale"])]
        out, applied = apply_seed_overrides(progs, self._overrides())
        self.assertEqual(out[0].official_program_url, self.OVR["replacement"])
        self.assertEqual(applied, {"X (MA)": self.OVR["replacement"]})
        # original object untouched (replace(), not mutation)
        self.assertEqual(progs[0].official_program_url, self.OVR["stale"])

    def test_scheme_and_trailing_slash_insensitive(self):
        for variant in (self.OVR["stale"].replace("https://", "http://"),
                        self.OVR["stale"].rstrip("/")):
            out, applied = apply_seed_overrides(
                [_prog("X", variant)], self._overrides())
            self.assertEqual(out[0].official_program_url,
                             self.OVR["replacement"], msg=variant)

    def test_unaffected_program_is_same_object(self):
        keep = _prog("Philosophy", f"{CLA}/departments/philosophy/graduate_admissions/")
        out, applied = apply_seed_overrides([keep], self._overrides())
        self.assertIs(out[0], keep)                  # bit-identical passthrough
        self.assertEqual(applied, {})

    def test_missing_or_invalid_config_is_noop(self):
        progs = [_prog("X", self.OVR["stale"])]
        out, applied = apply_seed_overrides(
            progs, load_seed_overrides(Path("/nonexistent/overrides.json")))
        self.assertIs(out[0], progs[0])
        self.assertEqual(applied, {})

    def test_real_config_covers_18_programs_from_snapshot(self):
        from ingestion.masters.discovery import discover_from_html
        html = (Path(__file__).parent / "fixtures" / "masters_html"
                / "index_live_snapshot.html").read_bytes()
        manifest = discover_from_html(html, source_url="fixture")
        out, applied = apply_seed_overrides(manifest.programs)
        self.assertEqual(len(applied), 18)
        # the four resolving legacy-host programs are untouched
        for label in ("Asian Studies (MA)", "Philosophy (MA)", "Music (MM)",
                      "Teaching Chinese as a Foreign Language (MA)"):
            self.assertNotIn(label, applied)
        # every remapped seed now lives on the live site
        for p in out:
            if _label(p) in applied:
                self.assertTrue(p.official_program_url.startswith(
                    f"{B}/college-of-liberal-arts/"))


def _label(p):
    return f"{p.normalized_program_name} ({p.degree_label})" \
        if p.degree_label else p.normalized_program_name


class TestAcquirePathUsesOverrides(unittest.TestCase):
    def test_replacement_crawled_and_card_updated(self):
        from rag.masters_ingest import acquire_masters_documents

        stale = f"{CLA}/departments/x/ma-program/"
        repl = f"{B}/college-of-liberal-arts/x/master-of-arts"
        index_html = (f'<html><body><table><tr><td><a href="{stale}">X (MA)</a>'
                      f'<a href="mailto:x@csulb.edu">Dr. X</a>'
                      f"<table><tr><td>Fall: April 01</td></tr></table>"
                      f"</td></tr></table></body></html>")
        site = {repl: "<html><head><title>X MA</title></head><body><main>"
                      "<p>Admission requirements: transcripts and statement "
                      "of purpose. Apply via Cal State Apply.</p></main></body></html>"}
        import rag.masters_discovery as md
        from unittest import mock
        overrides = {md._seed_key(stale): repl}
        with mock.patch("rag.masters_discovery.load_seed_overrides",
                        return_value=overrides), \
             mock.patch("rag.discovery.time.sleep", lambda *_: None):
            docs = acquire_masters_documents(index_html=index_html,
                                             fetch_fn=site.get)
        page_docs = [d for d in docs
                     if d.metadata.get("content_type") != "directory_card"]
        self.assertEqual(len(page_docs), 1)
        self.assertEqual(page_docs[0].metadata["source_url"], repl)
        cards = [d for d in docs
                 if d.metadata.get("content_type") == "directory_card"]
        self.assertEqual(len(cards), 1)
        self.assertIn(f"Official program page: {repl}", cards[0].text)
        self.assertNotIn(stale, cards[0].text)


class TestDeadSeedDetection(unittest.TestCase):
    HOME = f"{B}/college-of-liberal-arts"

    def test_two_cross_host_stales_flagged(self):
        rmap = {f"{CLA}/departments/a/": self.HOME,
                f"{CLA}/departments/b/": self.HOME}
        got = dead_seed_candidates(rmap)
        self.assertEqual(list(got), [self.HOME])
        self.assertEqual(got[self.HOME],
                         sorted([f"{CLA}/departments/a/", f"{CLA}/departments/b/"]))

    def test_single_redirect_not_flagged(self):
        self.assertEqual(dead_seed_candidates(
            {f"{CLA}/departments/a/": self.HOME}), {})

    def test_same_host_renames_not_flagged(self):
        rmap = {f"{B}/old-one": f"{B}/new", f"{B}/old-two": f"{B}/new"}
        self.assertEqual(dead_seed_candidates(rmap), {})

    def test_empty(self):
        self.assertEqual(dead_seed_candidates({}), {})


if __name__ == "__main__":
    unittest.main()
