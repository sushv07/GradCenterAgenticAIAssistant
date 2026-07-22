"""
rag/pipeline_adapters/
Infrastructure adapters that implement the ingestion.pipeline ports.

These are the concrete, infra-touching backends for the source-agnostic pipeline
defined in `ingestion/pipeline/`:

    recursive_chunker.RecursiveCharacterChunker  → Chunker      (langchain splitter)
    hf_embedder.HuggingFaceEmbeddingBackend      → Embedding    (langchain HF)
    chroma_indexer.ChromaVectorIndex             → VectorIndex  (langchain Chroma)

They live under `rag/` (not `ingestion/`) because `ingestion/` is guarded to stay
infra-free; keeping Chroma/embedding/langchain here preserves that invariant while
production and any future consumer share ONE implementation of each stage.

`build_production_pipeline()` wires them into a ready-to-run KnowledgePipeline
using the production configuration from `config/settings.py`.
"""
from rag.pipeline_adapters.chroma_indexer import ChromaVectorIndex
from rag.pipeline_adapters.hf_embedder import HuggingFaceEmbeddingBackend
from rag.pipeline_adapters.recursive_chunker import RecursiveCharacterChunker
from rag.pipeline_adapters.wiring import production_config, build_production_pipeline

__all__ = [
    "ChromaVectorIndex",
    "HuggingFaceEmbeddingBackend",
    "RecursiveCharacterChunker",
    "production_config",
    "build_production_pipeline",
]
