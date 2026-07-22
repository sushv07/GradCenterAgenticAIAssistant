"""Track B — official fine-tuned (LoRA) evaluation harness (Phase P8.2).

Track B is the *fine-tuned only* condition: the frozen Qwen2.5-7B-Instruct-4bit
base plus the official Track B LoRA adapter (selected in P8.1), evaluated on the
frozen benchmark with retrieval COMPLETELY disabled. No Chroma query, no
embeddings, no retrieved/citation chunk ids.
"""
