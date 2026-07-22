> **⚠️ Superseded — legacy document.**
> This file documents an earlier (pre-refactor) architecture of the CSULB
> Graduate Center AI Assistant, including a flat root-level file layout
> (`guidance_agent.py`, `answer_agent.py`, `query_handler.py`, `tracker.py`,
> etc.) that no longer exists in the codebase. It is retained for historical
> reference only and is **not maintained**.
>
> For the current, actively-maintained architecture documentation, see
> **[`../../ARCHITECTURE_ANALYSIS.md`](../../ARCHITECTURE_ANALYSIS.md)**.

---

# CSULB Graduate Center Agentic AI Assistant — Complete Architecture Documentation

---

## 1. SYSTEM OVERVIEW

### What the System Currently Does
The CSULB Graduate Center AI Assistant is a Streamlit web application that answers graduate admissions questions for California State University, Long Beach. It routes user queries through a deterministic multi-agent pipeline backed by a local ChromaDB vector store (RAG), a local JSON knowledge base, and fuzzy-match advisor lookup. There is no real-time LLM call in the primary execution path — the system is overwhelmingly deterministic rule-based with semantic retrieval layered on top.

### Main Capabilities Found in Code [IMPLEMENTED]
- **Intent-based routing** (`orchestrator.run()`) — 7 route types: `guidance`, `checklist`, `answer`, `tracking`, `advisor`, `deadlines`, `eligibility`, `application`, `next_steps`
- **Step-by-step application guidance** (`guidance_agent.guide_from_file()`) — 6 intent flows: `application_process`, `newly_admitted`, `doctoral_application`, `eligibility`, `international`, `orientation`
- **Interactive checklists** (`checklist_agent` path in orchestrator) — stateful, saved to `sessions/<id>.json`
- **Progress tracking** (`tracker.py`) — mark steps as `pending`/`in_progress`/`completed`, dependency-aware blocking, percent progress
- **Advisor fuzzy lookup** (`advisor_retrieval.py` + `tools/advisor_tool.py`) — `rapidfuzz.partial_ratio`/`ratio` against `advisors_extracted.json`, ambiguity detection
- **Auto-generated email draft** (`tools/email_tool.py`) — template subject/body + Outlook Web deep-link via `urllib.parse`
- **Deadline card retrieval** (`tools/deadlines_tool.py`) — ChromaDB RAG scoped to `page_type="deadlines"` with per-program card parsing
- **Eligibility retrieval** (`tools/eligibility_tool.py`) — ChromaDB RAG with `admissions.json` fallback
- **Program-aware application steps** (`tools/application_steps_tool.py`) — program alias detection, `workflow_priority`-based specificity, full-page reassembly from ChromaDB
- **FAQ semantic lookup** (`faq_rag_module.py`) — ephemeral in-memory Chroma store (1h TTL), `all-MiniLM-L6-v2` embeddings, scraped live from CSULB FAQ page
- **Program interest response** (`tools/program_interest_tool.py`) — deterministic template-based response for prospective students
- **Web-crawled program discovery** (`rag/discovery.py`) — automatic classification of doctoral program pages into `workflow_priority` tiers

### Deterministic vs Agentic Behaviors

| Behavior | Type | Notes |
|---|---|---|
| Intent routing in `orchestrator.run()` | Deterministic | Regex token matching + priority hierarchy |
| Advisor fuzzy matching | Deterministic | `rapidfuzz` scoring with hardcoded thresholds |
| Guidance step generation | Deterministic | Static JSON + keyword dictionaries |
| Checklist construction | Deterministic | Static admissions.json data |
| Progress tracking state machine | Deterministic | JSON file reads/writes |
| Email draft generation | Deterministic | String template interpolation |
| FAQ RAG semantic retrieval | Quasi-agentic | Vector similarity; no LLM decision |
| Deadlines/eligibility RAG | Quasi-agentic | Vector similarity; no LLM decision |
| Application steps RAG + bullet extraction | Quasi-agentic | Vector similarity + regex noise filtering |
| `agent.py` multi-turn tool calling | Agentic (legacy) | OpenAI `gpt-4o-mini` function calling — **not in primary UI path** |

### Current User Interaction Flow
```
User types query in Streamlit chat input
  → st.session_state["messages"] updated
  → orchestrator.run(query, session_id) called
  → Route detected (GUIDANCE / CHECKLIST / ANSWER / TRACKING / advisor / deadlines / eligibility / application / next_steps)
  → Appropriate agent/tool returns structured dict
  → _format_response() wraps in UI schema
  → Streamlit renders response panel (guidance expanders / checklist items / advisor card / deadline card / tracking bar)
  → next_actions[] shown as clickable suggestion chips
```

---

## 2. ARCHITECTURE LAYERS + TOOLS USED

### A. UI Layer [IMPLEMENTED]

**Purpose:** Single-page Streamlit app with branded CSULB Gold/Navy theme, sidebar session management, and multi-route response rendering.

**Files/Modules:** `app.py` (entire file)

**Tools/Libraries:**
- `streamlit>=1.35.0` — page layout, sidebar, chat bubbles (`st.chat_input`, `st.chat_message`), expanders, columns, `st.markdown(unsafe_allow_html=True)`
- `pathlib.Path` — static image loading
- `base64` (Python stdlib) — logo/Elbee mascot encoded as data URIs
- Custom CSS (~1,000 lines injected via `st.markdown`) — CSS variables, CSULB color tokens, `.csulb-header`, `.nav-item`, `.deadline-card`, `.app-step-card`, `.advisor-card` etc.

**Key Functions:**
- `_render_header()` — sticky gold gradient header with base64 logo
- `_render_sidebar()` — amber sidebar with session ID input, clear history button, Elbee mascot
- `_render_guidance_panel(steps)` — step-by-step expanders
- `_render_checklist_panel(steps)` — checkbox UI per step
- `_render_tracking_panel(response)` — progress bar + breakdown + current focus block
- `_render_advisor_panel(response)` — two-column advisor card + email draft preview + Outlook button
- `_render_deadline_card(card)` — structured two-column card per program
- `_render_topic_panel(response, topic)` — router for deadlines/eligibility/application routes
- `_render_application_steps(workflow_steps, program_name)` — step cards with category badge, full text, related links
- `_render_program_interest_panel(response)` — template-based program interest display

**Limitations:**
- No async rendering; each interaction blocks the Streamlit event loop
- No pagination — all steps rendered in a single scroll
- Session state lives only in `st.session_state`; clearing browser tab loses UI state (file persists)

---

### B. Orchestration Layer [IMPLEMENTED]

**Purpose:** Central router. Classifies intent, enforces a priority hierarchy of 7 possible routes, calls the appropriate agent/tool, and wraps the result in a UI-friendly dict.

**Files/Modules:** `orchestrator.py`

**Tools/Libraries:**
- Python `re` — `_tokenize()` regex token splitting, `_parse_tracking_command()` regex patterns
- Python `enum.Enum` — `Route` enum (`GUIDANCE`, `CHECKLIST`, `ANSWER`, `TRACKING`)
- `json` — response serialization

**Key Functions:**
- `orchestrator.run(query, session_id)` — master entry point, 9-branch priority tree
- `detect_route(query)` — keyword-token routing for 4 base routes
- `_parse_tracking_command(query)` — regex tracking command parser (mark step N, pending, progress, list_sessions)
- `_build_topic_response(topic, query, session_id)` — calls `deadlines_tool`, `eligibility_tool`, or `application_steps_tool`
- `_humanize_guidance/checklist/answer/tracking()` — presentation-layer formatters
- `_format_response()` — final schema wrapper
- `format_for_display()` — terminal CLI formatter

**Priority Hierarchy in `run()`:**
1. Topic-priority routing (deadlines/eligibility/application) if no advisor/checklist/tracking signal
2. Advisor retrieval via `find_advisor()` (if not `is_process_query`)
3. PhD/doctoral no-match → doctoral program list
4. Advisor-intent with no program → prompt for program name
5. START-intent intercept → `get_next_steps()` + `faq_rag_lookup()`
6. `detect_route()` → GUIDANCE / CHECKLIST / ANSWER / TRACKING

**Limitations:**
- Routing is entirely keyword-token based — no semantic understanding of intent
- All route branches are synchronous/blocking

---

### C. Agent / LLM Layer

**Primary path: [IMPLEMENTED — no LLM]**
`answer_agent.py` — rule-based extractor pipeline. No LLM call. Consumes `query_handler.handle_query()` output and runs a waterfall of 6 named extractors (`_extract_faq`, `_extract_deadlines`, `_extract_steps`, `_extract_contact`, `_extract_amounts`, `_extract_eligibility`, `_extract_programs`, `_extract_generic`).

**Legacy path: [IMPLEMENTED but not in primary UI path]**
`agent.py` — OpenAI `gpt-4o-mini` function calling with 4 tools (`get_advisor`, `draft_email`, `create_outlook_draft`, `ask_clarification`). Uses `openai>=1.0.0` SDK. Requires `OPENAI_API_KEY` env var. Called from `advisor_retrieval.handle_query()` as part of the old standalone CLI flow — not invoked by `app.py` or `orchestrator.py`.

**Libraries:**
- `openai>=1.0.0` — legacy only, `client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))`
- `MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")`

**No Anthropic/Claude SDK used anywhere in this codebase.**

**Key dataclass:** `answer_agent.Answer` — `query`, `answer`, `answer_type` (`direct`/`list`/`table`/`faq`/`unknown`), `source_file`, `source_url`, `confidence` (`high`/`medium`/`low`), `next_steps`

**Confidence scoring (rule-based):**
- `faq` → always `"high"`
- `table`/`list` non-empty → `"high"`
- `direct` with ≥3 token overlap → `"high"`, ≥1 → `"medium"`, 0 → `"low"`
- `unknown` → `"low"`

**Limitations:**
- No real LLM reasoning in the primary path — answer quality is bounded by extractor rules
- OpenAI dependency is planned for removal in Phase 7 (per `requirements.txt` comment)

---

### D. RAG / Retrieval Layer [IMPLEMENTED]

**Purpose:** Two-tier retrieval — a persistent ChromaDB store (`rag/` package) and an ephemeral in-memory Chroma store (`faq_rag_module.py`).

**Files/Modules:** `rag/__init__.py`, `rag/store.py`, `rag/retriever.py`, `rag/ingestion.py`, `rag/chunking.py`, `rag/discovery.py`, `faq_rag_module.py`, `admissions_rag.py`

**Tools/Libraries:**
- `langchain>=1.0.0`, `langchain-community>=0.4.0`, `langchain-core>=1.0.0`, `langchain-text-splitters>=1.0.0`
- `chromadb>=0.5.0` — persistent store in `./chroma_db/` (SQLite-backed)
- `sentence-transformers>=3.0.0` — embedding model `all-MiniLM-L6-v2`, 384-dim, CPU
- `langchain_community.embeddings.HuggingFaceEmbeddings` — wrapper
- `langchain_community.vectorstores.Chroma` — vector store wrapper
- `langchain_core.documents.Document` — chunk container
- `langchain_text_splitters.RecursiveCharacterTextSplitter` — `chunk_size=500`, `chunk_overlap=75`
- `requests>=2.31.0` — HTML page fetching
- `beautifulsoup4>=4.12.0` — HTML parsing/cleaning
- `ollama>=0.1.0` — listed in requirements for Phase 4+ local LLM, **not yet used**

**Persistent RAG (`rag/` package):**

Data sources ingested (5 page types):
1. `faq` — CSULB Graduate Center FAQs page
2. `deadlines` — Doctoral Programs, Advisors and Deadlines page (specialist parser per program card)
3. `eligibility` — Doctoral Programs Admission Eligibility page
4. `application_process` — Doctoral Programs Application Process page
5. `program_application` — Auto-discovered per-program pages (via `rag/discovery.py`)

Chunk metadata stored per chunk: `title`, `url`, `page_type`, `chunk_id` (`{md5(url)[:8]}_{index:04d}`), `chunk_index`, `program_name`, `content_category`, `workflow_priority`, `discovered_from`, `parent_program_url`, `links_json`

TTL: 24 hours (`STORE_TTL = 86_400`). TTL file: `chroma_db/.last_built`.

Self-healing: `_store_has_program_pages()` checks for `program_application` chunks and triggers a rebuild if the store predates discovery implementation.

**Ephemeral FAQ RAG (`faq_rag_module.py`):**
- In-memory Chroma store, rebuilt every 3600s (1h TTL)
- Scrapes CSULB FAQ accordion cards live on each rebuild
- Returns `{"guidance": markdown_text_with_links, "source": url}`

**Discovery (`rag/discovery.py`):**
- Starts from doctoral programs index page
- Classifies each program's linked pages into 8 `content_category` values and assigns `workflow_priority` 1–6
- Follows up to `_MAX_NESTED_LINKS=15` links per seed page with `_CRAWL_DELAY=0.4s`

**Retrieval interface:**
- `retrieve(query, k, min_score, page_type, program_name)` — filtered cosine similarity search
- `retrieve_multi(query, k_per_type, min_score)` — k results per page_type
- `MIN_RELEVANCE = 0.30`

**Limitations:**
- Single `all-MiniLM-L6-v2` model; no reranking
- No query expansion or hybrid keyword+dense retrieval
- `faq_rag_module.py` uses a separate in-memory store that duplicates embedding model loading
- Discovery crawl can fail silently on network errors
- `langchain-community` wrappers produce deprecation warnings on newer LangChain (noted in `requirements.txt`)

---

### E. Advisor Mapping Layer [IMPLEMENTED]

**Purpose:** Match free-text queries to CSULB doctoral program advisors using fuzzy string matching.

**Files/Modules:** `advisor_retrieval.py`, `tools/advisor_tool.py`, `advisors_extracted.json`, `advisors.json`

**Tools/Libraries:**
- `rapidfuzz>=3.0.0` — `fuzz.partial_ratio` (primary, catches abbreviations) and `fuzz.ratio` (tiebreaker)

**Key Constants:**
- `FUZZY_THRESHOLD = 90` — confirmed match
- `SUGGESTION_THRESHOLD = 70` — "did you mean?" suggestions
- `AMBIGUITY_THRESHOLD = 89` — 2+ programs near the top triggers disambiguation
- `NEAR_EXACT_THRESHOLD = 95` — alias exact match, skip ambiguity

**Process:**
1. `normalize_query()` — lowercase, strip punctuation, remove `STOP_WORDS` (37 words)
2. Score every advisor record via `_best_score_for()` — checks program name AND `aliases` list
3. Ambiguity check: if 2+ records ≥ 89 score and top record's full-ratio < 95 → unique-token disambiguation
4. Returns `{match: dict|None, confidence: int, suggestions: list[str]}`

**Data:** `advisors_extracted.json` — scraped via `scrape_advisors.py` (BeautifulSoup). Fields: `program`, `advisor_name`, `email`, `phone`, `office`, `source`, `aliases`

**Limitations:**
- Program aliases are hardcoded in each advisor record
- Stop word list lives only in `advisor_retrieval.py`
- `query_handler.py` has a parallel (simpler) `_PROGRAM_ALIASES` dict that doesn't share the `rapidfuzz` path

---

### F. Workflow State Layer [IMPLEMENTED]

**Purpose:** Persist checklist step states across Streamlit re-renders and browser refreshes.

**Files/Modules:** `tracker.py`, `sessions/*.json`

**Tools/Libraries:**
- Python `json`, `pathlib`, `datetime` (stdlib only)

**Operations:**
- `save(session_id, guidance_result)` — validates dependency graph before persisting; overwrites existing
- `load(session_id)` — returns full record or `None`
- `mark(session_id, step_ref, status)` — accepts step number (int) or step id (str like `"apply-3"`)
- `pending(session_id)` — returns pending/in_progress steps with `is_blocked` and `blocked_by` annotations
- `progress(session_id)` — `{total, completed, in_progress, pending, percent_done, blocked, ready, current_item}`
- `list_sessions()` — scans `sessions/*.json`, returns summary dicts
- `delete(session_id)` — removes file

**Step Schema (persisted):**
`id`, `step`, `title`, `action`, `primary_action`, `details`, `priority`, `status`, `depends_on`, `prep`, `how`, `time`, `outcome`, `glossary`, `warnings`, `resources`

**Dependency graph validation:** `guidance_agent.validate_steps()` — checks unknown `depends_on` ids and detects circular dependencies via DFS (white/gray/black coloring)

**Limitations:**
- File-based storage; no concurrent access protection
- Sessions stored in the project directory — not portable across machines
- No expiry/cleanup of old sessions

---

### G. Email Draft / Outlook Layer [IMPLEMENTED]

**Purpose:** Generate advisor email drafts and Outlook Web compose deep-links without auto-opening any email client.

**Files/Modules:** `tools/email_tool.py`

**Tools/Libraries:**
- `urllib.parse` (Python stdlib) — `urllib.parse.quote()` for URL encoding
- No external HTTP calls; no email sending

**Functions:**
- `draft_email(advisor_name, advisor_email, program, context)` → `{found, subject, body, to, ...}`
  - Template subject: `"Inquiry About the {program} Program — Prospective Student"`
  - Body has `[Your Name]`, `[Your Phone Number]`, `[Your CSULB ID / Email]` placeholders
- `build_outlook_url(to_email, subject, body)` → `{found, outlook_url}`
  - URL: `https://outlook.office.com/mail/deeplink/compose?to=...&subject=...&body=...`

**Safety contract:** Outlook URL is returned in the response dict; the UI (`_render_advisor_panel()`) shows a button. Outlook is never auto-opened.

---

### H. Observability / Debugging Layer [PARTIALLY IMPLEMENTED]

**Exists:**
- `print()` statements in `rag/store.py` — `[store] Loading embedding model`, `[store] Rebuilding`, `[store] ✓ Vector store built`
- `print()` statements in `rag/retriever.py` — `[retriever] Vector store unavailable`, `[retriever] Query failed`
- `traceback.print_exc()` in `store.get_or_build_store()` on exception
- Store TTL timestamp file `chroma_db/.last_built`

**Missing [PLANNED/RECOMMENDED]:**
- No structured logging (`logging` module not imported anywhere)
- No latency tracking / timing per route
- No query/response logging to file or external system
- No error rate monitoring
- No Streamlit session ID correlation in logs
- No ChromaDB query score distributions tracked
- No retrieval quality regression tests run in CI

---

### I. Storage Layer [IMPLEMENTED]

**Files/Modules:**
- `data/*.json` — 9 structured JSON files:
  - `admissions.json` — 6 sections: `application_steps`, `doctoral_application_steps`, `newly_admitted_steps`, `eligibility`, `international_students`, `orientation`
  - `advisors.json` / `advisors_extracted.json` — advisor contact records with aliases
  - `faqs.json` — FAQ categories, Q&A pairs
  - `funding.json`, `grad_center.json`, `milestones_thesis.json`, `programs.json`, `student_resources.json`, `why_csulb.json` — supplementary knowledge
  - `index.json` — `data_files[]` with topic lists + `keyword_to_file_map`
- `sessions/*.json` — one file per user session (default `sessions/default.json`)
- `chroma_db/chroma.sqlite3` — ChromaDB SQLite persistent store
- `chroma_db/.last_built` — TTL timestamp

**Limitations:**
- All storage is local filesystem; no database, no cloud storage
- `data/*.json` are static snapshots (manually updated)
- No versioning of data files

---

### J. Deployment / Runtime Layer [IMPLEMENTED]

**Tools:**
- `streamlit>=1.35.0` — `streamlit run app.py`
- Python 3.13 (inferred from `__pycache__` filenames: `*.cpython-313.pyc`)
- `.streamlit/config.toml` — Streamlit server configuration
- `requirements.txt` — pinned dependencies with `>=` floor versions
- No Docker, no CI/CD config files, no Procfile found

**Env vars:**
- `OPENAI_API_KEY` — required only for legacy `agent.py`
- `OPENAI_MODEL` — optional, defaults to `gpt-4o-mini` in `agent.py`
- No env var needed for the primary Streamlit app path

**Runtime singletons:**
- `_EMBEDDINGS` in `rag/store.py` — shared `HuggingFaceEmbeddings` instance
- `_STORE` in `rag/store.py` — shared `Chroma` instance
- `_EMBEDDINGS` + `_VECTORSTORE` in `faq_rag_module.py` — separate singletons
- `advisors` list in `advisor_retrieval.py` — loaded at module import time

---

## 3. REQUEST EXECUTION FLOW

Tracing query `"What are the deadlines for DNP?"`:

```
app.py:  st.chat_input captures query
          → orchestrator.run("What are the deadlines for DNP?", session_id="default")

orchestrator.run():
  1. _tokenize(query) → {"deadlines", "dnp", "what", ...}
  2. _raw_toks = {"what", "are", "deadlines", "for", "dnp"}
  3. _has_advisor_signal = False  (no "advisor", "contact", "who" tokens)
  4. _has_checklist = False
  5. _has_tracking = False
  6. _raw_toks & _DEADLINE_SIGNALS = {"deadlines"} → truthy
  7. → _build_topic_response("deadlines", query, session_id)

_build_topic_response():
  1. from tools.deadlines_tool import get_deadlines
  2. result = get_deadlines("What are the deadlines for DNP?")

tools/deadlines_tool.get_deadlines():
  1. retrieve(query, k=8, min_score=0.25, page_type="deadlines")
     → rag/retriever.retrieve():
         store = rag/store.get_or_build_store()
             → loads from chroma_db/ (if fresh) or triggers ingest_pages() + chunk_documents() + build_vector_store()
         filter: {"page_type": {"$eq": "deadlines"}}
         store.similarity_search_with_relevance_scores(query, k=16, filter=filter)
         → returns up to 8 chunks above 0.25 threshold
  2. _parse_chunk_to_card(chunk) for each result → deadline_cards[]
  3. top_card = deadline_cards[0]  (Nursing D.N.P.)
  4. _query_matches_program("What are the deadlines for DNP?", "Nursing (D.N.P.)")
     → pass 2: "dnp" found in q_norm → True
  5. score >= 0.42 and specific → deadline_card = top_card
  6. returns {deadline_card, deadline_cards, results, disclaimer, ...}

_build_topic_response() continues:
  → builds summary from first result text
  → returns full orchestrator response dict with route="deadlines"

app.py _render_topic_panel():
  → route == "deadlines"
  → deadline_card exists → _render_deadline_card(card)
     → st.markdown(HTML deadline table with spring/fall columns)
  → shows clarification button or disambiguation if needed
  → renders next_actions as clickable chips
```

---

## 4. MODULE-BY-MODULE BREAKDOWN

### `app.py`
**Purpose:** Streamlit UI entry point. Owns all rendering logic.
**Responsibilities:** CSS injection, page config, sidebar, session state initialization, chat rendering, response routing to panel renderers, suggestion chip buttons, Elbee mascot display.
**Key Functions:** `_init_state()`, `_render_header()`, `_render_sidebar()`, `_render_guidance_panel()`, `_render_checklist_panel()`, `_render_tracking_panel()`, `_render_advisor_panel()`, `_render_deadline_card()`, `_render_topic_panel()`, `_render_application_steps()`, `_render_program_interest_panel()`
**Dependencies:** `orchestrator`, `tools.program_interest_tool`, `streamlit`, `pathlib`, `base64`
**Architecture Role:** UI layer only; calls `orchestrator.run()` per query

### `orchestrator.py`
**Purpose:** Master query router and response formatter.
**Responsibilities:** Token-based intent routing, advisor lookup, topic-priority routing, start-intent intercept, tracking command parsing, humanizer presentation layer, CLI REPL.
**Key Functions:** `run()`, `detect_route()`, `_parse_tracking_command()`, `_build_topic_response()`, `_humanize_guidance/checklist/answer/tracking()`, `_format_response()`, `format_for_display()`
**Dependencies:** `query_handler`, `answer_agent`, `guidance_agent`, `tracker`, `advisor_retrieval`, `tools/application_steps_tool`, `tools/deadlines_tool`, `tools/eligibility_tool`, `tools/email_tool`, `next_steps`, `faq_rag_module`
**Architecture Role:** Orchestration layer

### `guidance_agent.py`
**Purpose:** Build structured step-by-step guidance from `data/admissions.json`.
**Responsibilities:** Intent detection (6 intents), step building (4 builders), metadata enrichment (warnings, resources, prep, how-to, time, outcome, glossary), dependency resolution, cycle validation.
**Key Classes:** `GuidanceStep` (dataclass with 17 fields)
**Key Functions:** `detect_intent()`, `guide()`, `guide_from_file()`, `_build_guidance()`, `_attach_metadata()`, `_resolve_dependencies()`, `validate_steps()`
**Dependencies:** `json`, `re`, `dataclasses`, `pathlib`
**Architecture Role:** Guidance agent — purely deterministic, no LLM

### `answer_agent.py`
**Purpose:** Extract a precise typed answer from `query_handler` output.
**Responsibilities:** 8-extractor waterfall pipeline, confidence scoring, source URL resolution, 3-pass extraction (FAQ first → primary block → secondary block).
**Key Class:** `Answer` (dataclass)
**Key Functions:** `answer()`, `ask()`, `_run_extractors()`, `_extract_faq/deadlines/steps/contact/amounts/eligibility/programs/generic()`
**Dependencies:** `query_handler`
**Architecture Role:** Answer agent — deterministic rule-based extractor

### `query_handler.py`
**Purpose:** Score and load JSON data files for a query; also handles advisor routing.
**Responsibilities:** Index loading, topic+keyword scoring, file content extraction, FAQ matching, advisor routing, next-step suggestions, fallback responses.
**Key Functions:** `handle_query()`, `rank_files()`, `extract_relevant_sections()`, `extract_faq_matches()`, `handle_advisor_query()`, `is_advisor_query()`, `build_fallback()`, `suggest_next_steps()`
**Dependencies:** `json`, `re`, `pathlib`
**Architecture Role:** JSON retrieval layer (parallel/legacy to ChromaDB RAG)

### `advisor_retrieval.py`
**Purpose:** Fuzzy-match advisor lookup with ambiguity detection.
**Key Functions:** `find_advisor()`, `normalize_query()`, `_best_score_for()`, `format_advisor_result()`, `handle_query()` (standalone CLI entry point)
**Dependencies:** `rapidfuzz.fuzz`, `json`, `re`
**Architecture Role:** Advisor mapping layer

### `tracker.py`
**Purpose:** Session-scoped progress tracking with dependency-aware blocking.
**Key Functions:** `save()`, `load()`, `mark()`, `pending()`, `progress()`, `list_sessions()`, `delete()`, `start_session()`
**Dependencies:** `json`, `pathlib`, `datetime`, `guidance_agent.validate_steps`
**Architecture Role:** Workflow state layer

### `tools/deadlines_tool.py`
**Purpose:** RAG retrieval for doctoral program deadlines with per-program card parsing.
**Key Functions:** `get_deadlines()`, `_parse_chunk_to_card()`, `_query_matches_program()`
**Dependencies:** `rag.retrieve`, `re`
**Architecture Role:** Tool layer — deadlines domain

### `tools/eligibility_tool.py`
**Purpose:** RAG retrieval for eligibility requirements with JSON fallback.
**Key Functions:** `get_eligibility()`, `_load_eligibility_json()`
**Dependencies:** `rag.retrieve`, `json`, `pathlib`
**Architecture Role:** Tool layer — eligibility domain

### `tools/application_steps_tool.py`
**Purpose:** Program-aware application step retrieval — the most complex tool.
**Key Functions:** `get_application_steps()`, `_detect_program()`, `_build_steps_from_results()`, `_extract_workflow_steps()`, `_extract_application_bullets()`, `_extract_page_links()`, `_get_all_chunks_for_url()`, `_merge_raw_chunks()`, `_merge_ordered_chunks()`
**Dependencies:** `rag.retrieve`, `rag.store.get_or_build_store`, `json`, `re`, `pathlib`
**Architecture Role:** Tool layer — application domain (most complex)

### `tools/advisor_tool.py`
**Purpose:** Thin wrapper around `advisor_retrieval.find_advisor()` with standard tool output schema.
**Key Functions:** `get_advisor()`
**Dependencies:** `advisor_retrieval`
**Architecture Role:** Tool layer — advisor domain

### `tools/email_tool.py`
**Purpose:** Email draft template + Outlook deep-link URL builder.
**Key Functions:** `draft_email()`, `build_outlook_url()`
**Dependencies:** `urllib.parse`
**Architecture Role:** Tool layer — email domain

### `tools/program_interest_tool.py`
**Purpose:** Deterministic template-based program interest response generator.
**Key Functions:** `generate_program_specific_response()`, `generate_general_interest_response()`
**Dependencies:** `advisor_retrieval.find_advisor`, `json`, `pathlib`
**Architecture Role:** Tool layer — program interest domain

### `rag/store.py`
**Purpose:** ChromaDB persistent store lifecycle management.
**Key Functions:** `get_or_build_store()`, `build_vector_store()`, `load_vector_store()`, `invalidate_store()`, `_store_is_fresh()`, `_store_has_program_pages()`
**Dependencies:** `langchain_community.embeddings.HuggingFaceEmbeddings`, `langchain_community.vectorstores.Chroma`, `shutil`, `time`, `pathlib`
**Architecture Role:** Vector store management

### `rag/retriever.py`
**Purpose:** Query interface for the vector store.
**Key Functions:** `retrieve()`, `retrieve_multi()`
**Dependencies:** `rag.store`
**Architecture Role:** Retrieval layer

### `rag/ingestion.py`
**Purpose:** Fetch and parse CSULB pages into structured page dicts.
**Key Functions:** `ingest_pages()`, `fetch_page()`, `parse_page()`, `_parse_deadlines_page()`
**Dependencies:** `requests`, `bs4.BeautifulSoup`, `re`, `time`, `urllib.parse`
**Architecture Role:** Data ingestion

### `rag/chunking.py`
**Purpose:** Split page text into overlapping LangChain Documents.
**Key Functions:** `chunk_documents()`
**Dependencies:** `langchain_core.documents.Document`, `langchain_text_splitters.RecursiveCharacterTextSplitter`, `hashlib`, `json`
**Architecture Role:** Chunking

### `rag/discovery.py`
**Purpose:** Auto-classify doctoral program application pages via content signals.
**Key Functions:** `discover_program_pages()`, `classify_page()`, `_score_page_signals()`
**Dependencies:** `bs4.BeautifulSoup`, `requests` (via ingestion), `re`, `urllib.parse`
**Architecture Role:** Web crawler + content classifier

### `faq_rag_module.py`
**Purpose:** Live-scraped in-memory FAQ vector store with 1h TTL.
**Key Functions:** `faq_rag_lookup()`, `_get_embeddings()`, `_fetch_faq_entries()`, `_build_vectorstore()`
**Dependencies:** `langchain_community.embeddings.HuggingFaceEmbeddings`, `langchain_community.vectorstores.Chroma`, `langchain_core.documents.Document`, `langchain_text_splitters.RecursiveCharacterTextSplitter`, `requests`, `bs4`
**Architecture Role:** FAQ-specific in-memory RAG

### `agent.py`
**Purpose:** Legacy multi-turn OpenAI agent (NOT used by primary UI path).
**Key Functions:** `run_agent(user_message, history)`, `_tool_get_advisor()`, `_tool_draft_email()`, `_tool_create_outlook_draft()`, `_tool_ask_clarification()`
**Dependencies:** `openai`, `advisor_retrieval`
**Architecture Role:** Legacy agentic layer (being phased out)

---

## 5. TOOLS TABLE

| Layer | Tool/Library | Used For | File/Module | Current Role | Future Improvement |
|---|---|---|---|---|---|
| UI | `streamlit>=1.35.0` | Page layout, chat, sidebar, widgets | `app.py` | Single-page app framework | Add async, caching decorators |
| UI | `base64` (stdlib) | Logo/mascot data URIs | `app.py` | Inline image embedding | CDN-served assets |
| UI | CSS (injected) | CSULB Gold/Navy branding | `app.py` | Custom component styling | Move to Streamlit component or external CSS file |
| Orchestration | `re` (stdlib) | Token routing, tracking command parsing | `orchestrator.py`, `guidance_agent.py`, `query_handler.py` | Intent detection | Replace with lightweight NLU model |
| Orchestration | `enum.Enum` (stdlib) | Route type constants | `orchestrator.py` | Type-safe routing | Keep |
| Agent | `openai>=1.0.0` | GPT-4o-mini function calling | `agent.py` (legacy) | Legacy agent path | Remove in Phase 7 |
| Agent | `dataclasses` (stdlib) | Answer/GuidanceStep structs | `answer_agent.py`, `guidance_agent.py` | Structured data | Keep |
| RAG | `langchain>=1.0.0` | Base framework | `rag/`, `faq_rag_module.py` | RAG pipeline framework | Upgrade to split packages when Python 3.13 compatible |
| RAG | `langchain-community>=0.4.0` | `HuggingFaceEmbeddings`, `Chroma` wrappers | `rag/store.py`, `faq_rag_module.py` | Embedding + store wrappers | Migrate to `langchain-huggingface`, `langchain-chroma` |
| RAG | `langchain-core>=1.0.0` | `Document` class | `rag/chunking.py`, `faq_rag_module.py` | Chunk container | Keep |
| RAG | `langchain-text-splitters>=1.0.0` | `RecursiveCharacterTextSplitter` | `rag/chunking.py`, `faq_rag_module.py` | Text chunking | Keep, tune chunk_size |
| RAG | `chromadb>=0.5.0` | Persistent vector store | `rag/store.py` | SQLite-backed vector DB | Add cloud Chroma or Pinecone for production |
| RAG | `sentence-transformers>=3.0.0` | `all-MiniLM-L6-v2` embeddings (384-dim) | `rag/store.py`, `faq_rag_module.py` | Dense embeddings | Try `all-mpnet-base-v2` for better quality |
| RAG | `requests>=2.31.0` | HTTP page fetching | `rag/ingestion.py`, `faq_rag_module.py`, `scrape_advisors.py` | Web scraping | Add async (aiohttp) for parallel ingestion |
| RAG | `beautifulsoup4>=4.12.0` | HTML parsing | `rag/ingestion.py`, `rag/discovery.py`, `faq_rag_module.py`, `scrape_advisors.py` | DOM traversal + text extraction | Keep |
| RAG | `ollama>=0.1.0` | Local LLM (planned) | Not yet used | Phase 4+ local LLM | Implement with `qwen2.5:7b` |
| Advisor | `rapidfuzz>=3.0.0` | `fuzz.partial_ratio`, `fuzz.ratio` | `advisor_retrieval.py` | Fuzzy program name matching | Keep + add embedding-based fallback |
| Storage | `json` (stdlib) | JSON read/write for sessions + data | `tracker.py`, `query_handler.py`, `guidance_agent.py`, etc. | Structured data storage | Migrate to SQLite or PostgreSQL |
| Storage | `pathlib` (stdlib) | Filesystem paths | All modules | Path management | Keep |
| Email | `urllib.parse` (stdlib) | URL encoding for Outlook deep-link | `tools/email_tool.py` | Mailto/Outlook URL builder | Keep |
| State | `datetime` (stdlib) | UTC timestamps for sessions | `tracker.py` | Session metadata | Keep |
| State | `hashlib` (stdlib) | `chunk_id` generation | `rag/chunking.py` | Stable chunk IDs | Keep |

---

## 6. AGENTIC BEHAVIOR ANALYSIS

### What is Truly Agentic vs Deterministic

**Truly Agentic [LEGACY — `agent.py` only, not in primary path]:**
- OpenAI `gpt-4o-mini` decides which tool to call based on conversation history
- Multi-turn conversation with clarification requests (`ask_clarification` tool)
- LLM selects arguments for `get_advisor()`, `draft_email()`, `create_outlook_draft()`

**Quasi-agentic [IMPLEMENTED — primary path]:**
- Vector similarity scoring determines which RAG chunks are relevant — non-deterministic at different run times if store is rebuilt
- `_query_matches_program()` in `deadlines_tool.py` — two-pass heuristic (word match + abbreviation match)
- `find_advisor()` ambiguity resolution — unique-token disambiguation has a form of "reasoning"
- `_extract_application_bullets()` — regex noise filtering is a signal-based classifier

**Purely Deterministic [IMPLEMENTED — primary path]:**
- All routing in `orchestrator.run()` — keyword token matching
- `guidance_agent.detect_intent()` — keyword score maximization
- `tracker` state machine — status transitions
- Email draft generation — string interpolation

### Where Clarification Happens [IMPLEMENTED]
- `deadlines_tool.py` — `needs_clarification=True` when query is vague; `clarification_hint` string built from all program names
- `advisor_retrieval.find_advisor()` — returns `suggestions[]` when ambiguous
- `orchestrator.run()` — advisor-intent with no program name returns a prompt asking for program
- `guidance_agent` — returns `{"error": "Empty query"}` on empty input

### Where Reasoning Happens [DETERMINISTIC]
No genuine LLM reasoning in the primary path. The closest approximation: `_extract_generic()` in `answer_agent.py` scores answer quality by token overlap, and `_score_confidence()` assigns confidence labels.

### Current Limitations
- The primary path has **zero LLM reasoning** — all decisions are rule/regex-based
- `agent.py` LLM path is not wired to the Streamlit UI
- No multi-turn memory in the orchestrator (each query is stateless except for `session_id` passed to `tracker`)

---

## 7. RAG DESIGN ANALYSIS

### Retrieval Pipeline [IMPLEMENTED]
```
User query
  → rag/retriever.retrieve(query, k, min_score, page_type, program_name)
  → rag/store.get_or_build_store() [TTL check → load from disk or rebuild]
  → store.similarity_search_with_relevance_scores(query, k*2, filter=where_filter)
  → [score >= min_score] → sort descending → return top k
```

### Chunking Strategy [IMPLEMENTED]
- `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=75)`
- Separator priority: `\n\n` → `\n` → sentence end → word → character
- Specialist deadlines parser: 1 chunk per program card (~150–220 chars) to prevent program boundary bleed
- FAQ ingestor: question+answer paired in same chunk

### Ranking / Scoring [IMPLEMENTED]
- Cosine similarity (`hnsw:space=cosine`) via ChromaDB HNSW index
- `MIN_RELEVANCE = 0.30` global floor
- Per-tool thresholds: `deadlines_tool` uses `min_score=0.25` + `_CARD_THRESHOLD=0.42` + `_DOMINANT_SCORE=0.60`
- No reranking; no BM25 hybrid

### Caching [IMPLEMENTED]
- Persistent ChromaDB: 24h TTL file `chroma_db/.last_built`
- FAQ store: 1h TTL `_VECTORSTORE_TTL = 3600` in-memory
- Embedding model: process-level singleton via `_EMBEDDINGS` global
- Store: process-level singleton via `_STORE` global

### Grounding / Hallucination Prevention [IMPLEMENTED]
- Every response includes `source_url` from chunk metadata
- `answer_agent._score_confidence()` labels low-overlap answers as `"low"` confidence with disclaimer
- `_humanize_answer()` for `confidence="low"` responses routes to `"contact GraduateCenter@csulb.edu"` fallback
- Disclaimer strings injected into all topic responses
- `answer_agent.answer()` returns `"I don't know"` string rather than hallucinating

### Whether Embeddings/Vector Search Are IMPLEMENTED
**[IMPLEMENTED]** — ChromaDB with `all-MiniLM-L6-v2` is fully operational. The persistent store in `chroma_db/chroma.sqlite3` is built and used for `deadlines`, `eligibility`, `application_process`, and `program_application` routes. The `faq_rag_module.py` in-memory store is separately operational.

---

## 8. WORKFLOW STATE ANALYSIS

### How User Progress Is Stored [IMPLEMENTED]
`sessions/<session_id>.json` — one JSON file per session. Contains full `GuidanceStep` dicts with `status` fields. Written atomically on every `tracker.mark()` call.

### How Dependencies Work [IMPLEMENTED]
`depends_on: list[str]` — list of prerequisite step IDs. Resolved in `guidance_agent._resolve_dependencies()` (title → id translation). In `tracker.pending()` and `tracker.progress()`, `_blocked_by()` walks `depends_on` and returns unmet prerequisites. A step is `is_blocked=True` if any `depends_on` id is not in `completed_ids`.

### How Blocked Tasks Are Handled [IMPLEMENTED]
`_annotate_step()` adds `blocked_by: list[{step, id, title}]` and `is_blocked: bool`. The orchestrator's `_next_step_instruction()` detects `blocked_by` and generates a redirect instruction: `"Step X is waiting on Step Y — take care of that one first."` UI renders 🔒 icon and "Blocked" label.

### How Sessions Are Persisted [IMPLEMENTED]
File written on `save()` and `mark()`. Session name defaults to `"default"`. User can change `session_id` in the sidebar text input, which clears `st.session_state["messages"]` and triggers rerun. Old session files remain on disk until `tracker.delete()` is called.

### How State Affects Responses [IMPLEMENTED]
`_humanize_tracking()` reads `progress.percent_done`, `progress.completed`, `progress.current_item` to generate context-aware progress messages and next-action suggestions. `_tracking_next_actions()` generates different `next_actions[]` based on whether the user has in-progress steps, pending steps, or is fully complete.

---

## 9. SCALABILITY ANALYSIS

### Bottlenecks
1. **Embedding model load on cold start** — `all-MiniLM-L6-v2` takes 2–5s to load the first time. Affects first user query after app restart.
2. **ChromaDB rebuild** — full rebuild takes 30–60s, triggered if TTL expired. Blocks all queries during rebuild.
3. **In-memory FAQ store** — `faq_rag_module.py` re-embeds ~50 chunks every hour, taking 5–10s, blocking the FAQ route.
4. **Synchronous web scraping in `ingest_pages()`** — sequential HTTP fetches with 0.4s crawl delay; rebuilding with discovery can take 60–120s.
5. **Single-process Streamlit** — all requests share one Python process; concurrent users compete for embedding model and ChromaDB access.

### What Breaks at Scale
- File-based `sessions/*.json` — race conditions with concurrent mark operations
- `_STORE` global singleton — not thread-safe if Streamlit spawns multiple worker threads
- ChromaDB local SQLite — single-writer limitation
- `advisors_extracted.json` loaded at module import — fine for hundreds of programs, not for tens of thousands

### Which Components Could Become Microservices
1. **RAG retrieval service** — expose `retrieve()` as REST API
2. **Advisor lookup service** — expose `find_advisor()` as REST API
3. **Tracker service** — expose `save/mark/progress/pending` over HTTP with proper locking
4. **Ingestion/rebuild service** — background job triggered on schedule

### Caching Opportunities
- Streamlit `@st.cache_resource` on `get_or_build_store()` — prevents rebuilds on Streamlit re-renders
- `@st.cache_data(ttl=3600)` on `faq_rag_lookup()` — prevents hourly rebuilds per query
- Result-level caching: identical queries within a session could be memoized

### Async Opportunities
- `ingest_pages()` could use `asyncio` + `aiohttp` for parallel page fetches
- `faq_rag_module.py` rebuild could run in a background thread

### Cloud Deployment Options
- Streamlit Community Cloud (current app already compatible)
- AWS/GCP App Engine with persistent volume for `chroma_db/`
- Pinecone or Weaviate to replace local ChromaDB for multi-instance deployments

---

## 10. ARCHITECTURAL TRADEOFFS

### Deterministic Routing vs Full Agent Autonomy
**Current:** Token-matching priority tree in `orchestrator.run()`. Predictable, fast, zero API cost, no hallucination risk in routing. But fragile on out-of-vocabulary queries (e.g., misspellings, non-English) and requires manual stop-word and signal set maintenance.
**Tradeoff:** Full agent autonomy (LLM router) would generalize better but adds latency (100–500ms), cost, and non-determinism. Hybrid: use LLM only as fallback when token-match confidence is low.

### Local JSON Storage vs Database
**Current:** `sessions/*.json` + `data/*.json`. Zero infrastructure, easy to inspect, simple backup. But no ACID guarantees, no concurrent writer safety, no query indexing, no schema migration.
**Tradeoff:** SQLite (even `sqlite3` stdlib) would give atomic writes and simple queries. PostgreSQL would enable multi-user session management and proper indexing.

### Keyword/Fuzzy Matching vs Vector Retrieval
**Current:** `rapidfuzz` for advisors, token-score ranking in `query_handler.rank_files()`. Fast and interpretable. But misses paraphrases (e.g., "nurse practitioner" vs "DNP"), handles abbreviations only via explicit alias lists.
**Tradeoff:** Embedding-based advisor lookup would generalize to "what's the contact for the nursing doctorate?" without explicit alias maintenance.

### Streamlit Prototype vs Production Web App
**Current:** Streamlit. Fast to build, Python-native, good for internal/demo tools. But limited concurrent user support, re-renders full page on each interaction, limited component customization (worked around via ~1,000 lines of CSS injection).
**Tradeoff:** FastAPI + React frontend would give proper REST API, real-time updates, component libraries, and horizontal scaling.

### Cost vs Intelligence
**Current:** Zero LLM inference cost in the primary path. But answers are bounded by extractor rules and keyword overlap — complex paraphrased questions fail gracefully but unhelpfully.
**Tradeoff:** Adding local Ollama (`qwen2.5:7b`, already in `requirements.txt`) for answer synthesis would improve quality at zero API cost.

### Reliability vs Flexibility
**Current:** Deterministic routing is highly reliable — no LLM failure modes, no API outages. But adding new response types requires code changes.
**Tradeoff:** A fully agentic approach requires careful prompt engineering and fallback handling.

---

## 11. VISUAL TEXT DIAGRAMS

### High-Level Architecture Diagram
```
┌─────────────────────────────────────────────────────────┐
│                     STREAMLIT UI                        │
│  app.py: sidebar · header · chat · panel renderers      │
└──────────────────────┬──────────────────────────────────┘
                       │ orchestrator.run(query, session_id)
┌──────────────────────▼──────────────────────────────────┐
│                   ORCHESTRATOR                          │
│  orchestrator.py: route detection · humanizers          │
└────┬───────┬──────┬──────┬──────┬──────┬──────┬────────┘
     │       │      │      │      │      │      │
  GUIDANCE CHECKLIST ANSWER TRACKING ADVISOR DEADLINES ELIGIBILITY/APPLICATION
     │       │      │      │      │      │      │
  guidance  tracker answer advisor deadlines eligibility application
  _agent    .py    _agent  _retrieval _tool  _tool     _steps_tool
     │              │              │      │      │           │
  admissions  query_handler  advisors_ rag/   rag/       rag/
  .json        + data/*.json  extracted retriever retriever  retriever
                              .json         │           │
                                            └─────┬─────┘
                                            chroma_db/
                                            (ChromaDB SQLite)
                                            all-MiniLM-L6-v2
```

### Layered Tools Diagram
```
┌─────────────────────────────────────────────┐
│ PRESENTATION          Streamlit + CSS        │
├─────────────────────────────────────────────┤
│ ORCHESTRATION         orchestrator.py (re)   │
├─────────────────────────────────────────────┤
│ TOOLS                 deadlines / eligibility│
│                       application_steps      │
│                       advisor / email        │
│                       program_interest       │
├─────────────────────────────────────────────┤
│ AGENTS (det.)         guidance_agent         │
│                       answer_agent           │
│                       tracker                │
├─────────────────────────────────────────────┤
│ RAG (vector)          rag/ package           │
│                       faq_rag_module.py      │
│                       ChromaDB + MiniLM      │
├─────────────────────────────────────────────┤
│ RAG (keyword)         query_handler          │
│                       data/index.json        │
├─────────────────────────────────────────────┤
│ FUZZY MATCH           advisor_retrieval      │
│                       rapidfuzz             │
├─────────────────────────────────────────────┤
│ STORAGE               data/*.json            │
│                       sessions/*.json        │
│                       chroma_db/             │
└─────────────────────────────────────────────┘
```

### Request Lifecycle Diagram
```
User Input
    │
    ▼
st.chat_input (app.py)
    │
    ▼
orchestrator.run(query, session_id)
    │
    ├── has DEADLINE token? ──────────────────► deadlines_tool.get_deadlines()
    │                                                │
    ├── has ELIGIBILITY token? ─────────────► eligibility_tool.get_eligibility()
    │                                                │
    ├── is PROCESS + PROGRAM query? ────────► application_steps_tool.get_application_steps()
    │                                                │
    ├── advisor fuzzy match? ───────────────► advisor_retrieval.find_advisor()
    │        └─ yes + email? ─────────────► email_tool.draft_email() + build_outlook_url()
    │
    ├── START intent? ──────────────────────► next_steps.get_next_steps() + faq_rag_lookup()
    │
    └── detect_route() ──────────────────┬─► GUIDANCE → guidance_agent.guide_from_file()
                                         ├─► CHECKLIST → guidance_agent + tracker.save()
                                         ├─► ANSWER → answer_agent.answer(query_handler.handle_query())
                                         └─► TRACKING → tracker.mark/pending/progress/list_sessions()
    │
    ▼
_format_response() / _humanize_X()
    │
    ▼
_render_X_panel() (app.py)
    │
    ▼
Streamlit chat message + next_actions chips
```

### Orchestration Flow Diagram
```
orchestrator.run(query)
│
├─ [1] is_process_query? (apply/steps/start...)
├─ [2] _raw_toks & _DEADLINE_SIGNALS → _build_topic_response("deadlines")
├─ [3] _raw_toks & _ELIGIBILITY_SIGNALS → _build_topic_response("eligibility")
├─ [4] is_process_query AND (_PROCESS_STEP_SIGNALS OR program detected) → _build_topic_response("application")
├─ [5] find_advisor() match AND NOT is_process_query → advisor response + email_tool
├─ [6] doctoral tokens + no advisor match → list doctoral programs
├─ [7] advisor intent + confidence==0 → prompt for program name
├─ [8] START intent AND NOT apply/doctoral tokens → next_steps + faq_rag_lookup
└─ [9] detect_route():
        CHECKLIST → _run_checklist → guidance_agent + tracker.save
        GUIDANCE  → _run_guidance  → guidance_agent.guide_from_file
        ANSWER    → _run_answer    → answer_agent.answer(query_handler.handle_query)
        TRACKING  → _run_tracking  → tracker.mark/pending/progress/list_sessions
```

### Workflow State Diagram
```
          ┌──────────────┐
          │   pending    │◄──────────────────────────────────────┐
          └──────┬───────┘                                       │
         "mark step N in progress"                         "reset / undo"
                 │                                               │
          ┌──────▼───────┐                                       │
          │  in_progress │                                       │
          └──────┬───────┘                                       │
         "mark step N done"                                      │
                 │                                               │
          ┌──────▼───────┐                                       │
          │  completed   │──────────────────────────────────────►┘
          └──────────────┘

Blocked check (each query to pending()):
  step.depends_on → _blocked_by() → unmet prereqs → is_blocked=True → 🔒
```

### Tool Invocation Diagram
```
orchestrator._build_topic_response("deadlines")
    └► deadlines_tool.get_deadlines(query)
           └► rag.retrieve(query, k=8, min_score=0.25, page_type="deadlines")
                  └► rag.store.get_or_build_store()  [TTL check]
                         ├─ fresh → Chroma.load(chroma_db/)
                         └─ stale → ingest_pages() → chunk_documents() → build_vector_store()
                  └► store.similarity_search_with_relevance_scores()
           └► _parse_chunk_to_card(chunk) per result
           └► _query_matches_program(query, program_name)
    returns {deadline_card, disclaimer, sources, ...}

orchestrator (advisor path):
    └► advisor_retrieval.find_advisor(query)
           └► normalize_query(query)
           └► rapidfuzz.fuzz.partial_ratio + ratio per advisor record
    └► email_tool.draft_email(advisor_name, email, program)
           └► string template interpolation
    └► email_tool.build_outlook_url(to, subject, body)
           └► urllib.parse.quote()
```

---

## 12. INTERVIEW-READY EXPLANATION

### 60-Second Explanation
"I built a full-stack AI assistant for CSULB's Graduate Center using Python and Streamlit. Students ask questions about grad school admissions — things like deadlines, eligibility, advisor contacts, or what to do after being accepted. The system routes each query through a deterministic priority tree, then retrieves answers from two sources: a local ChromaDB vector store backed by HuggingFace sentence embeddings, and a structured JSON knowledge base scraped from CSULB's website. There's no LLM in the primary path — everything is deterministic retrieval plus rule-based extraction, which gives zero inference cost and predictable behavior. The advisor lookup uses fuzzy string matching with RapidFuzz, email drafts are generated via templates and encoded as Outlook deep-links, and user progress through application checklists is tracked in JSON session files with dependency-aware blocking."

### 2-Minute System Design Walkthrough
"The system has 10 layers. At the top is a Streamlit UI with a custom CSULB-branded CSS theme. User queries go to an orchestrator that runs a 9-branch priority tree — it checks for deadline signals, eligibility signals, process+program signals, advisor signals, start-intent, and then falls back to 4 base routes: guidance, checklist, answer, and tracking.

For the RAG stack: I built a persistent ChromaDB store using LangChain wrappers and HuggingFace's all-MiniLM-L6-v2 embeddings. Pages are scraped from CSULB using BeautifulSoup, chunked at 500 chars with 75-char overlap, and stored with rich metadata including page_type and workflow_priority. I built a web crawler (rag/discovery.py) that auto-classifies each doctoral program's application pages into 8 content categories, which drives program-specific retrieval. The deadlines page gets a specialist parser that extracts one structured card per program to avoid cross-program chunk contamination.

The advisor layer uses RapidFuzz fuzzy matching with a threshold hierarchy: 90 for confirmed match, 70 for suggestions, and an ambiguity check when two programs score within 11 points of each other. Email drafts are template-based, URL-encoded for Outlook Web.

Progress tracking uses a file-based session store with dependency graphs validated for cycles via DFS. Each step has depends_on IDs, and the tracker annotates blocked steps at query time.

The one genuinely agentic component is a legacy OpenAI agent.py that uses GPT-4o-mini function calling — but it's not wired to the current UI. The plan is to replace it with a local Ollama model."

### Technical Highlights
- ChromaDB persistent vector store with 24h TTL and self-healing logic (detects stale store missing program_application chunks and triggers rebuild)
- Web discovery crawler with content-signal classifier producing `workflow_priority` metadata used for retrieval ranking
- Dependency-aware checklist tracker with DFS cycle detection
- Application bullet extraction pipeline with 20+ regex noise filters distinguishing actionable application content from marketing copy and course descriptions

### AI Highlights
- Dual-path retrieval: persistent ChromaDB (24h TTL) for deadlines/eligibility/application + ephemeral in-memory Chroma (1h TTL) for FAQs
- Cosine similarity scoring with per-domain threshold tuning (0.25 for deadlines tables, 0.30 default, 0.42 for deadline card confidence)
- Program-specificity detection via `workflow_priority` metadata — generically handles any future program without code changes
- Confidence scoring propagated through the answer pipeline to the UI

### Backend / Distributed Systems Highlights
- Process-level singleton pattern for embedding model and Chroma store (avoids re-loading 2–5s model on each Streamlit rerun)
- TTL-based cache invalidation using OS file mtime (robust across process restarts unlike `time.monotonic()`)
- Chunk ID scheme: `{md5(url)[:8]}_{index:04d}` — stable across rebuilds, filesystem-safe, sort-preserving
- `_store_has_program_pages()` guard: O(1) `limit=1` ChromaDB check to self-heal stale in-memory stores

---

## 13. GAP ANALYSIS + HIGH ROI NEXT STEPS

### Easiest Improvements

| # | Improvement | Effort | Status |
|---|---|---|---|
| 1 | Add `@st.cache_resource` to `get_or_build_store()` to prevent re-loads on Streamlit re-renders | 2 lines | [PLANNED/RECOMMENDED] |
| 2 | Add `@st.cache_data(ttl=3600)` to `faq_rag_lookup()` to prevent per-query FAQ rebuilds | 2 lines | [PLANNED/RECOMMENDED] |
| 3 | Replace `print()` with `logging.getLogger(__name__)` throughout `rag/` | Low effort | [PLANNED/RECOMMENDED] |
| 4 | Add a `OPENAI_API_KEY` check guard in `agent.py` so it fails gracefully if key is absent | 3 lines | [PLANNED/RECOMMENDED] |
| 5 | Add `st.spinner("Searching...")` during RAG calls to improve perceived UX | 2 lines | [PLANNED/RECOMMENDED] |

### Most Impressive Additions

| # | Improvement | Value | Status |
|---|---|---|---|
| 1 | Wire Ollama `qwen2.5:7b` (already in `requirements.txt`) for answer synthesis on low-confidence extractors | LLM reasoning at zero API cost | [PARTIALLY IMPLEMENTED] — dependency present, not wired |
| 2 | Hybrid retrieval: BM25 + dense vector reranking for better precision on keyword-heavy queries | Higher retrieval quality | [PLANNED/RECOMMENDED] |
| 3 | Add embedding-based fallback for advisor lookup (catches paraphrases `rapidfuzz` misses) | Better advisor matching | [PLANNED/RECOMMENDED] |
| 4 | Replace `faq_rag_module.py` in-memory store with the persistent `chroma_db/` store | Eliminates 5-10s cold-start delays | [PLANNED/RECOMMENDED] |
| 5 | Latency telemetry per route (`time.perf_counter()` + Streamlit metric) | Observable system | [PLANNED/RECOMMENDED] |

### Production-Grade Improvements

| # | Improvement | Status |
|---|---|---|
| 1 | Replace `sessions/*.json` with SQLite (`sqlite3` stdlib) for ACID writes | [PLANNED/RECOMMENDED] |
| 2 | Add `asyncio`/`aiohttp` to `ingest_pages()` for parallel page fetching | [PLANNED/RECOMMENDED] |
| 3 | Thread-safe ChromaDB access (single writer queue) | [PLANNED/RECOMMENDED] |
| 4 | Docker container + `requirements.txt` pinning for reproducible deploys | [PLANNED/RECOMMENDED] |
| 5 | Background rebuild job (APScheduler or Celery) for daily store refresh | [PLANNED/RECOMMENDED] |
| 6 | Remove `openai` dependency (Phase 7 per `requirements.txt` comment) | [PARTIALLY IMPLEMENTED] — planned |

### LinkedIn-Worthy Improvements

| # | Improvement | Why It Stands Out |
|---|---|---|
| 1 | Implement Ollama local LLM for answer generation | "Zero-cost RAG + LLM pipeline running entirely on local hardware" |
| 2 | Add eval harness: golden Q&A pairs per route, automated precision/recall scoring | Shows ML rigor |
| 3 | Export session checklists as PDF | Practical student feature |
| 4 | Add a "What changed since last visit" feature using store TTL comparison | Novel use of existing TTL infrastructure |
| 5 | Multi-session comparison dashboard (completion rates across sessions) | Data engineering angle |

### Interview-Worthy Improvements

| # | Improvement | Interview Talking Point |
|---|---|---|
| 1 | Replace `query_handler.rank_files()` keyword scoring with dense retrieval across all `data/*.json` | "Unified dense retrieval pipeline replacing two separate retrieval systems" |
| 2 | Expose `orchestrator.run()` as a FastAPI endpoint | "RESTful API design, separation of concerns, production-ready architecture" |
| 3 | Multi-turn conversation state in orchestrator (not just tracker) | "Stateful dialog management beyond single-turn routing" |
| 4 | Implement LLM-as-judge for answer quality scoring | "Automated evaluation loop with LLM-as-evaluator" |
| 5 | Add citation spans: highlight which exact sentence in the source chunk grounded the answer | "Grounding + faithfulness in RAG systems" |

---

**Key files referenced:**
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/app.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/orchestrator.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/guidance_agent.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/answer_agent.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/query_handler.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/advisor_retrieval.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tracker.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/agent.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/faq_rag_module.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/next_steps.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tools/deadlines_tool.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tools/eligibility_tool.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tools/application_steps_tool.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tools/advisor_tool.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tools/email_tool.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/tools/program_interest_tool.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/rag/store.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/rag/retriever.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/rag/ingestion.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/rag/chunking.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/rag/discovery.py`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/requirements.txt`
- `/Users/sushmithavijayakumar/Documents/ClaudeCode/GradCenterAgenticAIAssistant/sessions/default.json`