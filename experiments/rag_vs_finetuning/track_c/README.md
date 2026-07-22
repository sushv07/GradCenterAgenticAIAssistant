# Track C — Hybrid System (Fine-Tuned + RAG)

**Phase P10 — engineering implementation only.** Track C combines the frozen
Track A retrieval pipeline with the official Track B LoRA adapter. It is **not**
evaluated here (that is Phase P11): no benchmark run, no metrics, no comparison.

## Design rationale (from P9)

The P9 comparative analysis showed Pure RAG (Track A) beat Fine-Tuned-Only
(Track B) on every category (answer accuracy 0.458 vs 0.068), because **knowledge
must come from retrieval, not from a small LoRA**, and because RAG's
evidence-aware abstention avoids fabrication (hallucination 0.16 vs 1.0). Track C
therefore assigns responsibilities explicitly:

| Concern | Source in Track C |
| --- | --- |
| Institutional knowledge / facts | **Retrieval** (Chroma top-k chunks) — authoritative |
| Answer/refusal behaviour & style | **Track B LoRA adapter** (behaviour only) |
| Grounding & abstention | Grounded prompt + empty-retrieval refusal |

The adapter is **not** expected to memorise knowledge; retrieved context is the
authoritative source.

## Architecture

```text
User Question
      │
      ▼
Embedding  (all-MiniLM-L6-v2, frozen)          ─┐
      │                                          │  track_c/retrieve.py
      ▼                                          │  (Python 3.13: chromadb)
Vector Search  (Chroma masters_track_a_v1)       │  reuses track_a.retriever
      │                                          │  EXACTLY (top_k=4, thr=0.0)
      ▼                                          │
Top-k Chunks ───────────────────────────────────┘
      │        (JSON bundle bridges interpreters)
      ▼
Prompt Construction  (track_c/prompt_builder.py) ─┐
   system + retrieved context + question           │  track_c/infer.py
      │                                             │  (Python 3.9: mlx_lm)
      ▼                                             │
Base Model  Qwen2.5-7B-Instruct-4bit (frozen)       │
      +  Official Track B LoRA adapter (checksum-   │
         verified: sha256:a2a09086…)                │
      │                                             │
      ▼                                             │
Grounded Answer + Citations ─────────────────────────┘
```

### Why two interpreters

No single interpreter on this machine has both stacks:

- **Retrieval** needs `chromadb` + `sentence-transformers` → miniconda **Python 3.13**.
- **MLX generation** needs `mlx_lm` → CommandLineTools/Xcode **Python 3.9**.

`infer.py` (3.9) obtains retrieved context by invoking `retrieve.py` under the
3.13 interpreter (`TRACK_C_RETRIEVER_PYTHON`, default `/opt/miniconda3/bin/python3`)
and passing a JSON bundle. This keeps the frozen retrieval pipeline untouched and
avoids importing chromadb into the MLX process. For batch evaluation (P11),
`retrieve.py --questions-file … --out bundle.jsonl` precomputes retrieval once and
`infer.run_bundle_file()` generates from it.

## Execution flow

1. `retrieve.py` embeds the question and queries the frozen Chroma collection,
   returning the top-k chunks (id, program, section, similarity, content) — the
   exact `track_a.retriever.retrieve` call with config `top_k`/`threshold`.
2. `infer.py` loads the 4-bit base + Track B adapter once (`TrackCModel`), verifying
   the adapter checksum against the P8.1 selected adapter before use.
3. If retrieval returns **no** chunks, Track C refuses **without calling the model**
   (grounding failure mode, mirrors Track A) and emits the insufficient sentinel.
4. Otherwise `prompt_builder.build_messages` constructs `system + context + question`,
   the tokenizer applies the chat template, and the model generates greedily
   (temp 0, seed 42, max 256 tokens).
5. Abstention is detected (`is_insufficient`); citations are selected from the
   actually-retrieved chunk ids (`select_citations`).
6. A `ResponseRecord`-compatible dict is returned (`track="track_c_hybrid"`).

## Prompt template (`rag_ft_prompt_v1`)

System instruction (grounding rules):

```
You are the CSULB Graduate Center assistant. Answer the user's question USING
ONLY the retrieved Graduate Center context provided in the user message.
Follow these rules strictly:
1. Use only facts present in the retrieved context. Never invent, infer, or add
   outside knowledge, and never make unsupported claims.
2. If the retrieved context does not contain the answer, reply exactly:
   "I don't have enough information in the provided Graduate Center data to answer that." Do not guess.
3. Preserve published wording verbatim (deadlines, program names, contacts). Do
   not convert dates or invent a year.
4. Be concise and factual; do not repeat yourself.
```

User turn:

```
Retrieved context:
[chunk_id=… | program=… | section=… | similarity=…]
<chunk text>

[chunk_id=… | …]
<chunk text>

Question: <the question>

Answer using ONLY the retrieved context above. If the context is insufficient,
reply exactly: "I don't have enough information in the provided Graduate Center data to answer that."
```

The insufficient sentinel matches the phrase the Track B adapter was fine-tuned to
produce, so the adapter's learned behaviour and the grounded instruction agree.

## Adapter loading

`TrackCModel` calls `mlx_lm.load(BASE_MODEL, adapter_path=track_b_selected/)`. The
base is the frozen `mlx-community/Qwen2.5-7B-Instruct-4bit`; the adapter is the
**official P8.1 selected adapter** (`artifacts/adapters/track_b_selected/`,
`sha256:a2a09086…`). The checksum is verified on load — a mismatch aborts. No
retraining, no adapter modification.

## Retrieval integration

Retrieval reuses the frozen artifacts **exactly** and read-only:

- embedder `all-MiniLM-L6-v2` (P6 config), Chroma collection `masters_track_a_v1`,
  `top_k=4`, `threshold=0.0` — all from `configs/config`.
- `track_a.retriever.retrieve` is imported and called unchanged; chunking,
  embeddings, and the index are never touched.

## Citation handling

- `retrieved_chunk_ids` — every chunk returned by retrieval.
- `citation_chunk_ids` — drawn from the retrieved evidence (never invented): empty
  when the model abstains; otherwise chunk ids explicitly named in the answer, or
  all retrieved ids as the grounded support set (mirrors Track A policy).

## Files

| File | Interpreter | Role |
| --- | --- | --- |
| `prompt_builder.py` | both (stdlib) | grounded prompt, abstention detector, citation selection |
| `retrieve.py` | 3.13 | frozen retrieval stage + JSON/bundle CLI |
| `infer.py` | 3.9 (MLX) | base+adapter load, retrieval bridge, grounded generation |
| `cli.py` | 3.9 (MLX) | functional-validation harness (sanity questions) |

## Running

```bash
# functional validation (loads model once, runs sanity questions)
/Library/Developer/CommandLineTools/usr/bin/python3 \
    -m experiments.rag_vs_finetuning.track_c.cli

# single question
/Library/Developer/CommandLineTools/usr/bin/python3 \
    -m experiments.rag_vs_finetuning.track_c.infer "Who should I contact for Social Work?"
```
