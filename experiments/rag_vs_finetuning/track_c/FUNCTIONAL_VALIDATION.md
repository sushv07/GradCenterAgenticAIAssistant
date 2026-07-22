# Track C — Functional Validation Report (Phase P10)

**Scope:** engineering sanity checks only. No benchmark run, no metrics, no
comparison to Track A/B. Purpose: confirm the hybrid pipeline executes end-to-end.

- **Base model:** `mlx-community/Qwen2.5-7B-Instruct-4bit` (frozen)
- **Adapter:** official Track B selected adapter, checksum verified `sha256:a2a09086…`
- **Retrieval:** frozen Track A stack (`all-MiniLM-L6-v2`, Chroma `masters_track_a_v1`,
  top_k=4, threshold=0.0), reused unchanged via the 3.13 interpreter
- **Decoding:** greedy (temp 0), seed 42, max 256 tokens
- Run: `python -m experiments.rag_vs_finetuning.track_c.cli`

## Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Retrieval executes | ✅ PASS | 4 chunks returned per query, 14–114 ms latency |
| Adapter loads | ✅ PASS | checksum verified on load (`sha256:a2a09086…`) |
| Retrieved context appears in prompt | ✅ PASS | 892–919 chars of labelled `[chunk_id=…]` context injected |
| Citations generated | ✅ PASS | `citation_chunk_ids` populated from retrieved evidence |
| Insufficient evidence handled | ✅ PASS | forced empty retrieval → exact sentinel, model not called |
| No runtime errors | ✅ PASS | CLI exit 0 |

## Observed traces (abridged)

1. **Answerable — deadline.** *"What is the application deadline for Accountancy?"*
   → 4 application chunks retrieved & cited; grounded prompt built; model returned a
   degenerate near-refusal (`"I don't have that."`).
2. **Answerable — contact.** *"Who should I contact for Social Work?"* → social-work
   overview/contact chunks retrieved & cited; model output degenerate
   (`"I don't have have, have, don, have…"`).
3. **Source-missing probe.** *"What is the tuition cost … for the Music program?"* →
   chunks retrieved & cited; model output `"I don't have a provided, and don to have that."`
4. **Grounding-failure probe** (threshold 0.99 → **0 chunks**) → Track C refused
   **without calling the model**: `insufficient_evidence=True`, `citation_chunk_ids=[]`,
   answer = the exact sentinel *"I don't have enough information in the provided
   Graduate Center data to answer that."*

## Honest engineering note (not a metric)

The pipeline is functionally correct — retrieval, prompt construction, adapter
loading, citation population, and abstention all work. However, the official Track B
adapter produces **degenerate near-refusal text even when grounded context is
present**, consistent with the P8.2 / P9 finding that this adapter (LoRA over 121
examples, overfit) degraded generation. This is expected here and is **not**
assessed in P10; Phase P11 will formally evaluate Track C's answer quality on the
frozen benchmark. It also confirms the P9 recommendation that a future adapter
should be trained *with* retrieved context in the prompt rather than reusing the
context-free Track B adapter.
