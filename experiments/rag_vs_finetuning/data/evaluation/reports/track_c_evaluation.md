# Track C — Hybrid (RAG + Fine-Tuned) Evaluation Report

## Executive summary

- condition: **hybrid — retrieval grounding + Track B LoRA adapter**
- base `mlx-community/Qwen2.5-7B-Instruct-4bit` + adapter `sha256:a2a0908612b0e9c6…`; retrieval `chroma / masters_track_a_v1 (cosine, top_k=4, thr=0.0)`
- benchmark: eval-v1 (84 cases), checksum `sha256:e6f4145c91f18…`
- decoding: greedy(temp=0), max_tokens=256, seed=42; model invocations: 84/84 (rest refused on empty retrieval)
- responded: 84/84

## Metric table

| metric | value |
| --- | --- |
| answer_accuracy | 0.0169 |
| completeness | 0.0169 |
| hallucination_rate | 1.0 |
| unsupported_claim_rate | 0.9881 |
| refusal_rate | 0.0 |
| abstention_accuracy | 0.0 |

## Groundedness & citations

| metric | value |
| --- | --- |
| citation_precision | 0.161 |
| citation_recall | 0.5593 |
| retrieval_recall_at_k | 0.5593 |
| retrieval_precision_at_k | 0.161 |

## Operational metrics

- end-to-end avg 4901.895 ms · P50 3472.627 ms · P95 16397.427 ms
- avg generation 4893.748 ms · avg retrieval 8.147 ms

## Category results

- admissions: accuracy=0.0 (responded 5/5)
- application: accuracy=0.0 (responded 12/12)
- contact: accuracy=0.0 (responded 12/12)
- multi_field: accuracy=0.125 (responded 8/8)
- overview: accuracy=0.0 (responded 12/12)
- retrieval_challenge: accuracy=0.0 (responded 10/10)
- source_missing: accuracy=0.0 (responded 13/13)
- unknown: accuracy=0.0 (responded 12/12)

- strongest: multi_field (acc=0.125)
- weakest: admissions, application, contact, overview, retrieval_challenge, source_missing, unknown (acc=0.0)

## Error analysis (counts)

- hallucination: 25
- incorrect_answer: 58

## Representative successes

- EVAL-049 (multi_field): expected `Dr. Caitlin Fouratt` · I don't have the provided information in the provided, that, that, to answer that.

## Representative failures

- EVAL-001 (overview, incorrect_answer): I don't have a provided, for that, don: have a to answer that.
- EVAL-002 (overview, incorrect_answer): I don't have a (1990s) to answer that.
- EVAL-003 (overview, incorrect_answer): I don't have a provided, for that, and for the provided, that, don, have a look in the provided, that, to answer that.
- EVAL-004 (overview, incorrect_answer): I don't have a (1991) to answer that.
- EVAL-005 (overview, incorrect_answer): I don't have a provided, for that, don: have a to answer that.
- EVAL-006 (overview, incorrect_answer): I don't have a provided (2011) to 2014. The Department of International Studies (DID: 111111111) offers a Master of Arts in International Studies (MA)

## Limitations

- Reuses the P8.1 Track B adapter, which was fine-tuned WITHOUT retrieved context and overfit on 121 examples; grounded context is supplied but the adapter still tends to degenerate.
- Retrieval is the frozen Track A stack (top_k=4, threshold=0.0), so answer quality is bounded by its recall (same retrieval as Track A).
- Deterministic substring/set scoring, not an LLM judge.
- MLX greedy decoding is deterministic for a fixed version/hardware.
