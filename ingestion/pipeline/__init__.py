"""
ingestion/pipeline/
Source-agnostic Knowledge Ingestion Pipeline (contracts + orchestration).

This subpackage is the reusable, INFRA-FREE core of the production ingestion
pipeline. It owns the vocabulary and the orchestration of the write path —
"how do we turn any knowledge source into retrievable chunks?" — without knowing
anything about Chroma, embeddings, or a specific text splitter.

Layering (ports & adapters):

    ingestion/pipeline/            ← this package: pure contracts + orchestration
        documents.py   KnowledgeDocument (the source-agnostic input)
        ids.py         deterministic document/chunk IDs + content hashes
        metadata.py    the production ChunkMetadata schema + helpers
        ports.py       Chunk, Chunker/EmbeddingBackend/VectorIndex/Loader Protocols
        validator.py   pre-index validation → ValidationIssue list
        config.py      PipelineConfig (declarative tunables)
        pipeline.py    KnowledgePipeline + IngestionSummary (orchestration)
        loaders/       pure adapters: source records → KnowledgeDocument

    rag/pipeline_adapters/         ← the INFRA implementations of the ports
        recursive_chunker.py   (langchain splitter)
        hf_embedder.py         (langchain HuggingFace embeddings)
        chroma_indexer.py      (chromadb / langchain Chroma)

Why the split: `ingestion/` is guarded by an architecture test that forbids
Chroma/embedding/langchain imports anywhere under it (acquisition must stay
infra-free). Keeping the concrete backends in `rag/pipeline_adapters/` honours
that invariant while still giving both the experiment reference and production a
single, shared set of contracts and orchestration to build against.

Imports only stdlib + `domain`/`config`; never langchain, chromadb,
sentence-transformers, rag, retrieval, or experiments.
"""
