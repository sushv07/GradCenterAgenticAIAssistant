# Final Conclusions — RAG vs Fine-Tuning vs Hybrid

*CSULB Graduate Center assistant · experiment `experiments/rag_vs_finetuning/` ·
concluding phase P12. This chapter synthesizes the completed, frozen experiment;
it introduces no new training, inference, evaluation, or implementation.*

---

## 1. Project overview

**Problem statement.** Build a factual assistant for the CSULB Graduate Center
master's programs and determine, under controlled conditions, whether **retrieval
(RAG)**, **small-data LoRA fine-tuning**, or their **hybrid** best answers program
questions grounded in official content.

**Motivation.** RAG and fine-tuning are routinely proposed as interchangeable
paths to domain adaptation. When institutional knowledge is factual and updatable
and the supervised dataset is small, teams need evidence — not folklore — on which
to invest in.

**Research questions.**
1. Does Pure RAG perform well on grounded factual QA?
2. Can small-data LoRA fine-tuning replace retrieval as the knowledge source?
3. Does a Hybrid (RAG + fine-tuned adapter) improve over Pure RAG?
4. What role does retrieval grounding play relative to model weights?
5. When is fine-tuning the appropriate tool?

**Goals.** One frozen corpus, one frozen 84-case benchmark, and one evaluation
pipeline shared by all tracks; three controlled conditions (A = Pure RAG,
B = Fine-Tuned-only, C = Hybrid); reproducible, checksum-guarded artifacts.

**Experimental design.** A between-tracks comparison holding the corpus,
benchmark, scoring, and 7B base-model family constant. Track A grounds a base
model on retrieved chunks; Track B fine-tunes a LoRA adapter with no retrieval;
Track C reuses Track A retrieval plus the Track B adapter. Deterministic greedy
decoding; deterministic substring/set scoring (no LLM judge).

## 2. Methodology

| Component | Choice |
| --- | --- |
| Knowledge corpus | Frozen canonical records for 12 master's programs (source-guarded) |
| Chunking | Deterministic section-level → **41 chunks** |
| Embeddings | `all-MiniLM-L6-v2` (normalized, CPU) |
| Retrieval | Chroma `masters_track_a_v1`, cosine, **top_k=4, threshold=0.0** |
| Fine-tuning | MLX-LM LoRA on `Qwen2.5-7B-Instruct-4bit`; rank 16, 16 layers, LR 1e-4, 200 iters; **best checkpoint = iter 40** (val loss 1.018); 23.069M params (0.303%) |
| SFT dataset | **121 train / 13 val** (seed-42), built from the corpus only (no benchmark leakage) |
| Benchmark | **84 cases**, 8 categories, answerable + source-missing |
| Evaluation | Track-agnostic `ResponseRecord` scoring: accuracy, hallucination/abstention, citation & retrieval precision/recall, derived refusal/unsupported/completeness, latency — **identical across A/B/C** |

Each track's recompute reproduced its frozen report **exactly**, on the same
benchmark checksum, so the comparison is apples-to-apples.

## 3. Final experimental findings

### Headline metrics (frozen)

| Metric | Track A (RAG) | Track B (FT) | Track C (Hybrid) |
| --- | --- | --- | --- |
| Answer accuracy | **0.4576** | 0.0678 | 0.0169 |
| Completeness | 0.4576 | 0.0678 | 0.0169 |
| Hallucination rate | **0.16** | 1.00 | 1.00 |
| Abstention accuracy | **0.84** | 0.00 | 0.00 |
| Refusal rate | 0.5714 | 0.1071 | 0.0000 |
| Unsupported-claim rate | **0.25** | 0.9467 | 0.9881 |
| Citation precision | 0.1525 | 0.00 | 0.161 |
| Citation recall | 0.5254 | 0.00 | 0.5593 |
| Retrieval recall@k | 0.5593 | n/a | 0.5593 |

### Track A — Pure RAG

- **Purpose.** Retrieval-grounded baseline.
- **Architecture.** question → embed → Chroma top-k → grounded prompt → base LLM →
  answer + citations; refuses when no evidence is retrieved.
- **Strengths.** Highest accuracy (0.4576) and **wins all 8 categories**; safe
  failure mode (abstains rather than fabricates: hallucination 0.16, abstention
  accuracy 0.84); fluent grounded answers with citable chunks; knowledge is
  swappable without retraining.
- **Weaknesses.** Over-abstains when retrieval misses (refusal 0.5714; 31
  answerable abstentions, 29 retrieval failures); imperfect citation precision
  (59 incorrect-citation cases); accuracy bounded by retrieval recall
  (`retrieval_challenge` 0.20).
- **Key finding.** Retrieval grounding produces correct, safely-abstaining
  answers; **retrieval recall (0.5593) is the ceiling.**

### Track B — Fine-Tuned only

- **Purpose.** Test whether small-data LoRA can serve as the knowledge store.
- **Architecture.** question → base + Track B LoRA → answer (parametric knowledge
  only, no retrieval).
- **Strengths.** No retrieval infrastructure at inference; attempts more
  answerable questions (50/59) — but confidently and wrongly.
- **Weaknesses.** Very low accuracy (0.0678); unsupported-claim rate 0.9467;
  **fabricates on 100% of source-missing cases** (abstention 0.0); degenerate
  generation (repetition, corrupted refusals, invented tokens like `ced-2011-01-01`).
- **Key finding.** A 121-example LoRA **injected no reliable knowledge and
  degraded fluency** (validation loss diverged after iter 40). Fine-tuning did not
  replace retrieval.

### Track C — Hybrid (RAG + fine-tuned adapter)

- **Purpose.** Combine Track A retrieval with the Track B adapter.
- **Architecture.** question → frozen Track A retrieval → grounded prompt → base +
  Track B LoRA → answer + citations; empty-retrieval abstains.
- **Strengths.** Restores grounding and citations lost in Track B (citation recall
  0 → 0.5593); receives the **same retrieved evidence as Track A** (retrieval
  recall 0.5593).
- **Weaknesses.** **Lowest accuracy (0.0169) — below even Track B**; hallucination
  1.0; never abstains (refusal 0.0); unsupported-claim 0.9881; the adapter does not
  copy grounded facts into the answer.
- **Key finding.** With **identical retrieval to Track A** (retrieval recall 0.5593
  for both), Track C scored 0.0169 vs 0.4576. The evidence was the same; only the
  generator differed. **The context-free, overfit adapter is the binding
  constraint** — bolting it onto RAG did not help and actively hurt.

## 4. Research questions answered (evidence only)

1. **Did Pure RAG perform well?** Relatively, within scope — best of the three
   (0.4576 accuracy, 0.16 hallucination, 0.84 abstention accuracy). Absolute
   accuracy is still capped by retrieval recall (~0.56).
2. **Did small-data LoRA replace retrieval?** **No.** 0.0678 vs 0.4576; it
   fabricated on all source-missing cases and degenerated.
3. **Did Hybrid improve over Pure RAG?** **No.** 0.0169 < 0.4576 (and < 0.0678 on
   accuracy). The reused adapter capped quality.
4. **Role of retrieval grounding?** **Dominant.** Identical retrieval (0.5593
   recall) under A and C produced 0.4576 vs 0.0169 — the generator, not the
   evidence, decided the outcome.
5. **When is fine-tuning appropriate?** As a **behaviour/format layer trained on
   the retrieval-augmented setting**, not as a knowledge store.

## 5. Limitations

Stated plainly, without minimization:

- **Single institution / limited domain.** One data source (CSULB Graduate Center,
  12 programs); findings may not transfer to other domains or content structures.
- **Small supervised dataset.** 121 train / 13 validation examples — Track B/C are
  data-starved, and the fine-tuning results may partly reflect dataset size rather
  than fine-tuning per se.
- **One benchmark, small cells.** 84 cases across 8 categories (n=5–13 each) limits
  statistical power; category-level numbers are indicative, not definitive.
- **One base-model family.** Only `Qwen2.5-7B`; no cross-family or cross-size check.
- **Mixed runtimes.** Track A used Ollama; Tracks B/C used Apple MLX 4-bit. Latency
  is therefore **not** directly comparable across tracks and quantization differs.
- **Deterministic proxy scoring.** Substring/set matching (no LLM judge) is
  reproducible but can both under- and over-credit answers; some Track B/C
  "successes" were substring coincidences on otherwise degenerate text.
- **Single greedy run per track.** No seed/variance sweep.
- **Track C used the mandated P8.1 adapter unchanged** — it was never trained with
  retrieved context, so Track C tests *this* adapter in a hybrid, not hybrids in
  general.

## 6. Final conclusions

**What did this project demonstrate?** Within the scope of this study, **retrieval
grounding is the dominant factor** for factual, updatable QA over a maintained
corpus. Small-data LoRA neither replaced retrieval (Track B) nor improved a working
RAG pipeline (Track C).

**What surprised us?** Two results. First, tiny-dataset LoRA did not merely
under-perform — it **catastrophically degenerated** a strong instruct model
(repetition, fabricated tokens). Second, the **hybrid scored below even
fine-tuning-only**: adding correct retrieved context did not rescue a degraded
generator, and the controlled design (identical retrieval, 0.5593 recall in both A
and C) isolates the adapter as the cause.

**What practical guidance emerged?** For factual assistants over a maintained
knowledge base, **invest in retrieval quality first**; use fine-tuning only as a
behaviour layer, and only when it is trained *with* retrieved context in the
prompt. A poorly-trained adapter is not neutral — it can drag down an otherwise
functional RAG system.

*These conclusions hold in this experimental setting (one institution, one small
SFT set, one benchmark, one 7B base family, Apple MLX). See `future_work.md` for
the experiments that would test their generality and `lessons_learned.md` for the
engineering practices that made the comparison trustworthy.*
