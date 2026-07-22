"""
ingestion/pipeline/documents.py
The KnowledgeDocument — the source-agnostic input to the pipeline.

Every knowledge source (master's programs, doctoral programs, policies, FAQs,
deadlines, advisors, funding, …) is first adapted into a `KnowledgeDocument` by
a loader. The pipeline then operates ONLY on `KnowledgeDocument`s, so adding a
new source is a new loader — not a change to chunking, embedding, or indexing.

`metadata` is an open, source-specific dict of primitive values (str/int/float/
bool). It is copied onto every chunk of the document and ultimately stored flat
in the vector store (ChromaDB does not allow nested metadata), so loaders must
keep values primitive. See `metadata.ChunkMetadata` for the recommended keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ingestion.pipeline.ids import document_id_from_url


@dataclass(frozen=True)
class KnowledgeDocument:
    """One unit of source knowledge, prior to chunking.

    Attributes:
        text:         the full text to be chunked and indexed.
        source_url:   canonical URL/identifier of the source (citation + id seed).
        content_type: coarse source category (e.g. "program_application", "faq",
                      "policy", "deadlines"); mirrored to metadata for filtering.
        document_id:  stable id; defaults to the md5(source_url) prefix.
        metadata:     flat, source-specific primitives copied onto every chunk.
    """

    text: str
    source_url: str
    content_type: str = ""
    document_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Derive a deterministic id when the caller did not supply one.
        if not self.document_id:
            object.__setattr__(self, "document_id", document_id_from_url(self.source_url))

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()
