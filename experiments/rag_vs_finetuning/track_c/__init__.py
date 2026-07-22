"""Track C — Hybrid (Fine-Tuned + RAG) inference (Phase P10).

Combines the frozen Track A retrieval pipeline (embedding -> Chroma -> top-k
chunks) with the official Track B LoRA adapter for generation. Retrieved context
is the authoritative knowledge source; the adapter only shapes behaviour. This is
an engineering implementation only — no benchmark run, no metrics (that is P11).

Environment note: retrieval requires chromadb/sentence-transformers (miniconda
Python 3.13); MLX generation requires mlx_lm (CommandLineTools/Xcode Python 3.9).
Because no single interpreter has both, Track C bridges them: retrieve.py runs on
3.13, infer.py runs on 3.9 and obtains retrieved context from retrieve.py.
"""
