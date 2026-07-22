# Master's Knowledge → Shared Pipeline — Pilot Ingestion Report

Isolated pilot store (not the deployed production collection); same code path.

## Pipeline statistics (run 1)

- documents processed: 29
- documents indexed: 29
- documents skipped: 0
- chunks created: 476
- chunks indexed (embeddings generated): 476
- avg chunks/document: 16.41
- avg chunk size: 376.6 chars
- vector entries (collection count): 476
- validation failures: 0 · warnings: 0
- duplicates detected: 0

## Idempotency (run 2, same docs)

- vector entries after run 1: 476
- vector entries after run 2: 476
- delta: 0  (0 = no duplicate knowledge created)
- run2 chunks_indexed: 476 (upserted in place)

## Sample stored chunk metadata

- {"program_name": "Business Administration", "degree": "Evening MBA", "degree_level": "Masters", "content_type": "supplemental_application", "source_url": "https://www.csulb.edu/cob-graduate-programs/admissions-faqs", "parent_program_url": "https://www.csulb.edu/cob-graduate-programs/mba-programs/evening-mba", "canonical_document_id": "2e6e54fd", "chunk_id": "2e6e54fd_0000", "chunk_index": 0, "page_type": "masters_program"}
- {"program_name": "Business Administration", "degree": "Evening MBA", "degree_level": "Masters", "content_type": "supplemental_application", "source_url": "https://www.csulb.edu/cob-graduate-programs/admissions-faqs", "parent_program_url": "https://www.csulb.edu/cob-graduate-programs/mba-programs/evening-mba", "canonical_document_id": "2e6e54fd", "chunk_id": "2e6e54fd_0001", "chunk_index": 1, "page_type": "masters_program"}
- {"program_name": "Business Administration", "degree": "Evening MBA", "degree_level": "Masters", "content_type": "supplemental_application", "source_url": "https://www.csulb.edu/cob-graduate-programs/admissions-faqs", "parent_program_url": "https://www.csulb.edu/cob-graduate-programs/mba-programs/evening-mba", "canonical_document_id": "2e6e54fd", "chunk_id": "2e6e54fd_0002", "chunk_index": 2, "page_type": "masters_program"}
