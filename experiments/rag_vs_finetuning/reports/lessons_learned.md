# Engineering Lessons Learned

*Practical lessons from the RAG vs Fine-Tuning vs Hybrid experiment. Evidence-based;
derived from the completed frozen results.*

## 1. Retrieval grounding is the highest-leverage decision

The cleanest result of the study: Track A and Track C were given **identical
retrieved evidence** (retrieval recall@k = 0.5593 in both), yet answer accuracy was
0.4576 vs 0.0169. Grounding — and the ability to condition generation on real
source text — did more for factual accuracy than any weight update. **Lesson:** for
factual, updatable domains, spend engineering effort on retrieval (chunking,
embeddings, recall, thresholds) before reaching for fine-tuning.

## 2. Fine-tuning is a behaviour layer, not a knowledge store

A 121-example LoRA did not teach the model facts; it degraded fluency and produced
confident fabrication (Track B hallucination 1.0, unsupported-claim 0.9467).
**Lesson:** use supervised fine-tuning to shape *format, tone, and refusal
behaviour* on top of retrieved evidence — never to memorize institutional facts,
especially with small datasets.

## 3. Small data + aggressive LR = overfitting you must design against

Training logged a validation-loss minimum at **iter 40 (1.018)** followed by
divergence to 5.338 by iter 200. Selecting the **lowest-validation-loss
checkpoint** (not the final one) was essential and still insufficient.
**Lesson:** with tiny datasets, match learning rate and step count to the data,
checkpoint frequently, select by validation loss, and use early stopping.
Assume overfitting is the default, not the exception.

## 4. A weak component can make a system worse, not just no-better

The hybrid (Track C) scored **below even fine-tuning-only** on accuracy
(0.0169 < 0.0678). Combining a good retriever with a bad generator did not average
out — the generator dominated the output. **Lesson:** in a pipeline, the weakest
component in the generation path sets the ceiling; adding a strong upstream stage
does not compensate for a broken downstream one.

## 5. Controlled experimentation is what made the finding trustworthy

Holding the corpus, benchmark, scoring, and base-model family constant let us
attribute the A-vs-C gap **solely to the adapter** (same retrieval recall, opposite
accuracy). **Lesson:** freeze everything you are not testing. One frozen benchmark
and one evaluation pipeline shared across conditions is worth more than three
bespoke evaluations.

## 6. Reproducibility via checksums caught drift and enabled exact recompute

Every phase guarded artifacts with SHA-256 checksums (corpus, chunks, index,
benchmark, adapter, reports). Each track's metrics **recomputed to its frozen
report exactly**, and integrity checks confirmed no frozen artifact changed across
six evaluation/analysis phases. **Lesson:** content-hash your datasets, models, and
reports; verify reproduction before every comparison.

## 7. Evaluate abstention and hallucination, not just accuracy

The tracks differed most on *how* they failed: Track A refused safely (hallucination
0.16, abstention accuracy 0.84), while B and C fabricated (hallucination 1.0,
abstention 0.0). A single accuracy number would have hidden the most important
safety property. **Lesson:** for grounded assistants, measure hallucination rate,
abstention accuracy, and unsupported-claim rate as first-class metrics.

## 8. Benchmark design decides what you can conclude

Including **source-missing** and **unknown** categories (should-abstain cases) is
what exposed Track B/C fabrication; category breakdowns (n=5–13) localized where
each track failed. **Lesson:** design benchmarks with explicit "should refuse"
cases and category labels, and prevent train/benchmark leakage (verified here).

## 9. Environment realities shape the architecture

No single interpreter had both the retrieval stack (chromadb/sentence-transformers,
Python 3.13) and MLX (Python 3.9). Track C bridged them with a JSON hand-off rather
than forcing one runtime. **Lesson:** treat interpreter/runtime boundaries as
first-class design constraints; a clean process boundary beats a fragile shared
environment.

## 10. Deterministic scoring has known blind spots — document them

Substring/set matching is reproducible but credited degenerate outputs that merely
contained an expected token ("representative successes" that were coincidences).
**Lesson:** state your scoring's failure modes explicitly, and treat an LLM judge
or human review as future work rather than pretending the proxy is ground truth.
