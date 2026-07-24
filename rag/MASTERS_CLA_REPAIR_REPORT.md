# Master's CLA Acquisition Repair — Phase 9B Report

Repairs the CLA redirect class identified in Phase 8: the legacy
`cla.csulb.edu` department CMS was decommissioned, so 14 Graduate Studies
directory links (covering 18 master's programs) 302-redirect to the College
of Liberal Arts homepage, leaving those programs with no dedicated content.
Retriever, chunking, embeddings, ranking, evaluation framework, and the
Phase 9A hygiene rules are unchanged.

## Root cause

Every affected seed is a path under the old `cla.csulb.edu` CMS. A live probe
of all 22 CLA-hosted programs (2026-07-22) showed:

- **18 programs / 14 unique seeds:** `302 → https://www.csulb.edu/college-of-liberal-arts`
  (Economics and Political Science first take a `301 http→https`). The
  homepage is a "redirect magnet": many dead department links all collapse
  onto it. Classification: **redirects to a generic college homepage.**
- **4 programs / 3 seeds resolve correctly and were left untouched:** Asian
  Studies + Teaching Chinese (`aaas/graduate-credential/`, 200), Philosophy
  (`www.cla`→`cla` same path, 200 — the page MRE-018 already retrieves at
  0.88), Music (`web.csulb.edu/…/graduate-admissions.php`, 200).

For all 18, a dedicated replacement exists on the migrated site under
`www.csulb.edu/college-of-liberal-arts/<dept>/…`, each verified live: HTTP 200,
no redirect, real program content via the production extractor (e.g. the
Political Science MA page yields 31,841 chars).

## Repair mechanism (generic, data-driven)

- **Config:** `config/masters/seed_overrides.json` — 14 verified
  `stale → replacement` entries, each with `reason` and a `_verified` date.
  Absence of a program means "the directory seed is correct."
- **Mechanism:** `rag.masters_discovery.apply_seed_overrides` remaps matching
  seeds (scheme/trailing-slash-insensitive) right after directory parsing,
  before nested discovery *and* before directory-card building — so crawl
  seeds and each card's "Official program page" line both cite the live page.
  Unaffected programs pass through as the *same object*. Fail-safe: a
  missing/invalid config yields zero behavior change (identical to pre-9B).
- **Not a special case:** the mechanism is generic remapping; only the data is
  CLA-specific. Any future directory rot is fixed by adding a verified entry.

## Dead-seed self-detection (reusable)

`rag.masters_catalog_metrics.dead_seed_candidates` flags the homepage-magnet
signature — a final URL reached from ≥2 distinct requested URLs on a different
host — in the build audit. Reporting only; never an automatic exclusion. On
the Phase 9B build it reports **(none)**: the 14 magnet seeds are now remapped,
confirming the repair. If the directory rots again, the next build surfaces the
new magnet instead of silently indexing homepage boilerplate.

## Validation — Phase 9A vs Phase 9B (isolated full-catalog builds)

| metric | Phase 9A | Phase 9B | Δ |
| --- | --- | --- | --- |
| seed overrides applied | 0 | 18 | +18 |
| redirects followed (final != requested) | 23 | 12 | **−11** |
| dead-seed magnets detected | (n/a) | 0 | resolved |
| seed hosts `cla.csulb.edu` | 15 | 1 | −14 (only `aaas` remains) |
| unique pages | 151 | 165 | +14 |
| page documents accepted | 137 | 160 | +23 |
| master's chunks | 2675 | 3142 | **+467 (+17.5 %)** |
| total chunks / vectors | 2888 | 3355 | +467 |
| store size on disk | ~44 MB | ~49 MB | +5 MB |
| program coverage (any content) | 67/67 | 67/67 | = |
| programs with **dedicated** page content | 49/67 | **67/67** | +18 |

The four unaffected programs are byte-identical (Philosophy still on
`cla.csulb.edu`, Music on `web.csulb.edu`, Asian Studies / Teaching Chinese on
`aaas`).

### Dedicated page-chunk coverage (was shared-page + card only → now real)

| program family | 9A page chunks | 9B page chunks |
| --- | --- | --- |
| Political Science (MA) | 11 | 176 |
| Economics (MA) | 11 | 85 |
| Linguistics (MA) | 11 | 77 |
| TESOL (MA) | 11 | 77 |
| Creative Writing (MFA) | 11 | 59 |
| Geography (MA) | 11 | 55 |
| English (MA) | 11 | 51 |
| Communication Studies (MS) | 11 | 35 |
| Spanish / German / French (rgrll, MA each) | 11 | 32–33 |
| Religious Studies (MA) | 11 | 31 |
| History (MA) | 11 | 28 |
| Anthropology (+Applied) (MA) | 12 | 27 |
| Industrial/Organizational Psychology (MS) | 11 | 17 |

No program remains card-only (0 programs with 0 page chunks).

## Retrieval impact (unchanged framework, 25 golden cases)

| metric | Phase 9A | Phase 9B |
| --- | --- | --- |
| Recall@1 / @3 / @5 | 73.91 / 82.61 / 91.30 % | 73.91 / 82.61 / 91.30 % |
| MRR | 0.7949 | 0.7949 |
| passed | 21/25 | 21/25 |

Headline metrics are flat **by construction**: the golden dataset was authored
against the pilot store and none of its 25 queries target the newly-repaired
CLA programs — except **MRE-021 (Political Science)**, whose improvement is
real but masked by a stale ground-truth URL:

- **MRE-021 before:** acquisition_gap — top hit the directory anchor at 0.73,
  expected page had **0 chunks** in the store.
- **MRE-021 after:** the live PoliSci MA page
  (`…/college-of-liberal-arts/political-science/master-of-arts`) is indexed
  and retrieved at **rank 1, score 0.81**. The case still records "fail"
  **only** because its golden `expected_urls` still lists the dead
  `cla.csulb.edu/departments/polisci/master-of-arts/`.

Updating that expectation is the correct follow-up but is **deliberately not
done in this phase** — the eval golden set is under the "do not modify
evaluation" constraint. Recommended as a separate, reviewable change:
point MRE-021 `expected_urls` at the live page (which would move Recall@1 to
78.26 %, Recall@3 to 86.96 %, 22/25 passing).

No previously-passing case regressed; `doctoral_guard` stays 100 %.

## Remaining known issues

- MRE-021 golden URL update (above) — separate eval-set change.
- MRE-008 transcripts ranking miss; negative-case answerability gate (answer
  layer); `department`/`college` metadata gap — all unchanged, out of scope.
- The four resolving legacy-host programs still depend on `cla.csulb.edu` /
  `web.csulb.edu` staying up; if either is decommissioned next, the
  dead-seed detector will flag it and a new override entry repairs it.
