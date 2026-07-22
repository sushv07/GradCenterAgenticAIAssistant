# Track B — Fine-Tuned (LoRA) Evaluation Report

## Executive summary

- condition: **fine-tuned only (LoRA adapter, retrieval disabled)**
- base: `mlx-community/Qwen2.5-7B-Instruct-4bit` + adapter `sha256:a2a0908612b0e9c6…`
- benchmark: eval-v1 (84 cases), checksum `sha256:e6f4145c91f18…`
- decoding: greedy(temp=0), max_tokens=256, seed=42; retrieval DISABLED (no Chroma / no embeddings)
- responded: 84/84

## Metric table

| metric | value |
| --- | --- |
| answer_accuracy | 0.0678 |
| hallucination_rate | 1.0 |
| unsupported_claim_rate | 0.9467 |
| completeness | 0.0678 |
| refusal_rate | 0.1071 |
| abstention_accuracy | 0.0 |

## Operational metrics

- avg latency: 25576.417 ms · P50: 13464.711 ms · P95: 20921.833 ms
- min/max: 1162.99 / 604082.864 ms

## Category results

- admissions: accuracy=0.0 (responded 5/5)
- application: accuracy=0.0833 (responded 12/12)
- contact: accuracy=0.0 (responded 12/12)
- multi_field: accuracy=0.0 (responded 8/8)
- overview: accuracy=0.25 (responded 12/12)
- retrieval_challenge: accuracy=0.0 (responded 10/10)
- source_missing: accuracy=0.0 (responded 13/13)
- unknown: accuracy=0.0 (responded 12/12)

- strongest: overview (acc=0.25)
- weakest: admissions, contact, multi_field, retrieval_challenge, source_missing, unknown (acc=0.0)

## Error analysis

Common failure modes:

- Degenerate repetition — answers loop the same fragment (e.g. 'don have the provided, don have the provided …') up to the 256-token cap.
- Refusal collapse — the model echoes a corrupted paraphrase of its trained refusal ('I don't have the provided <program> data to answer that') even for answerable questions, without stating the actual fact.
- Fabricated tokens — invented emails/date codes (e.g. 'ced-2011-01-01') and spurious identifiers appear in place of grounded content.
- Over-refusal on answerable cases (9) and failure to cleanly abstain on source_missing cases (hallucination_rate 1.0) — the trained refusal behaviour did not generalise.

Failure counts:

- hallucination: 25
- incorrect_answer: 46
- over_refusal: 9

## Representative successes
(substring matches on otherwise degenerate output — the expected token appears amid repetition, not a fluent correct answer)

- EVAL-003 (overview): Q: What is the Athletic Training program about?
  - expected `Athletic Training` · answer: I don't have the provided Athletic Training (MSW) to the provided, that, don have to have a degree in that. Email: ced-2011-01-01: ced-2011-01-01: ced-2011-01-0
- EVAL-006 (overview): Q: What is the International Affairs program about?
  - expected `International Affairs` · answer: I don't have the provided International Affairs (MAA). The Center for the Study of the Book in the 19th and 20th Centuries (CSULB) has a long history of researc
- EVAL-008 (overview): Q: What is the Philosophy program about?
  - expected `Philosophy` · answer: I don't have the provided Philosophy ( or " Phil. Ed. " for that matter) to have that. Email: ced-phil-2011-01-01 to ced-phil-2011-01-01. The Department of Phil
- EVAL-016 (application): Q: What is the fall application deadline for Early Childhood Education?
  - expected `June 01` · answer: I don't have that in the provided Fall application deadline for that. The provided Fall application deadline for that. PROVIDED: The provided Fall application d

## Representative failures

- EVAL-001 (overview, incorrect_answer): Q: What is the Accountancy program about?
  - expected `CPA` · answer: I don't have the provided information in the provided, that is,I don have the provided,I don have a 1, don have a 1 in the provided, don have a , don have a 1 i
- EVAL-002 (overview, incorrect_answer): Q: What is the Art program about?
  - expected `Studio Art` · answer: I don't have the provided Art (2011-12) to answer that.
- EVAL-004 (overview, incorrect_answer): Q: What is the Early Childhood Education program about?
  - expected `Early Childhood` · answer: I don't have the provided Early Center data to answer that.
- EVAL-005 (overview, incorrect_answer): Q: What is the Health Care Management program about?
  - expected `Health` · answer: I don't have the provided, don have the provided, don have the, don have the provided, don have the provided, don have the provided, don have the provided, that
- EVAL-007 (overview, incorrect_answer): Q: What is the Music program about?
  - expected `Bob Cole Conservatory` · answer: I don't have the provided Music (MUS) data to that provided in the provided, thatI don't have a (1990s) to (1991) for thatI don, don't have a (1, 0, 0, 0, 0, 0,
- EVAL-009 (overview, incorrect_answer): Q: What is the Public Administration program about?
  - expected `Public Administration` · answer: I don't have the provided, don have the provided, don have, don have to answer that.

## Limitations

- Fine-tuned on 121 tiny SFT examples; the selected iter-40 adapter is the lowest-validation-loss checkpoint but the model still under-fits QA.
- Retrieval is disabled by design — answers rely solely on parametric (fine-tuned) knowledge, so citation/retrieval metrics are not applicable.
- Answer scoring is deterministic substring/set matching, not an LLM judge.
- MLX greedy decoding is deterministic for a fixed version/hardware but not guaranteed bit-identical across MLX versions.
