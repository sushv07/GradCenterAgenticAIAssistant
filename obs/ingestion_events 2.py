"""
obs/ingestion_events.py
Phase 9D — structured, stage-level ingestion observability events.

Seven events, one per pipeline stage boundary in rag/ingestion.py and
rag/chunking.py:

    ingestion.started       — ingest_pages() called, sources resolved
    ingestion.page_fetched  — HTTP fetch succeeded
    ingestion.page_retry    — first fetch attempt failed, retrying
    ingestion.page_parsed   — HTML parsed into text (or specialist entries)
    ingestion.page_failed   — page skipped due to fetch/parse failure
    ingestion.page_chunked  — page text split into chunks (chunk_documents())
    ingestion.completed     — ingest_pages() finished, totals captured

Each wraps gradcenter_logging.emit() — no second logging system.  The
only fields emitted are deterministic metadata (counts, timings, URLs,
error types). The following are intentionally NEVER logged:
  - raw HTML content of any page
  - cleaned text of any page
  - chunk text
  - embeddings
  - full stack traces (error_type is logged, not the message when it
    could contain raw content)

Why separate from obs/retrieval_events.py:
    Ingestion events describe a WRITE-PATH batch process (building the KB);
    retrieval events describe per-request READ-PATH calls against the built
    KB. They share the same underlying emit() mechanism but are logically
    distinct, emitted from different modules, and read by different
    summaries.

Mirror of obs/retrieval_events.py's design: each helper is a thin
wrapper over emit(), making every call site a single-line statement that
clearly communicates what stage just completed, without any logic embedded
in the helper itself.
"""
from __future__ import annotations

from gradcenter_logging import emit


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def emit_ingestion_started(
    source_count: int,
    use_discovery: bool,
) -> None:
    emit(
        "ingestion.started", level="INFO",
        ingestion_stage="started",
        source_count=source_count,
        use_discovery=use_discovery,
    )


def emit_ingestion_page_fetched(
    url: str,
    page_type: str,
    program_name: str,
    fetch_elapsed_ms: float,
    response_size_bytes: int,
) -> None:
    emit(
        "ingestion.page_fetched", level="INFO",
        ingestion_stage="fetch",
        url=url,
        page_type=page_type,
        program_name=program_name,
        fetch_elapsed_ms=fetch_elapsed_ms,
        response_size_bytes=response_size_bytes,
    )


def emit_ingestion_page_retry(
    url: str,
    error_type: str,
    error: str = "",
) -> None:
    """Emitted from inside fetch_page() when the first HTTP attempt fails
    and the function is about to sleep and retry.  Only url is known at
    this level — page_type and program_name are not passed into fetch_page()."""
    emit(
        "ingestion.page_retry", level="WARNING",
        ingestion_stage="fetch",
        url=url,
        error_type=error_type,
        error=error[:200],
    )


def emit_ingestion_page_parsed(
    url: str,
    page_type: str,
    program_name: str,
    char_count: int,
    parse_elapsed_ms: float,
    entry_count: int = 1,
) -> None:
    """entry_count > 1 indicates the specialist deadlines extractor was used
    and produced multiple per-program entries from a single source URL."""
    emit(
        "ingestion.page_parsed", level="INFO",
        ingestion_stage="parse",
        url=url,
        page_type=page_type,
        program_name=program_name,
        char_count=char_count,
        parse_elapsed_ms=parse_elapsed_ms,
        entry_count=entry_count,
    )


def emit_ingestion_page_failed(
    url: str,
    page_type: str,
    program_name: str,
    stage: str,
    reason: str,
    error_type: str = "",
) -> None:
    """stage: 'fetch' | 'parse'
    reason: 'fetch_failed' | 'parse_failed' | 'short_content'"""
    emit(
        "ingestion.page_failed", level="WARNING",
        ingestion_stage=stage,
        url=url,
        page_type=page_type,
        program_name=program_name,
        reason=reason,
        error_type=error_type,
    )


def emit_ingestion_page_chunked(
    url: str,
    page_type: str,
    program_name: str,
    chunks_generated: int,
    chars_in: int,
    chunk_elapsed_ms: float,
) -> None:
    emit(
        "ingestion.page_chunked", level="INFO",
        ingestion_stage="chunk",
        url=url,
        page_type=page_type,
        program_name=program_name,
        chunks_generated=chunks_generated,
        chars_in=chars_in,
        chunk_elapsed_ms=chunk_elapsed_ms,
    )


def emit_ingestion_completed(
    pages_attempted: int,
    pages_succeeded: int,
    pages_failed: int,
    elapsed_ms: float,
    total_chars: int,
) -> None:
    level = "WARNING" if pages_failed > 0 else "INFO"
    emit(
        "ingestion.completed", level=level,
        ingestion_stage="completed",
        pages_attempted=pages_attempted,
        pages_succeeded=pages_succeeded,
        pages_failed=pages_failed,
        elapsed_ms=elapsed_ms,
        total_chars=total_chars,
    )
