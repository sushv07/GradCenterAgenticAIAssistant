"""
ingestion/masters/
Reusable canonical ingestion foundation for CSULB master's programs.

Two independent stages:
    discovery  — parse the Graduate Studies index into a DiscoveryManifest
    enrichment — normalize discovered + fetched facts into CanonicalProgram

Supporting concerns: injectable fetching, immutable content-hashed snapshots,
conservative extraction, deterministic validation (domain validator), and
file-per-program persistence. No retrieval, Chroma, embeddings, RAG, experiment,
or fine-tuning code lives here.
"""
