"""
ingestion/
Production-side data-acquisition tooling that converts official CSULB sources
into validated domain.programs.CanonicalProgram records.

This package MAY use infrastructure (HTTP, HTML parsing, filesystem); it is NOT
part of the engine-independent domain layer. It imports domain.programs
read-only and is never imported BY the domain. It performs no retrieval,
embedding, Chroma, RAG, experiment, or fine-tuning work.
"""
