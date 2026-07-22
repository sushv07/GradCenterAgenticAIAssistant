# Phase P9 — Comparative Analysis: Track A (Pure RAG) vs Track B (Fine-Tuned)

## Executive summary

On an identical 84-case frozen benchmark scored by one unchanged pipeline, Pure RAG (Track A) reached 0.4576 answer accuracy versus 0.0678 for Fine-Tuned-Only (Track B), and hallucinated on 16% of source-missing cases versus 100% for Track B. Track A wins every category. The gap is driven by retrieval grounding and evidence-aware abstention, while Track B — a LoRA over 121 examples with no retrieval — overfit and degenerated. Recommendation for Track C: keep RAG as the knowledge source and abstention mechanism; use fine-tuning (if any) only to shape faithful answer/refusal formatting on top of retrieved context, never to store facts.

- benchmark: eval-v1 · checksum `sha256:e6f4145c91f18…`
- consistency: same benchmark for both = True; both reproduce frozen reports = True

## Overall metric comparison

| metric | Track A | Track B | Δ (B−A) | Δ% | preferable |
| --- | --- | --- | --- | --- | --- |
| answer_accuracy | 0.4576 | 0.0678 | -0.3898 | -85.2% | track_a |
| completeness | 0.4576 | 0.0678 | -0.3898 | -85.2% | track_a |
| hallucination_rate | 0.16 | 1.0 | 0.84 | 525.0% | track_a |
| unsupported_claim_rate | 0.25 | 0.9467 | 0.6967 | 278.7% | track_a |
| refusal_rate | 0.5714 | 0.1071 | -0.4643 | -81.3% | context |
| abstention_accuracy | 0.84 | 0.0 | -0.84 | -100.0% | track_a |

## Operational comparison

| metric | Track A | Track B | Δ (B−A) |
| --- | --- | --- | --- |
| avg_latency_ms | 3410.016 | 25576.417 | 22166.401 |
| p50_latency_ms | 2560.733 | 13464.711 | 10903.978 |
| p95_latency_ms | 6219.075 | 20921.833 | 14702.758 |

> Latencies are NOT a like-for-like runtime comparison: Track A generation runs on Ollama (qwen2.5:7b-instruct) and Track B on Apple MLX (Qwen2.5-7B-Instruct-4bit). Track B also includes MLX first-call/tail stalls under 16 GB memory pressure. Read latency as indicative only.

## Category comparison

| category | n | Track A | Track B | winner |
| --- | --- | --- | --- | --- |
| admissions | 5 | 1.0 | 0.0 | track_a |
| application | 12 | 0.3333 | 0.0833 | track_a |
| contact | 12 | 0.4167 | 0.0 | track_a |
| multi_field | 8 | 0.375 | 0.0 | track_a |
| overview | 12 | 0.6667 | 0.25 | track_a |
| retrieval_challenge | 10 | 0.2 | 0.0 | track_a |
| source_missing | 13 | 0.6923 | 0.0 | track_a |
| unknown | 12 | 1.0 | 0.0 | track_a |

## Failure-mode comparison

- Track A counts: {'abstention_error': 31, 'hallucination': 4, 'incorrect_answer': 5, 'incorrect_citation': 59, 'missing_citation': 31, 'retrieval_failure': 29}
- Track B counts: {'hallucination': 25, 'incorrect_answer': 46, 'over_refusal': 9}

Track B failure modes:

- Degenerate repetition — answers loop the same fragment (e.g. 'don have the provided, don have the provided …') up to the 256-token cap.
- Refusal collapse — the model echoes a corrupted paraphrase of its trained refusal ('I don't have the provided <program> data to answer that') even for answerable questions, without stating the actual fact.
- Fabricated tokens — invented emails/date codes (e.g. 'ced-2011-01-01') and spurious identifiers appear in place of grounded content.
- Over-refusal on answerable cases (9) and failure to cleanly abstain on source_missing cases (hallucination_rate 1.0) — the trained refusal behaviour did not generalise.

Representative Track B failures:

- EVAL-001 (incorrect_answer): I don't have the provided information in the provided, that is,I don have the provided,I don have a 1, don have a 1 in the provided, don have a , don have a 1 i
- EVAL-002 (incorrect_answer): I don't have the provided Art (2011-12) to answer that.
- EVAL-004 (incorrect_answer): I don't have the provided Early Center data to answer that.
- EVAL-005 (incorrect_answer): I don't have the provided, don have the provided, don have the, don have the provided, don have the provided, don have the provided, don have the provided, that

## Root cause analysis

- **Track A is ~6.7x more accurate on answerable questions (0.458 vs 0.068).**
  - cause: Retrieval grounding. Track A conditions generation on the frozen corpus chunks, so when retrieval surfaces the right chunk the model copies published wording. Track B must recall facts from a 121-example LoRA and has no text to ground on.
  - evidence: answer_accuracy 0.4576 vs 0.0678; Track A wins every category.
- **Track B fabricates on 100% of source-missing cases; Track A only 16%.**
  - cause: The trained refusal did not generalise and, absent retrieved context, Track B has no signal that evidence is missing. Track A sees empty/low-similarity retrieval and abstains.
  - evidence: hallucination_rate 1.0 (B) vs 0.16 (A); abstention_accuracy 0.0 vs 0.84.
- **Track B output is degenerate (repetition, corrupted refusals, fabricated tokens); unsupported-claim rate 0.947.**
  - cause: Overfitting/instability from P8.1: at LR 1e-4 on 121 examples the validation loss minimised at iter 40 then diverged. LoRA on a tiny SFT set degraded fluency rather than adding knowledge.
  - evidence: unsupported_claim_rate 0.9467; P8.1 val-loss curve 1.018@40 -> 5.338@200; representative answers loop 'don have the provided…'.
- **Track A's main weakness is over-abstention, not fabrication.**
  - cause: Retrieval recall is the ceiling: when the right chunk is not in top-k, Track A abstains (safe failure) rather than answer.
  - evidence: refusal_rate 0.5714 with abstention_error=31 and retrieval_failure=29; hallucination only 0.16.

## Track A — Pure RAG

**Strengths**
- High factual accuracy when retrieval hits (0.458 answerable, wins every category).
- Safe failure mode: abstains instead of fabricating (abstention_accuracy 0.84, hallucination 0.16).
- Fluent, grounded answers with citable chunks; no catastrophic degeneration.
- Knowledge is swappable — update the corpus/index without retraining.

**Weaknesses**
- Over-abstains when retrieval misses (refusal_rate 0.571; 31 answerable abstentions).
- Citation precision is imperfect (incorrect_citation=59: extra/irrelevant chunks retrieved).
- Accuracy bounded by retrieval recall (retrieval_challenge only 0.20).

**Best use cases**
- Factual Q&A over a maintained knowledge base where correctness and abstention matter more than coverage.
- Domains with frequently changing source content.

**Limitations**
- Depends on embedding quality, chunking, and top-k threshold.
- No parametric domain adaptation; style is the base model's.

## Track B — Fine-Tuned Only

**Strengths**
- Answers more answerable questions without abstaining (50/59 attempted vs 32/59).
- No retrieval infrastructure needed at inference (self-contained weights).
- Occasionally surfaces the right token (overview 0.25) — some signal was learned.

**Weaknesses**
- Very low accuracy (0.068) and completeness; near-total unsupported claims (0.947).
- Fabricates on all source-missing cases (hallucination 1.0; abstention 0.0).
- Degenerate generation: repetition, corrupted refusals, invented emails/dates.

**Best use cases**
- On the current 121-example dataset: none for production factual Q&A.
- Potentially style/format adaptation if paired with grounding (see hybrid).

**Limitations**
- Tiny SFT set + aggressive LR overfit; selected checkpoint still under-fits QA.
- No grounding signal, so cannot know when to abstain.

## Hybrid design insights (for Track C)

**Inherit from Track A**
- Retrieval grounding as the primary knowledge source — it drives the 6.7x accuracy advantage and enables evidence-aware abstention.
- The abstain-when-evidence-is-missing behaviour (Track A hallucination 0.16 vs Track B 1.0).
- Citations tied to retrieved chunks for verifiability.

**Inherit from Track B**
- Only lightweight, format/behaviour-oriented fine-tuning — NOT knowledge injection. Any adapter must be trained to consume retrieved context, not to memorise facts.
- If used at all, fine-tune for refusal formatting and answer style on top of retrieved evidence.

**Weaknesses Track C should solve**
- Track A over-abstention on answerable questions (recover the 31 answerable abstentions via better recall / higher-k / query expansion).
- Track A imperfect citation precision (incorrect_citation=59).
- Track B degeneration and fabrication — eliminated by grounding generation on retrieved context and training the adapter WITH context in the prompt.
- Never repeat P8.1's overfitting: more data, lower LR, and validation-based early stopping if any fine-tuning is done.

**Recommended Track C shape**

RAG-first pipeline (Track A retrieval + prompt) with an OPTIONAL small LoRA trained on (retrieved-context -> grounded-answer/refusal) pairs — retrieval supplies facts, the adapter only shapes faithful formatting and abstention. Fine-tuning must never be the knowledge store.

## Threats to validity

- Small supervised dataset (121 train / 13 val) — Track B is data-starved; results may not reflect fine-tuning with a larger, cleaner SFT set.
- Single institution (CSULB Graduate Center) and a single base-model family (Qwen2.5-7B).
- Different inference runtimes per track (Ollama for A, Apple MLX 4-bit for B) — latency is not directly comparable and quantization differs.
- Deterministic substring/set scoring, not an LLM judge — can both under- and over-credit answers (e.g. Track B 'successes' are substring coincidences).
- Benchmark is 84 cases over 12 programs; category cells are small (n=5–13).
- Single official run per track (greedy); no seed/variance sweep.
- Track B hyperparameters were fixed by P8.1, not tuned — a different LR/size could change Track B's absolute numbers (though not the grounding conclusion).

## Conclusions

**Primary findings**
- Pure RAG (Track A) decisively outperforms fine-tuned-only (Track B) on this benchmark: 0.458 vs 0.068 answer accuracy, winning all 8 categories.
- The decisive factor is retrieval grounding, not model size — both use a 7B Qwen2.5 base.
- Fine-tuning on 121 examples injected almost no reliable knowledge and degraded generation quality.

**Surprising findings**
- Track B did not merely under-perform — it catastrophically degenerated (repetition, fabricated tokens), showing tiny-dataset LoRA can harm a strong instruct model rather than gently under-fit.
- Track B abstained LESS (0.107) yet was far less accurate — it answered confidently and wrongly, the opposite of the safe RAG failure mode.

**Practical implications**
- For factual assistants over a maintained corpus, invest in retrieval quality before fine-tuning.
- Use fine-tuning for behaviour/format on top of retrieval, not as a knowledge store.
- Evidence-aware abstention is a first-class safety property that RAG provides and fine-tuning-only did not.

**Lessons learned**
- Match learning rate and dataset size to avoid overfitting (P8.1 val loss diverged after iter 40).
- Always evaluate abstention/hallucination, not just accuracy — the tracks differ most there.
- Keep a frozen benchmark + one scoring pipeline so cross-condition comparison is exact (both tracks reproduced their frozen reports).
