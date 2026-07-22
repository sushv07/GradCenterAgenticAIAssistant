"""
ingestion/pipeline/loaders/
Source adapters: turn a specific knowledge source into KnowledgeDocuments.

A loader is the ONLY source-aware code in the pipeline. Adding a new knowledge
source (doctoral programs, policies, FAQs, deadlines, advisors, funding, …) means
writing a new loader here — chunking, embedding, validation, and indexing stay
untouched. Loaders are pure (stdlib + domain/pipeline only); no infra.
"""
from ingestion.pipeline.loaders.pages import PageDictLoader, page_to_document

__all__ = ["PageDictLoader", "page_to_document"]
