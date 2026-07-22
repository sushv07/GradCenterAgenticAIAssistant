# Future Work

*Recommended next steps. These are **not** part of the completed experiment; they
are hypotheses and improvements motivated by the frozen results (see
`final_conclusions.md`). Nothing below has been implemented or measured.*

## Directly motivated by the findings

### 1. Retrieval-aware fine-tuning (the highest-priority follow-up)
The central negative result was that a **context-free, overfit adapter** dragged
down a working RAG pipeline (Track C 0.0169 vs Track A 0.4576 on identical
retrieval). The natural next experiment is a **Track C-v2**: train a small adapter
on `(retrieved-context → grounded-answer / grounded-refusal)` pairs so the model
learns to *use* injected evidence and to abstain when it is missing. Keep retrieval
as the authoritative knowledge source; the adapter only shapes faithful formatting.

### 2. Larger, cleaner instruction dataset with regularization
Track B/C used 121 training examples and overfit (val loss diverged after iter 40).
Future work: scale the SFT set (paraphrase augmentation, more programs/sections),
lower the learning rate, add early stopping on validation loss, and sweep LoRA rank
— then re-run B and C to test whether the conclusions are data-size artifacts.

### 3. Raise the retrieval ceiling
Track A's accuracy was bounded by retrieval recall (~0.56); several answerable
questions retrieved the wrong program's chunk. Candidate improvements: a
**cross-encoder reranker**, **query expansion / rewriting**, program-aware metadata
filtering, higher `top_k`, and tuned similarity thresholds. Each should be measured
against the same frozen benchmark.

## Broader generalization

### 4. Multiple base-model families and sizes
The study used one family (Qwen2.5-7B). Repeat A/B/C across families (e.g.,
Llama, Mistral) and sizes to test whether "retrieval dominates small-data
fine-tuning" holds beyond this model.

### 5. Larger and multi-institution benchmarks
84 cases over one institution (CSULB) with small per-category cells (n=5–13) limits
statistical power. Expand to more programs, more institutions, and more cases per
category; add difficulty strata and multi-hop questions.

### 6. Evaluation methodology upgrades
Deterministic substring/set scoring credited some degenerate outputs. Add an
**LLM-as-judge** track (with human spot-checking), calibrated abstention scoring,
and inter-rater/variance analysis (multiple decoding seeds) to complement the
deterministic metrics.

## Toward production

### 7. Production deployment concerns
If a RAG assistant is deployed: caching and latency budgets, corpus refresh /
re-indexing pipelines, citation rendering in the UI, guardrails on abstention
messaging, and monitoring for retrieval drift.

### 8. User studies
Offline accuracy is a proxy. Run task-based user studies with prospective graduate
applicants to measure perceived helpfulness, trust in citations, and the real-world
cost of over-abstention vs hallucination.

---

**Scope note.** Items 1–3 test the study's own recommendations directly; items 4–6
test the generality of its conclusions; items 7–8 concern productization. All are
future work — the completed project covers only Tracks A, B, and C as evaluated in
phases P7–P11.
