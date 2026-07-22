# Master's Retrieval — Baseline Benchmark (Phase 6)

Store under evaluation: isolated unified evaluation store (689 chunks: 5 pilot master's programs, depth-1 crawl + static base sources), queried via the unmodified production retriever

Retrieval-only (production `rag.retriever.retrieve`, k=5, min_score=0.30). No LLM, no reranking, no query rewriting.

## Overall metrics

- cases: 25 · passed: 20 · failed: 5
- **Recall@1: 82.61% · Recall@3: 86.96% · Recall@5: 86.96%**
- MRR: 0.8406
- latency: avg 15.6 ms · p50 8.2 ms · p95 30.3 ms

## Per-category

| category | cases | passed | R@1 | R@3 | R@5 |
| --- | --- | --- | --- | --- | --- |
| admission_requirements | 3 | 3 | 100% | 100% | 100% |
| advisor | 1 | 0 | 0% | 0% | 0% |
| application_process | 2 | 1 | 50% | 50% | 50% |
| concentration | 1 | 1 | 0% | 100% | 100% |
| curriculum | 2 | 2 | 100% | 100% | 100% |
| deadlines | 2 | 2 | 100% | 100% | 100% |
| department | 2 | 1 | 50% | 50% | 50% |
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
- evidence: expected URL present in store; first hit at rank 7 within probe k=20 (needed <= 5)
- top retrieved: [0.68] https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs; [0.63] https://www.csulb.edu/admissions/doctoral-programs-application-process; [0.63] https://www.cpace.csulb.edu/courses/degree-programs/master-of-arts-in-international-affairs

### MRE-020 [advisor / direct] — retriever_ranking
- query: Who is the graduate advisor for the Linguistics MA program?
- expected: ['https://cla.csulb.edu/departments/linguistics/ma-program/']
- first relevant rank: None
- evidence: expected URL present in store; first hit at rank 18 within probe k=20 (needed <= 5)
- top retrieved: [0.55] https://www.cpace.csulb.edu/courses/degree-programs/master-of-arts-in-international-affairs; [0.51] https://www.cpace.csulb.edu/courses/degree-programs/master-of-science-in-geographic-information-science; [0.47] https://www.cpace.csulb.edu/courses/degree-programs/master-of-arts-in-international-affairs

### MRE-021 [department / direct] — embedding_limitation
- query: Tell me about the Political Science master's degree program at CSULB
- expected: ['http://cla.csulb.edu/departments/polisci/master-of-arts/']
- first relevant rank: None
- evidence: expected URL present in store but absent from the top 20 results for this query
- top retrieved: [0.65] https://www.cpace.csulb.edu/courses/degree-programs/master-of-arts-in-international-affairs; [0.64] https://www.cpace.csulb.edu/courses/degree-programs/master-of-arts-in-international-affairs; [0.58] https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral

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


## Root-cause annotations (manual, evidence-backed)

The automated classification above reports the *mechanical* failure point.
Inspecting the actual indexed chunks refines the root causes:

- **MRE-020 (advisor) & MRE-021 (PoliSci overview)** — mechanically
  ranking/embedding failures, but the true root cause is **acquisition/extraction**:
  the CLA department seed pages (`cla.csulb.edu/.../linguistics/ma-program/`,
  `.../polisci/master-of-arts/`) yielded only 2 chunks each, containing **CLA
  news boilerplate** ("Beach alumni leave gift…", "Remembering Frank Fata…") —
  no program or advisor content exists under the expected URLs to rank. This is
  the CLA-template extraction gap already documented in Phase 3 calibration
  ("CLA generic layout yields no overview"). Advisor names additionally live only
  in the directory cards, which are not indexed (known acquisition gap).
- **MRE-020/021 noise source** — the top-ranked competitors are the CPACE
  degree pages (149 + 59 chunks) pulled in by **shared-navigation bleed**
  (Phase 2 finding): they dominate generic "master's program" queries by volume.
- **MRE-008 (transcripts)** — genuine ranking miss (expected page at rank 7),
  compounded by mild evaluation ambiguity: the FAQ page ranked first does also
  discuss transcript submission.
- **MRE-024/025 (negative queries)** — production `min_score=0.30` admits
  loosely-related FAQ chunks for out-of-scope queries (top scores 0.67 / 0.42).
  Dense retrieval + a permissive threshold means "no relevant knowledge" is not
  currently detectable. A known characteristic, now quantified.

## Recommendations (ranked by expected impact — NOT implemented)

1. **Fix CLA-template extraction / seed-page quality (acquisition layer).**
   Evidence: 2/25 failures are pages whose indexed text is 100% news boilerplate;
   any program hosted on the `cla.csulb.edu` template will fail identically at
   full-catalog scale (~15+ of 67 programs are CLA-hosted).
2. **Index directory-card facts (advisor/deadline metadata) as retrievable
   content.** Evidence: the advisor category is 0/1; advisor names exist only in
   the un-indexed DiscoveryManifest cards.
3. **Suppress shared-navigation bleed (canonical-URL + nav-block filtering).**
   Evidence: CPACE pages (208 chunks, 2 programs' nav bleed) appear in the top-3
   of every failed generic query; at 67 programs this noise multiplies.
4. **Raise/side-channel the out-of-scope threshold.** Evidence: both negative
   cases retrieved ≥0.42-scored chunks; consider a higher answerability bar at
   the answer layer rather than changing production retrieval defaults.
5. **Reranking / query rewriting — NOT yet justified.** Evidence: only one
   failure (MRE-008, rank 7) would plausibly be fixed by a reranker; recall@5 on
   well-extracted pages is already 100%. Revisit after items 1–3 land.
