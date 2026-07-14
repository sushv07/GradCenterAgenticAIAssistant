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

Calibrated against live CSULB pages in Phase P3/P3.1: card-based discovery,
main-content overview extraction (boilerplate/nav rejected), advisor email
capture, and a no-fabricated-ISO-date deadline policy (published "Month Day"
text is preserved in ApplicationTerm.deadline_text; the structured `deadline`
stays None until a correct year is known).

Deferred extraction gaps (NOT implemented — future enrichment work; ingestion
represents these honestly as `unknown`/`source_missing` today):
  - STEM designation from program pages (index cards carry no per-card STEM text)
  - college extraction from program pages
  - department extraction from program pages
  - GRE/GMAT "badge"/image-caption requirement extraction
  - University Catalog enrichment (source tier 3)
  - Center for International Education enrichment (source tier 5)
  - official CSULB-hosted PDF enrichment (source tier 7)
"""
