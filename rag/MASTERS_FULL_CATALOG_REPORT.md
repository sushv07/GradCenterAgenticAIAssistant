# Master's Full-Catalog Acquisition — Build & Quality Audit (Phase 8)

Produced by `python -m rag.masters_catalog_cli --scratch-dir <isolated dir>
--measure-embedding` against the live Graduate Studies directory
(2026-07-22). Store built in an isolated scratch directory — the production
`chroma_db/` was never touched (the builder refuses it by construction).
Acquisition path identical to Phases 1–7: same directory parser, generic
crawler, extractor, loader, chunker, embedder, and Chroma adapter — no new
acquisition logic, only instrumentation around the existing injection seams.

## Directory discovery

- programs discovered: 67
- unique seed URLs: 55
- seed hosts: {'cla.csulb.edu': 15, 'web.csulb.edu': 1, 'www.cla.csulb.edu': 1, 'www.cpace.csulb.edu': 3, 'www.csulb.edu': 35}
- programs with discovery warnings: 5
- index content hash: `sha256:c37f1663199a5745d3c254ee09a003d376a05efd519c3cb6cf2f74a856e5e5e6`

The live parse matches the committed snapshot fixture (67 programs / 55 unique
seeds), pinned by `tests/test_masters_full_catalog.py`.

## Nested page discovery

- unique pages: 153 (seed 54 · nested 99)
- shared pages (>1 program): 43
- programs skipped (no seed): 0
- fetches: 751 attempts · 13 failures

### Pages by classification

- department_application: 2
- international_instructions: 8
- overview_only: 22
- program_eligibility: 4
- program_requirements: 62
- supplemental_application: 17
- transcript_instructions: 38

## Extraction / validation

- pages processed: 153
- documents accepted: 139 (+ 67 directory cards)
- documents rejected: 14 (all `redirect_duplicate` — stale links collapsing
  onto already-converted final URLs; truthful-provenance dedup working as
  designed)
- empty pages: 0 · duplicate document IDs: 0
- redirects followed (final != requested): 23

### Missing optional metadata (accepted docs)

- college: 139 · department: 139 (known deferred gap — never fabricated)
- degree: 42 · program_name: 42 (shared multi-program pages, by design)

## Program coverage

- programs with page content: **67 of 67** (plus 67 directory cards)
- programs WITHOUT page content: 0

Coverage attribution note: six directory labels contain `", "` — the same
separator the masters loader uses to join `associated_programs` (flat ChromaDB
metadata). A naive split fragmented those labels and initially mis-reported 6
programs as uncovered and invented phantom program names. The audit now
reconstructs labels against the known label set
(`masters_catalog_metrics.split_associated_programs`, pinned by tests). The
loader's join format itself is a pre-existing Phase-3 representation, consumed
only by this audit; changing it was out of scope for Phase 8.

## Store

- master's chunks: 3254 (3173 page + 81 directory-card)
- base-source chunks: 213
- total chunks / indexed vectors: **3467**
- on-disk store size: ~51 MB
- avg chunks/program (attributed; shared pages count toward each associated
  program): 91.3

### Largest programs (top 10 by chunks)

- Criminology and Criminal Justice (MS): 618  ← see anomaly A1
- Emergency Services Administration (Online MS): 509
- International Affairs (MA): 319
- Sport Management (Online MA): 312
- Social Work (MSW): 200
- Science Education: Informal (MS): 169
- Science Education: TK-12 (MS): 169
- Athletic Training (MS): 167
- Exercise Science (MS): 157
- Museum Studies (MA): 129

### Smallest programs (bottom 10 by chunks)

All at 12 chunks (shared central pages + their directory card only):
Teaching English to Speakers of Other Languages (MA), Spanish (MA), Religious
Studies (MA), Political Science (MA), Linguistics ×3 variants (MA), History
(MA), German (MA), Geography (MA) — see anomaly A2.

## Stage timings (seconds)

- directory_discovery: 0.6
- nested_discovery: 452.9 (live crawl, 0.4 s politeness delay — dominates)
- extraction_conversion: 37.5 (includes redirect-aware re-fetch)
- chunking: 0.03
- base_sources: 2.9
- embedding_measured: 15.4 (benchmark-only explicit pass, 3467 chunks, CPU)
- index_fused_embed_and_index: 17.1 (Chroma fuses embed+index)
- indexing_derived: ~1.7 (fused − measured embedding)
- **total: 526 s (~8.8 min)** — network-bound; compute is ~35 s of it

## Anomalies (highlighted, not silently fixed)

- **A1 — PDF indexed as text (largest single noise source).** 512 of
  Criminology's 618 chunks come from
  `…/MSCCJ%20Program%20Application%20Form_0.pdf`: the crawler follows the
  link, the fetcher returns the PDF byte stream, and the extractor/chunker
  treat it as text. ~15 % of the store is one garbled document. Proposed fix
  (needs approval; touches the acquisition layer): skip non-HTML content types
  at fetch/discovery time.
- **A2 — CLA stale-redirect class confirmed at scale.** 14 of the 16
  `cla.csulb.edu`/`www.cla.csulb.edu` seeds 301-redirect to the College of
  Liberal Arts homepage; after dedup, ~10 humanities MAs (the entire 12-chunk
  bottom cluster) have no program-specific page content — only shared central
  pages and their directory card. This is roadmap item 2 (acquire real source
  pages); Political Science (MRE-021) is one member of this class.
- **A3 — stale event page.** `…/college-of-health-human-services/fall-2021`
  (67 chunks) is a Fall-2021 COVID-era page; it is also the top hit (0.79) for
  the parking-permit negative eval case. Candidate for a staleness/aggregator
  filter in a future corpus-quality pass.
- **A4 — fetch failures (13).** 3× SSL failure on a `processLogout.action`
  link (cpace courseware — crawler followed a session link), 6× HTTP 403
  (`graduate-center/transcripts` and `.php` legacy pages appear bot-blocked),
  4× HTTP 404 (dead legacy links). None fatal; all fail-safe skipped.
- **A5 — marketing hosts.** 3 seeds live on `www.cpace.csulb.edu`; their
  International Affairs pages rank in eval case MRE-021's top-5 — thin
  marketing-style content, kept because seeds are always kept by design.

## Scalability assessment

- **Storage:** 3467 vectors ≈ 51 MB on disk (384-dim float32 + text + HNSW).
  Linear in chunks; a 10× corpus (~35 k chunks) would be ~0.5 GB — fine for
  local/desktop, tight but viable on Render's 512 MB instance only if the
  store lives on disk and query-time memory stays bounded (Chroma mmaps; the
  embedding model itself is ~90 MB resident).
- **Build:** crawl dominates (452 s of 526 s) and is politeness-limited, not
  compute-limited; embedding all 3467 chunks took 15 s on CPU. Scaling to more
  sources scales linearly in pages fetched. The current single-threaded,
  0.4 s-delay crawl is the right shape for one university; it would need
  scheduling (not redesign) only if sources multiplied by ~10×.
- **Operational:** a full production rebuild with `MASTERS_INGESTION_ENABLED`
  would add ~8–9 min to the TTL/first-request rebuild path — unacceptable
  inline on Render; run it as a scheduled/manual build (the store is
  persisted, so serving cost is unchanged). Double-fetching (discovery +
  redirect-aware extraction) is ~2× network cost; a shared fetch cache would
  halve crawl time if that ever matters.
- **Architecture verdict:** no redesign warranted by evidence. The ports &
  adapters pipeline, deterministic IDs, and upsert/prune modes already support
  incremental growth; the pressure points at scale are corpus *quality*
  filters (A1–A3), not throughput.

## Retrieval regression

See `evals/MASTERS_FULL_CATALOG_RETRIEVAL.md` (Recall@5 and pass count held;
Recall@1 diluted — analysed per case there).
