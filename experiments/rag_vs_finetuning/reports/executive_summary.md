# Executive Summary — RAG vs Fine-Tuning vs Hybrid

**One-page overview for readers unfamiliar with the repository.**

## Problem

Graduate applicants ask factual questions about master's programs (deadlines,
contacts, program overviews). We built an assistant for the CSULB Graduate Center
and used it to answer a broader engineering question: **when institutional
knowledge is factual and changes over time, and the training data is small, should
you use retrieval (RAG), fine-tune the model, or combine both?**

## Approach

Three systems were built on the **same** frozen knowledge base, the **same** 84-question
benchmark, and the **same** scoring pipeline, so results are directly comparable:

- **Track A — Pure RAG:** retrieve the relevant program text from a vector database
  (Chroma), then have a 7B model answer *using only that text*.
- **Track B — Fine-Tuned only:** train a small LoRA adapter (Qwen2.5-7B) on 121
  examples and answer from the model's own weights, no retrieval.
- **Track C — Hybrid:** the Track A retrieval feeding the Track B adapter.

Everything was checksum-frozen and reproducible; each system's scores recompute
exactly from its saved outputs.

## Experimental design

A controlled, between-systems comparison holding the corpus, benchmark, evaluation
metrics, and base-model family constant — so any difference is attributable to the
one thing that changed (retrieval vs weights vs both). Metrics went beyond accuracy
to include **hallucination rate** and **abstention accuracy** (did the system
correctly say "I don't know" when the answer wasn't available?).

## Major findings

| System | Answer accuracy | Hallucination | Safely abstains? |
| --- | --- | --- | --- |
| **A — Pure RAG** | **0.46** | 0.16 | Yes (0.84) |
| B — Fine-Tuned | 0.07 | 1.00 | No (0.00) |
| C — Hybrid | 0.02 | 1.00 | No (0.00) |

- **Retrieval won decisively** and was the only system that refused to fabricate
  when it lacked evidence.
- **Small-data fine-tuning did not add knowledge** — it produced confident, wrong,
  often degenerate answers.
- **The hybrid was the cleanest result:** Tracks A and C were handed *identical*
  retrieved evidence, yet A scored 0.46 and C scored 0.02. Same facts in, very
  different answers out — proving the **fine-tuned generator, not the evidence, was
  the bottleneck.** A poorly trained adapter made a working RAG system *worse*.

## Engineering impact

- For factual, updatable assistants, **invest in retrieval quality first**;
  fine-tuning is a behaviour/format layer, not a knowledge store.
- **A weak component can degrade a whole pipeline** — combining a good retriever
  with a bad generator did not average out.
- **Rigor paid off:** one frozen benchmark + one scoring pipeline + checksummed
  artifacts made a surprising result trustworthy and exactly reproducible.

*Scope: one institution, one small supervised dataset, one benchmark, one 7B model
family, on-device Apple MLX. Conclusions are stated for this experimental setting;
generalization is proposed as future work.*
