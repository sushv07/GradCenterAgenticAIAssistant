# Phase P11 — Three-Way Comparison: Track A vs Track B vs Track C

## Consistency

- same benchmark for all three: True
- each reproduces its frozen report: {'track_a': True, 'track_b': True, 'track_c': True}

## Overall metric comparison

| metric | Track A (RAG) | Track B (FT) | Track C (Hybrid) | winner |
| --- | --- | --- | --- | --- |
| answer_accuracy | 0.4576 | 0.0678 | 0.0169 | track_a |
| completeness | 0.4576 | 0.0678 | 0.0169 | track_a |
| hallucination_rate | 0.16 | 1.0 | 1.0 | track_a |
| unsupported_claim_rate | 0.25 | 0.9467 | 0.9881 | track_a |
| refusal_rate | 0.5714 | 0.1071 | 0.0 | context |
| abstention_accuracy | 0.84 | 0.0 | 0.0 | track_a |
| citation_precision | 0.1525 | 0.0 | 0.161 | track_c |
| citation_recall | 0.5254 | 0.0 | 0.5593 | track_c |
| retrieval_recall_at_k | 0.5593 | 0.0 | 0.5593 | tie |

## Operational (avg end-to-end latency, ms)

- A 3410.0 · B 25576.4 · C 4901.9
> Latency not directly comparable across runtimes (Ollama vs MLX).

## Category comparison (answer accuracy)

| category | n | A | B | C | winner |
| --- | --- | --- | --- | --- | --- |
| admissions | 5 | 1.0 | 0.0 | 0.0 | track_a |
| application | 12 | 0.3333 | 0.0833 | 0.0 | track_a |
| contact | 12 | 0.4167 | 0.0 | 0.0 | track_a |
| multi_field | 8 | 0.375 | 0.0 | 0.125 | track_a |
| overview | 12 | 0.6667 | 0.25 | 0.0 | track_a |
| retrieval_challenge | 10 | 0.2 | 0.0 | 0.0 | track_a |
| source_missing | 13 | 0.6923 | 0.0 | 0.0 | track_a |
| unknown | 12 | 1.0 | 0.0 | 0.0 | track_a |

## Failure-mode comparison (counts)

- Track A: {'abstention_error': 31, 'hallucination': 4, 'incorrect_answer': 5, 'incorrect_citation': 59, 'missing_citation': 31, 'retrieval_failure': 29}
- Track B: {'hallucination': 25, 'incorrect_answer': 46, 'over_refusal': 9}
- Track C: {'hallucination': 25, 'incorrect_answer': 58}

## Discussion

- **Track C vs Track B:** Adding retrieval to the same adapter changed answer accuracy 0.0678 (B) -> 0.0169 (C) and hallucination 1.0 -> 1.0. Grounding is lower for accuracy vs fine-tuning-only.
- **Track C vs Track A:** Against Pure RAG, Track C answer accuracy is 0.0169 vs 0.4576 (A) — lower; hallucination 1.0 vs 0.16. Track C uses the SAME retrieval as A, so any gap is attributable to the adapter's generation.
- **Did retrieval compensate?** Retrieval only partly compensated for the weak adapter: Track C recovers grounded evidence and citations that Track B lacked, but the reused context-free/overfit adapter still degrades the final generation.
- **Hybrid as expected?** The architecture behaved as designed (retrieval feeds context, adapter generates, empty-retrieval abstains), but the reused Track B adapter — trained WITHOUT context and overfit — is the binding constraint, so the hybrid did not reach Track A quality.

## Error analysis (Track C)

counts: {'hallucination': 25, 'incorrect_answer': 58}

- Degenerate / low-information answers — the adapter emits short corrupted refusals ('I don't have that.') even when correct context is present.
- Grounding under-use — retrieved context is in the prompt and cited, but the adapter does not copy the grounded fact into the answer.
- Retrieval ceiling — some answerable questions retrieve the wrong program's chunk (shared Track A recall limit).
- Citations are populated from retrieved evidence, so citation errors track retrieval precision rather than fabrication.

Representative Track C failures:

- EVAL-001 (incorrect_answer): I don't have a provided, for that, don: have a to answer that.
- EVAL-002 (incorrect_answer): I don't have a (1990s) to answer that.
- EVAL-003 (incorrect_answer): I don't have a provided, for that, and for the provided, that, don, have a look in the provided, that, to answer that.
- EVAL-004 (incorrect_answer): I don't have a (1991) to answer that.

## Research conclusions

### When should RAG be preferred over fine-tuning?

- On this benchmark RAG beat fine-tuning-only decisively (0.4576 vs 0.0678 accuracy; hallucination 0.16 vs 1.0).
- Prefer RAG when institutional knowledge is factual, updatable, and larger than what a small SFT set can encode, and when safe abstention on missing evidence matters — RAG grounds answers and refuses instead of fabricating.
- Prefer fine-tuning only for fixed behaviour/format/style, not for storing facts; a 121-example LoRA injected no reliable knowledge and degraded generation.

### When does hybrid RAG + fine-tuning add value?

- Hybrid did not beat fine-tuning-only (0.0169 vs 0.0678).
- Hybrid did NOT surpass Pure RAG (0.0169 vs 0.4576): reusing the weak, context-free Track B adapter as the generator capped quality.
- Hybrid RAG+fine-tuning adds value only when the adapter is trained ON the retrieval-augmented format (context -> grounded answer/refusal). Bolting an adapter tuned without context onto a RAG pipeline does not help and can hurt.
- Evidence-based recommendation: for a future Track C iteration, retrain a small adapter with retrieved context in the prompt and proper regularisation (more data, lower LR, early stopping); keep retrieval as the knowledge source.

**Central answer:** Retrieval grounding is the dominant factor for factual, updatable QA. Fine-tuning helps only as a behaviour layer on top of retrieval, and only when trained for that setting; a weak adapter provides no hybrid benefit over pure RAG.

## Threats to validity

- Small SFT dataset (121/13) — Track B/C adapter is data-starved.
- Single institution and single base-model family (Qwen2.5-7B).
- Tracks A vs B/C use different runtimes (Ollama vs Apple MLX 4-bit); latency not directly comparable.
- Deterministic substring/set scoring, not an LLM judge.
- 84-case benchmark; small per-category cells (n=5–13).
- Single greedy run per track; no variance sweep.
- Track C reuses the P8.1 adapter unchanged (mandated); it was not trained with context.
