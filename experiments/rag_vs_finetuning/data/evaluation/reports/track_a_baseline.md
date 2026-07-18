# Track A — Pure RAG Baseline Report

- dataset: eval-v1 (84 cases), checksum `sha256:e6f4145c91f18…`
- model: `qwen2.5:7b-instruct` · embedding: `all-MiniLM-L6-v2` · prompt: `rag_prompt_v1`
- vector store: chroma / masters_track_a_v1 (cosine)

## Overall metrics

- answer_accuracy: 0.4576
- abstention_accuracy: 0.84
- hallucination_rate: 0.16
- citation_precision: 0.1525
- citation_recall: 0.5254
- retrieval_recall_at_k: 0.5593
- retrieval_precision_at_k: 0.161
- avg_retrieval_latency_ms: 29.4913
- avg_generation_latency_ms: 3380.5248
- avg_end_to_end_latency_ms: 3410.0161
- avg_answer_chars: 135.1429

## Metrics by category

- admissions: accuracy=1.0 (n=5)
- application: accuracy=0.3333 (n=12)
- contact: accuracy=0.4167 (n=12)
- multi_field: accuracy=0.375 (n=8)
- overview: accuracy=0.6667 (n=12)
- retrieval_challenge: accuracy=0.2 (n=10)
- source_missing: accuracy=0.6923 (n=13)
- unknown: accuracy=1.0 (n=12)

## Failure analysis (counts)

- abstention_error: 31
- hallucination: 4
- incorrect_answer: 5
- incorrect_citation: 59
- missing_citation: 31
- retrieval_failure: 29

## Retrieval diagnostics

- avg retrieved chunks: 4.0 · avg similarity: 0.4849
- never-retrieved chunks: 3

## Limitations

- Single greedy run (temperature 0); Ollama decoding is not guaranteed bit-identical across versions.
- Answer scoring is deterministic substring/set matching, not an LLM judge.
- Baseline reflects the frozen retrieval/prompt/model; no tuning applied.
