# Master's Corpus Hygiene — Phase 9A Report

Deterministic corpus-quality filters addressing the two highest-impact
anomalies from the Phase 8 audit (`MASTERS_FULL_CATALOG_REPORT.md`, A1/A3).
Retriever, chunking, embeddings, prompts, and the evaluation framework are
unchanged; the filters live entirely in the master's acquisition layer,
following the Phase 7 nav-bleed-guard precedent.

## Rules introduced

### 1. Unsupported resource types (`is_supported_resource`)

Nested-page URLs whose (percent-decoded, case-insensitive) path ends in
`.pdf`, `.doc`, `.docx`, `.ppt`, or `.pptx` are skipped at discovery time.

- **Why safe:** the extractor is an HTML extractor; there is no binary
  document pipeline in this repo. Indexing a byte stream as text can only add
  noise (Phase 8 evidence: one PDF produced 512 garbled chunks — ~15 % of the
  entire store). The rule reads only the URL path — deterministic, no
  fetching, no classification. Lookalike slugs (`/pdf-guidelines`) survive
  because only the path *suffix* is tested.
- **Defense in depth:** `fetch_page_final` additionally rejects 200 responses
  whose `Content-Type` is non-HTML, catching extensionless binaries reached
  via redirects. An absent header is treated as HTML (never observed on
  csulb.edu).

### 2. Obsolete term archives (`is_obsolete_term_page`)

Nested-page URLs whose FINAL path segment is exactly `<season>-<year>`
(e.g. `fall-2021`) are skipped.

- **Why safe:** a bare term-year slug is a term-scoped announcement/archive
  page, not an evergreen program page (Phase 8 evidence: the CHHS `fall-2021`
  COVID-era page — 67 chunks — was the top hit, 0.79, for a *negative* eval
  case). The rule is intentionally narrow: segments that merely CONTAIN a
  term-year (`fall-2026-deadlines`, `apply-by-fall-2026`) are untouched, so
  legitimate deadline pages survive. Static regex, no dates computed, no
  "current term" logic — fully deterministic and reproducible.

Both guards apply to **nested pages only** — directory seeds are always kept,
so no program can be silently dropped by a hygiene rule. Every skip is
recorded with its reason (`MastersDiscoveryResult.skipped_pages`) and surfaced
in the build audit report.

## Skipped resources (live rebuild, 2026-07-22)

| URL | reason | chunks removed |
| --- | --- | --- |
| `…/sites/default/files/2026/documents/MSCCJ%20Program%20Application%20Form_0.pdf` | unsupported_resource_type | 512 |
| `…/college-of-health-human-services/fall-2021` | obsolete_term_archive | 67 |

## Store before/after (isolated full-catalog builds, same recipe)

| metric | Phase 8 | Phase 9A | Δ |
| --- | --- | --- | --- |
| unique pages | 153 | 151 | −2 |
| page documents accepted | 139 | 137 | −2 |
| directory cards | 67 | 67 | = |
| master's chunks | 3254 | 2675 | **−579 (−17.8 %)** |
| total chunks / vectors | 3467 | 2888 | **−579 (−16.7 %)** |
| store size on disk | ~51 MB | ~44 MB | −7 MB |
| program coverage | 67/67 | 67/67 | = |
| duplicate document IDs | 0 | 0 | = |
| largest program (chunks) | Criminology 618 (83 % PDF) | Emergency Services 509 | PDF noise gone |

Criminology and Criminal Justice drops from 618 chunks (512 of them one
garbled PDF) to its genuine ~39 page + card chunks; its real pages (department
graduate page, admissions) remain indexed.

Build time: 853 s vs 526 s in Phase 8 — the difference is live-site/network
variance (crawl 593 s vs 453 s; extraction 224 s vs 37 s on slower responses),
not the filters, which do no additional fetching. Compute stages shrank with
the corpus (embedding 9.8 s vs 15.4 s).

## Retrieval regression (unchanged framework, 25 golden cases)

| metric | Phase 8 | Phase 9A |
| --- | --- | --- |
| Recall@1 | 73.91 % | 73.91 % |
| Recall@3 | 82.61 % | 82.61 % |
| Recall@5 | 91.30 % | 91.30 % |
| MRR | 0.7949 | 0.7949 |
| passed | 21/25 | 21/25 (same set) |

Every case's first-relevant rank is identical to Phase 8 — removing 579 noise
chunks cost **zero** retrieval quality, confirming the removed content never
contributed a relevant hit. The one behavioral improvement is on the failing
negative case MRE-024: its top hit is no longer the stale `fall-2021` page at
0.79 but the FAQ at 0.67 — back to the Phase 7 baseline behavior (the case
still fails by design pending an answer-layer answerability gate).

## Remaining known issues (unchanged by this phase)

- CLA stale-redirect class (~10 humanities MAs with only shared/card content)
  — roadmap item 2; needs real source pages, not filtering.
- MRE-008 transcripts ranking miss; negative-case answerability gate (answer
  layer); `department`/`college` metadata gap.
- Rank-1 dilution from same-topic pages across programs (Phase 8 finding) —
  a future `content_type`/program-aware ranking question, explicitly not
  retrieval work for this phase.
