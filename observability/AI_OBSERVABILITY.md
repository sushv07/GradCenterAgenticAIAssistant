# AI Observability (Phase 3)

Phase 1 gave us structured NDJSON logs; Phase 2 added OpenTelemetry traces + Prometheus
RED metrics + Tempo + Grafana, all as Infrastructure-as-Code. **Phase 3 makes the
*reasoning and retrieval behavior* of the assistant observable** — not just the
infrastructure — using the same three-signal spine.

Nothing about routing, retrieval, or recommendation logic changed. Every metric and
trace attribute is recorded at an **existing seam** (the same points that already emit
NDJSON events), so the AI signals are a parallel view of the pipeline, never a fork of it.

- **Metrics** (`telemetry/metrics.py`) → Prometheus, scraped from `/metrics`.
- **Trace attributes** (`telemetry/tracing.py` spans) → Tempo, one span tree per request.
- **Logs** (`gradcenter_logging.emit`) → unchanged; correlated to traces by `trace_id`.

> **Run the stack:** `docker compose --profile observability up`
> Grafana `:3000` (dashboards auto-provisioned) · Prometheus `:9090` · Tempo `:3200`.

---

## 1. Metrics

All AI metrics are prefixed `ai_`, use base unit **seconds**, `_total` for counters, and
**only bounded labels** (high-cardinality detail lives in logs/traces). Route *distribution*
deliberately reuses the Phase-1 `pipeline_requests_total{route}` — no duplicate series.

### Routing
| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `ai_routing_duration_seconds` | Histogram | — | Latency of `decide_route()`. Sub-ms normally; a spike ⇒ routing regression. |
| `pipeline_requests_total` *(Phase 1)* | Counter | `route`, `outcome` | **Route distribution / rates** (answer, discovery, advisor, …) and success/error. |

*Routing confidence:* the router returns a categorical `reason`, not a numeric score, so it
is exposed as the **`route.reason` span attribute** rather than a metric (no numeric confidence exists).

### Retrieval (Chroma vector retriever)
| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `ai_retrieval_duration_seconds` | Histogram | — | Retrieval call latency. |
| `ai_retrieval_requests_total` | Counter | `outcome` (`hit`/`empty`/`error`) | Success/fallback/error. `empty` = nothing cleared the threshold. |
| `ai_retrieval_documents` | Histogram | — | # docs returned (post-threshold). Avg = `_sum/_count`. |
| `ai_retrieval_top_score` | Histogram | — | Best relevance score per call. |
| `ai_retrieval_score` | Histogram | — | One observation per returned doc → **avg = mean relevance**. |
| `ai_retrieval_source_total` | Counter | `page_type` | Source distribution (faq/deadlines/eligibility/application_process/program_application/unfiltered). |

- **Retrieval success rate** = `hit / (hit+empty+error)`; **no-result rate** = `empty / total`;
  **fallback usage** ≈ `empty` (tools fall back when retrieval is empty).

### Recommendation engine
| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `ai_recommendation_duration_seconds` | Histogram | — | `select_recommendation()` latency. |
| `ai_recommendation_behavior_total` | Counter | `behavior` | recommend / multi_recommend / partial_match_with_caveat / clarify / redirect. **Clarification frequency = clarify share.** |
| `ai_recommendation_candidates` | Histogram | — | # candidate programs surfaced. |
| `ai_recommendation_confidence_total` | Counter | `confidence` | high / medium / low / none distribution. |
| `ai_recommendation_explanation_total` | Counter | `outcome` | `generated` / `no_evidence` / `failed` / `disabled`. **Explanation generation rate**; `disabled` shows would-be demand while the LLM flag is off. |

### Answer generation
| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `ai_answer_duration_seconds` | Histogram | — | Answer-route retrieve+extract(+synthesis) latency. |
| `ai_answer_total` | Counter | `answer_type`, `confidence` | direct (deterministic) vs `llm_synthesized` vs `unknown` (insufficient evidence / fallback). |

- **Deterministic vs synthesized** = `answer_type=direct` vs `llm_synthesized`.
- **Insufficient-evidence / fallback rate** = `answer_type=unknown` share.

### LLM (framework — stays instrumented even while synthesis/explanation is disabled)
| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `ai_llm_requests_total` | Counter | `model`, `operation` (`synthesis`/`explanation`), `outcome` (`success`/`error`) | Success/failure rate per model & call type. |
| `ai_llm_duration_seconds` | Histogram | `model`, `operation` | Generation latency. |
| `ai_llm_errors_total` | Counter | `operation`, `error_type` | Failures; **timeout count = `error_type` matching `*Timeout*`**. |
| `ai_retry_attempts_total` | Counter | `operation` | Retry attempts (from `utils.retry.retry_call`). |
| `ai_retry_exhausted_total` | Counter | `operation` | Retries exhausted (persistent outage proxy). |

*Prompt version* is a **span attribute** (`prompt.version`), not a metric label, to avoid cardinality.

---

## 2. Trace attributes (why-this-answer)

Attached to the **root `pipeline.request` span** (and stage spans) so a single trace explains
the outcome. Set at the seam where each value becomes known.

| Attribute | Span | Source |
|---|---|---|
| `route`, `session.id`, `query.len`, `pipeline.error` | `pipeline.request` | entrypoint |
| `route.selected`, `route.reason` | `route.decide` | router |
| `retrieval.k`, `retrieval.min_score`, `retrieval.hits`, `retrieval.top_score`, `retrieval.empty` | `rag.retrieve` | retriever |
| `db.system`, `db.k_requested`, `db.filtered` | `vectordb.query` | retriever |
| `recommendation.behavior`, `recommendation.candidates` | `pipeline.request` | journey_agent |
| `answer_type`, `confidence`, `source_file`, `answer.synthesized` | `pipeline.request` | `_run_answer` |
| `llm.model`, `prompt.version`, `program.id` | `llm.generate` | synthesizer / explainer |
| `composite`, `intents.count`, `plan.halted`, `agent.name`, `sections.count` | coordinator spans | coordinator/executor/synthesizer |

Every NDJSON log line inside a request also carries `trace_id` + `span_id` (Phase 2 enricher),
so you can pivot log → trace in Grafana.

---

## 3. Dashboards (auto-provisioned)

`observability/grafana/dashboards/`:

- **GradCenter — Service Health** (Phase 1): RED, latency percentiles, in-flight.
- **GradCenter — AI Pipeline** (Phase 3): rows for
  - **Routing** — distribution (pie), rate, decision latency.
  - **Retrieval** — latency p50/95/99, outcomes, no-result rate, avg top/relevance score, docs & source mix.
  - **Recommendation** — behavior mix, confidence pie, explanation outcomes.
  - **Answer** — answer types, insufficient-evidence rate, confidence mix.
  - **LLM** — success/error, latency p95, errors & retries.
  - **End-to-end** — stage latency p95 overlay (routing/retrieval/recommendation/answer/llm vs total) to attribute where time goes.

---

## 4. Alerts

`observability/prometheus/alerts.yml` (loaded via `rule_files`; visible in Prometheus/Grafana,
no paging provisioned — a deliberate demo scope). Thresholds are starting points.

| Alert | Fires when | Area |
|---|---|---|
| `HighRetrievalFailureRate` | retrieval `error` rate > 5% for 10m | retrieval |
| `ElevatedEmptyRetrievalRate` | `empty` rate > 40% for 15m | retrieval |
| `ElevatedClarificationRate` | discovery `clarify` share > 60% for 15m | recommendation |
| `ExcessiveInsufficientEvidence` | answer `unknown` share > 30% for 15m | answer |
| `LLMErrorSpike` | LLM `error` rate > 20% for 10m | llm |
| `AbnormalPipelineLatencyP95` | pipeline p95 > 10s for 10m | latency |

---

## 5. Debugging with AI observability

- **"Answers feel wrong / generic."** Check *Retrieval quality* (avg top/relevance score) and
  *no-result rate*, plus `ai_answer_total{answer_type="unknown"}`. Rising empty/unknown ⇒ KB
  coverage/drift — cross-check `kb_drift` / `kb_health`. Open a slow/failed trace and read
  `retrieval.hits` / `retrieval.top_score` on `rag.retrieve`.
- **"Requests are slow."** *End-to-end stage latency* panel: whichever stage's p95 tracks the
  pipeline p95 is the culprit (usually `llm`). Confirm on a trace — the `llm.generate` span
  dominates. `ai_retry_attempts_total` rising ⇒ Ollama flaky.
- **"Users never get a recommendation."** *Recommendation behavior* — a high `clarify` share
  means signal extraction isn't producing matches; `ai_recommendation_candidates` avg ~0 confirms.
- **"Enabled the LLM but nothing happens."** `ai_llm_requests_total` stays flat ⇒ the call
  isn't reached; `ai_recommendation_explanation_total{outcome="disabled"}` rising ⇒ flag off in
  the serving process; `outcome="no_evidence"` ⇒ matches lack `score_basis`. If `error`/retries
  climb, Ollama is unreachable (`ai_llm_errors_total` `error_type` tells Timeout vs Connection).
- **Pivot to a single request.** In Grafana Explore → Tempo, search by route/latency, open the
  trace, read the `pipeline.request` attributes (`route`, `answer_type`, `confidence`,
  `retrieval.hits`, `top_score`, `recommendation.behavior`, `source_file`, `llm.model`) — that
  span alone explains *why* the assistant produced its answer. Use its `trace_id` to grep the
  NDJSON log for full detail.
