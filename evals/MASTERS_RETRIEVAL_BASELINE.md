# Master's Retrieval — Baseline Benchmark (Phase 6)

Store under evaluation: isolated unified evaluation store v2 (431 chunks: Phase-7 improved acquisition — nav-bleed guard, redirect canonicalization, widget stripping, directory cards; 5 pilot programs, depth-1 crawl + static base sources), queried via the unmodified production retriever

Retrieval-only (production `rag.retriever.retrieve`, k=5, min_score=0.30). No LLM, no reranking, no query rewriting.

## Overall metrics

- cases: 25 · passed: 21 · failed: 4
- **Recall@1: 82.61% · Recall@3: 86.96% · Recall@5: 91.30%**
- MRR: 0.8514
- latency: avg 11.2 ms · p50 7.6 ms · p95 10.0 ms

## Per-category

| category | cases | passed | R@1 | R@3 | R@5 |
| --- | --- | --- | --- | --- | --- |
| admission_requirements | 3 | 3 | 100% | 100% | 100% |
| advisor | 1 | 1 | 100% | 100% | 100% |
| application_process | 2 | 1 | 50% | 50% | 50% |
| concentration | 1 | 1 | 0% | 100% | 100% |
| curriculum | 2 | 2 | 100% | 100% | 100% |
| deadlines | 2 | 2 | 100% | 100% | 100% |
| department | 2 | 1 | 0% | 0% | 50% |
| doctoral_guard | 1 | 1 | 100% | 100% | 100% |
| faq_shared | 2 | 2 | 100% | 100% | 100% |
| gpa | 2 | 2 | 100% | 100% | 100% |
| international | 2 | 2 | 100% | 100% | 100% |
| multi_hop | 1 | 1 | 100% | 100% | 100% |
| negative | 2 | 0 | 0% | 0% | 0% |
| tuition | 2 | 2 | 100% | 100% | 100% |

## Failures

### MRE-008 [application_process / direct] — retriever_ranking
- query: Where do I send my official transcripts for the graduate business programs?
- expected: ['https://www.csulb.edu/cob-graduate-programs/admissions-information']
- first relevant rank: None
- evidence: expected URL present in store; first hit at rank 6 within probe k=20 (needed <= 5)
- top retrieved: [0.68] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs; [0.63] https://www.csulb.edu/admissions/doctoral-programs-application-process; [0.62] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs

### MRE-021 [department / direct] — acquisition_gap
- query: Tell me about the Political Science master's degree program at CSULB
- expected: ['http://cla.csulb.edu/departments/polisci/master-of-arts/']
- first relevant rank: None
- evidence: expected URL(s) have 0 chunks in the evaluation store
- top retrieved: [0.73] https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-masters#political-science-ma; [0.58] https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral; [0.57] https://www.csulb.edu/cob-graduate-programs/mba-programs

### MRE-024 [negative / negative] — evaluation_ambiguity
- query: where can I buy a student parking permit on campus
- expected: (no results expected)
- first relevant rank: None
- evidence: expected no results but retrieved 5 chunks (top score 0.6691)
- top retrieved: [0.67] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs; [0.38] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs; [0.36] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs

### MRE-025 [negative / negative] — evaluation_ambiguity
- query: freshman dormitory housing options for undergraduates
- expected: (no results expected)
- first relevant rank: None
- evidence: expected no results but retrieved 4 chunks (top score 0.422)
- top retrieved: [0.42] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs; [0.39] https://www.csulb.edu/college-of-health-human-services/public-policy-and-administration; [0.39] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs


## Phase 7 — before/after (corpus-quality improvements)

Store v1 (689 chunks) → v2 (431 chunks). Same retriever, embeddings, chunking,
and thresholds — only acquisition changed (widget stripping, redirect-aware
canonical URLs, nav-bleed host guard, directory-card documents).

| metric | v1 baseline | v2 (Phase 7) | Δ |
| --- | --- | --- | --- |
| Recall@1 | 82.61% | 82.61% | = |
| Recall@3 | 86.96% | 86.96% | = |
| Recall@5 | 86.96% | **91.30%** | **+4.3 pt** |
| MRR | 0.8406 | **0.8514** | +0.011 |
| passed | 20/25 | **21/25** | +1 |
| failures | 5 | 4 | −1 |
| store noise | 264 nav-bleed/utm chunks | 0 | −264 |

Failure-level changes:
- **MRE-020 (advisor): FAIL → PASS.** Directory-card documents made advisor
  facts retrievable (advisor category 0% → 100%).
- **MRE-021 (PoliSci): reclassified** embedding_limitation → acquisition_gap —
  the honest state: the stale CLA URL redirects to the college homepage; no
  Political Science program content exists anywhere in the crawlable corpus.
  Fixing it requires acquiring a real PoliSci source page, not retrieval work.
- **MRE-008 (transcripts) and MRE-024/025 (negatives): unchanged** — the
  remaining ranking miss and the out-of-scope threshold behavior were
  explicitly out of scope (no retriever/threshold changes permitted).

Ground-truth updates made during this phase (documented, evidence-based):
- MRE-020/MRE-006: the Graduate Studies directory (now indexed as per-program
  card documents) added as an accepted source — the cards literally contain the
  asked-for advisor/deadline facts.
- Known tradeoff (reported, not papered over): directory cards now compete with
  *overview*-style queries — MRE-023's department page slipped from rank 1 to
  rank 4 behind MPA card chunks. The card is not a program overview, so the
  golden expectation was left unchanged. A future metadata-aware ranking or
  content_type boost could address this; not justified from one case.
