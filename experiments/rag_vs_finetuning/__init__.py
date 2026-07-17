"""
experiments/rag_vs_finetuning/
Isolated RAG-vs-fine-tuning experiment area. Reads frozen canonical records
(read-only) and produces retrieval-neutral projection artifacts. It never
imports production RAG, routing, orchestration, LangChain, Chroma, embeddings,
or model-serving code, and production code never imports this package.
"""
