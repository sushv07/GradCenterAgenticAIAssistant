# Phase 10 — Answer-Generation Layer: Design Review

Audit of how the system turns retrieved content into a user-facing answer, with
no code changed during the review. Retrieval (acquisition, crawling, chunking,
embeddings, Chroma, ranking, the retrieval eval framework) is explicitly out of
scope; this review covers only the answer layer.

## 1. The answer path, end to end

The `answer` route (`orchestrator._run_answer`) runs three stages:

1. **Retrieve** — `retrieval.query_handler.handle_query(query)` returns a dict of
   result blocks (structured JSON knowledge) plus `next_steps`.
2. **Deterministic extraction** — `agents.answer_agent.answer()` walks the top
   result block with an ordered set of rule-based extractors (steps, amounts,
   eligibility, contact, programs, deadlines; FAQ first-pass; generic fallback),
   producing `{answer, answer_type, source_file, source_url, confidence,
   next_steps}`. **No LLM.**
3. **Optional LLM synthesis** — `agents.llm_synthesizer.synthesize_answer()`
   (Ollama, **off by default**, `LLM_SYNTHESIS_ENABLED`). On success it replaces
   `answer`/`confidence` with a synthesized version; on any failure it returns
   `None` and the deterministic answer stands.

Presentation is `orchestrator._humanize_answer` → `responses.builder.build_response`.

### How each concern is handled today

| Concern | Current behavior | Location |
|---|---|---|
| Chunk assembly | Entire retrieved dict serialized to JSON; `canonical_source_url` prepended | `llm_synthesizer._build_context` |
| Prompt | Single system prompt, priority **Accuracy > Completeness > … > Brevity**; "You are NOT a summarizer" | `prompts/grounded_answers/synthesis_v1.md` |
| Citations | Deterministic single `source_url` (first http source in block, else hardcoded fallback); LLM-fabricated URLs rejected | `answer_agent._resolve_source_url`, `llm_synthesizer._validate` |
| Confidence | Rule heuristic (faq→high, list/table→high, direct→token overlap); LLM may set its own; presentation maps to advice sentence | `answer_agent._score_confidence`, `_humanize_answer` |
| Missing info | Empty results → "I don't know"; prompt tells LLM to state coverage + set confidence low | `answer_agent.answer`, prompt line 35 |
| Conflicting evidence | **Not handled** — no detection/reconciliation | — |
| Ambiguity / clarification | Answer route has **no clarification path** (only topic-tools disambiguate programs) | — |

## 2. Findings (where quality is at risk)

**F1 — Verbosity is a designed-in bias.** The v1 prompt ranks Brevity last,
says "You are NOT a summarizer," and "do not omit … for brevity." Combined with
dumping the full retrieved JSON as context, synthesized answers trend long and
can bury the actual answer under preserved-but-unasked detail.

**F2 — No conflict handling.** If two retrieved blocks disagree (e.g. two GPA
minimums from different pages), the prompt's "preserve all" rule concatenates
both without flagging the discrepancy or preferring the canonical source. The
user sees a contradiction with no signal.

**F3 — No clarification on ambiguity.** When a query matches multiple programs
or policies ("what's the deadline for the MA?" with many MAs), the layer answers
from the top block instead of asking which program. There is no mechanism to
emit a clarifying question on the answer route.

**F4 — Hallucination surface is URL-only.** `_validate` guarantees no fabricated
**URLs**, which is excellent. But fabricated **numbers, dates, names, or
requirements** are not checked against the evidence — the prompt asks for
grounding but nothing enforces it for non-URL facts.

**F5 — Single-source citation.** Only one `source_url` is surfaced even when the
answer legitimately draws on multiple pages, and `_resolve_source_url` picks the
first http link in the block rather than the one most relevant to the answer —
so a multi-fact answer can cite a tangential page.

**F6 — Confidence is not evidence-calibrated.** The deterministic score is a
token-overlap proxy; when the LLM is enabled it may assert "high" regardless of
how well the evidence covers the question. Weak-evidence answers are not reliably
marked low.

## 3. What this phase changes (and what it deliberately does not)

Improvements target the **prompt** and add a **deterministic answer-quality
evaluation suite**, following the repo's established idioms (versioned prompt
registry, config-over-code toggles, deterministic no-LLM-judge evals):

- **`synthesis_v2` prompt** (F1–F4, F6): concise-but-faithful reordering,
  explicit conflict-surfacing, an ambiguity→clarification instruction, an
  evidence-first grounding rule for every factual claim, and a stricter
  abstention/low-confidence contract for missing information.
- **Config-selectable active prompt** (`GROUNDED_ANSWER_PROMPT`, default v1) —
  zero runtime change until an operator opts in, matching `LLM_SYNTHESIS_ENABLED`
  / `MASTERS_INGESTION_ENABLED`.
- **`evals/` answer-quality suite** — deterministic metrics (grounding,
  citation correctness, hallucinated-URL count, verbosity, repetition,
  abstention, clarification) over a golden set spanning admissions, eligibility,
  deadlines, program-specific, advisor, unknown, and ambiguous questions, with
  before/after answer fixtures.

**Not changed:** the retriever, embeddings, chunking, Chroma, ranking, the
retrieval eval framework, and the deterministic URL-fidelity guard (kept as-is —
it is the one hard guarantee and is already correct). The existing Phase 7D
`run_llm_evals` harness and its dataset are left untouched.

### Honest limitation

The synthesized-answer path requires a live Ollama model, which is unavailable
in the offline test/eval environment (the same reason `run_llm_evals` has no
`--live` mode). The new suite therefore scores answer **properties** on
representative before/after fixtures — it demonstrates what v2 targets and gives
reproducible metrics, but it is not a live-model A/B. A live A/B is documented
future work.
