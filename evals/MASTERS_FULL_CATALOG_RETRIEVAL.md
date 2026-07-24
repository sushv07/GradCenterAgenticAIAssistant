# Master's Retrieval — Full-Catalog Regression (Phase 8)

Store under evaluation: isolated FULL-CATALOG store (all 67 discoverable
master's programs, depth-1 crawl + static base sources; 3467 chunks), queried
via the **unmodified** production retriever (`k=5`, `min_score=0.30`). Same
25-case golden dataset, same evaluation framework (`run_masters_retrieval_evals`),
zero retrieval/eval changes. Baseline for comparison: Phase 7 pilot store
(431 chunks, 5 programs) in `MASTERS_RETRIEVAL_BASELINE.md`.

## Overall — Phase 7 baseline vs Phase 8 full catalog

| metric | Phase 7 (431 chunks) | Phase 8 (3467 chunks) | Δ |
| --- | --- | --- | --- |
| Recall@1 | 82.61% | 73.91% | **−8.7 pt** |
| Recall@3 | 86.96% | 82.61% | −4.3 pt |
| Recall@5 | 91.30% | **91.30%** | = |
| MRR | 0.8514 | 0.7949 | −0.057 |
| cases passed | 21/25 | **21/25** | = |
| failed case IDs | MRE-008/021/024/025 | MRE-008/021/024/025 | same set |
| latency avg | 11.2 ms | 14.4 ms | +3.2 ms (8× corpus) |

**Headline:** pass count and Recall@5 are fully preserved at 8× corpus size,
and no previously-passing case fails. The loss is concentrated in *rank-1*
precision: newly indexed same-topic pages from other programs now compete
with the golden pages. This is corpus-scale dilution, not a retriever, corpus
or golden-set defect — explained per case below; no changes proposed without
review.

## Per-case changes (only cases that moved)

- **MRE-002 (admission_requirements, paraphrase): rank 1 → 5** (still passes).
  The MPA admissions page is now outranked by College of Education
  "online application submission" pages added with the full catalog — the
  paraphrase query ("how many separate applications…") semantically matches
  any application-submission page. Pure dilution.
- **MRE-018 (faq_shared): rank 1 → 2** (still passes). The newly acquired
  Philosophy `graduate_admissions` page (a *legitimate*, program-specific CLA
  page that did not redirect to the college homepage) scores 0.88 and takes
  rank 1. Arguably a better-grounded hit for the query; ground truth left
  unchanged.
- **MRE-008 (transcripts, already failing): rank 6 @k=20 → absent @k=20**;
  reclassified retriever_ranking → embedding_limitation by the evidence-based
  classifier. Dozens of new transcript/application chunks
  (`transcript_instructions`: 38 pages) push the COB admissions page out of
  the probe window. Remains the standing reranking candidate.
- **MRE-024 (negative, already failing): top score 0.67 → 0.79**, now hitting
  the stale `fall-2021` page (which mentions parking) — anomaly A3 in
  `rag/MASTERS_FULL_CATALOG_REPORT.md`. Reinforces the answerability-gate
  roadmap item (answer layer, not retrieval).
- **MRE-021 (PoliSci, already failing): unchanged acquisition_gap** — now
  conclusively evidenced at scale: its CLA seed is one of 14 that 301-redirect
  to the college homepage (anomaly A2). Needs a real source page, not
  retrieval work.
- All other 19 cases: identical ranks (17 at rank 1; MRE-015 rank 3,
  MRE-023 rank 4 — unchanged from baseline).

## Per-category (Phase 8)

| category | cases | passed | R@1 | R@3 | R@5 |
| --- | --- | --- | --- | --- | --- |
| admission_requirements | 3 | 3 | 67% | 67% | 100% |
| advisor | 1 | 1 | 100% | 100% | 100% |
| application_process | 2 | 1 | 50% | 50% | 50% |
| concentration | 1 | 1 | 0% | 100% | 100% |
| curriculum | 2 | 2 | 100% | 100% | 100% |
| deadlines | 2 | 2 | 100% | 100% | 100% |
| department | 2 | 1 | 0% | 0% | 50% |
| doctoral_guard | 1 | 1 | 100% | 100% | 100% |
| faq_shared | 2 | 2 | 50% | 100% | 100% |
| gpa | 2 | 2 | 100% | 100% | 100% |
| international | 2 | 2 | 100% | 100% | 100% |
| multi_hop | 1 | 1 | 100% | 100% | 100% |
| negative | 2 | 0 | 0% | 0% | 0% |
| tuition | 2 | 2 | 100% | 100% | 100% |

`doctoral_guard` stays at 100% — full master's ingestion still does not
regress doctoral retrieval.

## Phase 9A addendum — corpus hygiene rebuild

After the Phase 9A filters (non-HTML resources, term-year archives — see
`rag/MASTERS_CORPUS_HYGIENE_REPORT.md`), the full-catalog store shrank
3467 → 2888 chunks (−16.7 %) with **identical** retrieval metrics
(R@1 73.91 % · R@3 82.61 % · R@5 91.30 % · MRR 0.7949 · 21/25, every
first-relevant rank unchanged). MRE-024's top hit reverted from the stale
`fall-2021` page (0.79) to the FAQ (0.67), matching Phase 7 behavior.

## Phase 9B addendum — CLA acquisition repair

After remapping 14 decommissioned CLA seeds to verified live replacements
(18 programs; see `rag/MASTERS_CLA_REPAIR_REPORT.md`), the store grew
2888 → 3355 chunks (+467) and every CLA program gained dedicated content
(e.g. Political Science 11 → 176 page chunks). Overall metrics are unchanged
(R@1 73.91 % · R@3 82.61 % · R@5 91.30 % · MRR 0.7949 · 21/25) because no
golden query targets the repaired programs **except MRE-021**:

- **MRE-021 (Political Science)** flipped from `acquisition_gap` (expected URL
  had 0 chunks) to retrieving the live PoliSci MA page at **rank 1, score
  0.81** — a genuine repair. It still records "fail" only because its golden
  `expected_urls` lists the now-dead `cla.csulb.edu` URL. Per the "do not
  modify evaluation" constraint, the golden set was NOT changed this phase.
  Recommended separate follow-up: update MRE-021's `expected_urls` to
  `https://www.csulb.edu/college-of-liberal-arts/political-science/master-of-arts`,
  which would yield R@1 78.26 %, R@3 86.96 %, 22/25.

## Notes

- The golden dataset was authored against the pilot store; it remains valid
  (all expected URLs still resolvable in the full store except the known
  MRE-021 gap) and was NOT modified in this phase.
- Corpus-quality candidates surfaced by this regression (PDF chunks, stale
  fall-2021 page, CLA redirect class) are catalogued as anomalies A1–A3 in
  `rag/MASTERS_FULL_CATALOG_REPORT.md` and await review before any fix.
