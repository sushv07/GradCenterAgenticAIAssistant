"""
rag/store.py
Manages the persistent ChromaDB vector store for the CSULB RAG pipeline.

Why persistent ChromaDB instead of in-memory Chroma (like faq_rag_module.py):

    faq_rag_module.py calls Chroma.from_documents() WITHOUT a persist_directory.
    Every time the Streamlit app restarts — or every hour when the TTL fires —
    it re-downloads the FAQ page, re-splits all chunks, and re-embeds them.
    With one FAQ page (~50 chunks) this takes ~5–10 seconds.

    With 4 pages (~150+ chunks), the same pattern would cost 30–60 seconds on
    every cold start, making the app feel broken on first load.

    This module writes embeddings to ./chroma_db/ after the first build.
    ChromaDB reads pre-computed vectors from disk on subsequent starts:
    typically under 1 second regardless of corpus size.

    Rebuild is triggered only when:
      a) The ./chroma_db/ directory doesn't exist yet  (first run)
      b) The TTL file (.last_built) is older than STORE_TTL seconds (default 24h)
      c) force_rebuild=True is passed explicitly

TTL design:
    A plain timestamp file (.last_built) is written after each successful build.
    We compare its mtime (OS file modification time, wall-clock) against the
    current wall-clock time.  This is robust across process restarts, unlike
    time.monotonic() which resets when the process exits.

Collection design:
    One collection ("csulb_grad_center") stores all chunks from all 4 sources.
    page_type metadata enables filtered retrieval per source when needed.
    cosine distance (hnsw:space=cosine) ensures similarity scores in [0, 1].

Embedding model:
    all-MiniLM-L6-v2 — same as faq_rag_module.py.  384-dimensional embeddings,
    fast on CPU, good semantic quality for English academic text.
    Loaded once as a process-level singleton to avoid repeated model downloads.
"""

from __future__ import annotations

import shutil
import time
from typing import Optional

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

from gradcenter_logging import emit
from config.settings import (
    CHROMA_DIR,
    CHROMA_COLLECTION_NAME as COLLECTION_NAME,
    EMBEDDING_MODEL,
    EMBEDDING_DEVICE,
    EMBEDDING_NORMALIZE,
    CHROMA_STORE_TTL_SECONDS as STORE_TTL,
)

# ---------------------------------------------------------------------------
# Paths and configuration
# ---------------------------------------------------------------------------
# CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL, STORE_TTL now live in
# config/settings.py (Phase 5A) — imported above under their original local
# names so nothing else in this file (or any future caller) needs to change.

# Timestamp file written after each successful build.
# Its mtime (OS modification time) is used for TTL checks.
_TIMESTAMP_FILE = CHROMA_DIR / ".last_built"

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------
# These are held in memory for the lifetime of the Python process.
# Streamlit re-runs the script on each interaction but doesn't restart the
# Python process, so these survive across user queries within a session.

_STORE:           Optional[Chroma]               = None
_EMBEDDINGS:      Optional[HuggingFaceEmbeddings] = None
# Set to True once the in-memory _STORE has been confirmed to contain
# program_application chunks.  Prevents the check from running on every query
# while still catching a stale store loaded before discovery was implemented.
_STORE_VALIDATED: bool                           = False


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def _get_embeddings() -> HuggingFaceEmbeddings:
    """
    Return the shared HuggingFace embeddings model, loading it once per process.

    Loading the model is the slow step (~2–5 seconds on first call).
    Subsequent calls return the cached instance immediately.
    normalize_embeddings=True produces unit vectors, which is required for
    cosine similarity to return correct scores in [0, 1].
    """
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        print(f"[store] Loading embedding model: {EMBEDDING_MODEL}  (one-time ~2–5s)")
        _EMBEDDINGS = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": EMBEDDING_DEVICE},
            encode_kwargs={"normalize_embeddings": EMBEDDING_NORMALIZE},
        )
    return _EMBEDDINGS


def get_embeddings() -> HuggingFaceEmbeddings:
    """
    Public accessor for the shared embeddings model.

    Phase 4C: faq_rag_module.py uses this instead of instantiating its own
    HuggingFaceEmbeddings — same model name and kwargs, so this only avoids
    loading the model twice; it does not change embedding output.
    """
    return _get_embeddings()


# ---------------------------------------------------------------------------
# TTL helpers
# ---------------------------------------------------------------------------

def _store_is_fresh() -> bool:
    """
    Return True if the on-disk store was built within STORE_TTL seconds.

    Uses the OS mtime of the .last_built timestamp file (wall-clock time),
    which persists across process restarts — unlike time.monotonic().
    Returns False if the timestamp file is missing or unreadable.
    """
    if not _TIMESTAMP_FILE.exists():
        return False
    try:
        mtime = _TIMESTAMP_FILE.stat().st_mtime
        age   = time.time() - mtime
        return age < STORE_TTL
    except OSError:
        return False


def _write_timestamp() -> None:
    """
    Write a timestamp file after a successful build so TTL checks work.
    The file mtime is what we read in _store_is_fresh().
    """
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _TIMESTAMP_FILE.write_text(str(time.time()))


def _chroma_has_data() -> bool:
    """
    Return True if ChromaDB appears to have been populated on disk.
    ChromaDB writes chroma.sqlite3 on its first persist call.
    """
    return (CHROMA_DIR / "chroma.sqlite3").exists()


def check_store_on_disk() -> tuple[bool, str]:
    """
    Passively verify the Chroma vector store data is present on disk.

    Returns (ok, detail_if_not_ok). Never loads the embedding model, never
    instantiates Chroma. Use this for lightweight readiness probes that must
    not trigger ML initialization.

    A successful check means the store has been built at least once and the
    data files are present. It does NOT guarantee the store is within TTL or
    that the current process has loaded it — those are handled at retrieval
    time when get_or_build_store() runs normally.
    """
    if not CHROMA_DIR.exists():
        return False, f"chroma_db directory not found: {CHROMA_DIR}"
    if not (CHROMA_DIR / "chroma.sqlite3").exists():
        return False, "chroma.sqlite3 not present — store has not been built yet"
    return True, ""


def _store_has_program_pages(store: "Chroma") -> bool:
    """
    Return True if the store contains at least one program_application chunk.

    A store built before program discovery was implemented will have 0 such
    chunks (only faq / deadlines / eligibility / application_process).  We use
    this check to self-heal stale stores that are still within TTL but lack the
    program_application content that discovery now provides.

    Uses a limit=1 get() to avoid loading the whole collection — O(1).
    """
    try:
        result = store._collection.get(
            where={"page_type": {"$eq": "program_application"}},
            limit=1,
            include=[],
        )
        return len(result.get("ids", [])) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _clear_chroma_dir_contents() -> None:
    """
    Delete every file and subdirectory inside CHROMA_DIR without removing
    CHROMA_DIR itself.

    shutil.rmtree(CHROMA_DIR) raises OSError EBUSY on Linux when CHROMA_DIR
    is a mount point (e.g. a Render persistent disk).  Deleting the contents
    in a loop leaves the mount point intact while still giving Chroma a clean
    slate for the next from_documents() write.
    """
    for item in CHROMA_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def build_vector_store(documents: list) -> Chroma:
    """
    Embed documents and persist them in ChromaDB on disk.

    This is the write path — it fully replaces the existing collection.
    To prevent duplicate embeddings on repeated builds, the existing
    chroma_db/ directory is cleared before writing new data.

    Args:
        documents: List of LangChain Document objects from chunking.chunk_documents().

    Returns:
        The loaded Chroma instance (backed by the newly written on-disk store).

    Raises:
        RuntimeError: if documents is empty or embedding fails.
    """
    global _STORE, _STORE_VALIDATED

    if not documents:
        raise RuntimeError("[store] Cannot build vector store: document list is empty")

    # Clear existing data to prevent duplicate embeddings on rebuild.
    # Uses _clear_chroma_dir_contents() instead of shutil.rmtree(CHROMA_DIR)
    # so the directory itself is never removed — required when CHROMA_DIR is a
    # Render persistent disk mount point (rmdir raises OSError EBUSY on Linux).
    if CHROMA_DIR.exists():
        print(f"[store] Clearing existing store at {CHROMA_DIR} before rebuild")
        _clear_chroma_dir_contents()
    else:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    embeddings = _get_embeddings()

    print(f"[store] Embedding {len(documents)} chunks → {CHROMA_DIR}  (this may take ~30–60s)")

    # Delegate embed + index to the shared Knowledge Ingestion Pipeline's Chroma
    # adapter (rag/pipeline_adapters/chroma_indexer.py). It issues the same
    # Chroma.from_documents(..., collection_metadata={"hnsw:space": "cosine"})
    # call this method used to make directly, reusing the process embeddings
    # singleton — so the on-disk store the retriever reads is unchanged. Store
    # lifecycle (clearing, timestamp, caching) stays here.
    from rag.pipeline_adapters.wiring import production_indexer
    store = production_indexer(embeddings=embeddings).build_from_langchain_documents(documents)

    _write_timestamp()
    _STORE = store
    _STORE_VALIDATED = True   # a freshly built store always has program pages

    print(f"[store] ✓ Vector store built and persisted  ({len(documents)} chunks)")
    return store


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_vector_store() -> Optional[Chroma]:
    """
    Load an existing ChromaDB collection from disk.

    Returns None if the store does not exist (not yet built).

    Loading from disk is fast (<1s) because embeddings are pre-computed.
    The embedding model must be the same as when the store was built.
    If EMBEDDING_MODEL was changed since the last build, call invalidate_store()
    first to force a full rebuild with the new model.
    """
    if not _chroma_has_data():
        return None

    try:
        embeddings = _get_embeddings()
        store = Chroma(
            persist_directory=str(CHROMA_DIR),
            collection_name=COLLECTION_NAME,
            # NOTE: the constructor uses `embedding_function`, not `embedding`
            # (different from Chroma.from_documents which uses `embedding`).
            # This is a LangChain API inconsistency — use the correct name here.
            embedding_function=embeddings,
        )
        print(f"[store] Loaded existing vector store from {CHROMA_DIR}")
        return store
    except Exception as exc:
        print(f"[store] Failed to load vector store: {exc}")
        return None


# ---------------------------------------------------------------------------
# Get or build (main entry point)
# ---------------------------------------------------------------------------

def get_or_build_store(
    pages: Optional[list] = None,
    force_rebuild: bool = False,
) -> Optional[Chroma]:
    """
    Return the active vector store — loading from disk if fresh, rebuilding if stale.

    This is the primary entry point.  Callers (retriever.py, app.py) always
    call this rather than build_vector_store() or load_vector_store() directly.

    Decision logic:
        1. If _STORE is already in memory AND not force_rebuild → return it.
        2. If force_rebuild=True → skip to step 4 (full rebuild).
        3. If on-disk store is fresh (within TTL) → load from disk.
        4. Otherwise (stale or missing) → ingest → chunk → embed → persist.

    Args:
        pages:         Pre-ingested page dicts (list[dict] from ingest_pages()).
                       If None and a rebuild is needed, ingest_pages() is called
                       automatically.  Pass pre-ingested pages to avoid re-fetching
                       URLs when you've already fetched them (e.g. in tests).
        force_rebuild: If True, always rebuild from fresh data regardless of TTL.
                       Useful for: manual refresh, content updates, model change.

    Returns:
        Chroma instance or None if ingestion or building fails.
    """
    global _STORE, _STORE_VALIDATED

    # 1. Return the in-process cached instance (fastest path).
    # Before trusting the cached store, validate it contains program_application
    # chunks exactly once per process.  This catches the case where the app is
    # running with a stale _STORE that was built before discovery was implemented
    # (only has faq/deadlines/eligibility/application_process, 0 program pages).
    # _STORE_VALIDATED is set to True after the first successful check so
    # subsequent queries skip it — O(1) on every call after the first.
    # Track why a rebuild is needed (set before reaching the rebuild block).
    _rebuild_trigger = ""

    if _STORE is not None and not force_rebuild:
        if not _STORE_VALIDATED:
            if _store_has_program_pages(_STORE):
                _STORE_VALIDATED = True
                return _STORE
            # Stale in-memory store — clear it and fall through to rebuild
            print(
                "[store] In-memory store has no program_application chunks "
                "(built before discovery) — clearing and rebuilding"
            )
            emit("store.lifecycle", level="WARNING",
                 store_type="chroma", lifecycle_event="validation_triggered",
                 trigger="missing_program_pages")
            _STORE = None
            _rebuild_trigger = "missing_program_pages"
        else:
            return _STORE

    # 2. Try loading from disk if the store is within its TTL
    if not force_rebuild and _store_is_fresh():
        store = load_vector_store()
        if store is not None:
            # Validate the store includes program_application chunks.
            # A store built before discovery was implemented only has the 4
            # base page types and will never return program-specific results.
            # Detect this case and fall through to a rebuild even within TTL.
            if not _store_has_program_pages(store):
                print(
                    "[store] Loaded store has no program_application chunks "
                    "(built before discovery) — triggering rebuild"
                )
                emit("store.lifecycle", level="WARNING",
                     store_type="chroma", lifecycle_event="validation_triggered",
                     trigger="missing_program_pages")
                _rebuild_trigger = "missing_program_pages"
                # Don't cache the incomplete store; let rebuild run below.
            else:
                try:
                    _chunk_count = store._collection.count()
                except Exception:
                    _chunk_count = None
                _lc_kw = {"num_chunks": _chunk_count} if _chunk_count is not None else {}
                emit("store.lifecycle", level="INFO",
                     store_type="chroma", lifecycle_event="load_complete",
                     trigger="process_start", **_lc_kw)
                _STORE = store
                _STORE_VALIDATED = True  # disk store confirmed to have program pages
                return store
        # Load failed (e.g. corrupt file) — fall through to rebuild

    # 3. Rebuild from scratch — determine trigger if not already set
    if not _rebuild_trigger:
        if force_rebuild:
            _rebuild_trigger = "force_rebuild"
        elif not _chroma_has_data():
            _rebuild_trigger = "first_run"
        else:
            _rebuild_trigger = "ttl_expired"

    print("[store] Rebuilding vector store from source pages ...")

    # Capture TTL age for ttl_expired trigger (helps debug how stale the store was)
    _ttl_kw: dict = {}
    if _rebuild_trigger == "ttl_expired" and _TIMESTAMP_FILE.exists():
        try:
            _ttl_kw["ttl_age_s"] = round(time.time() - _TIMESTAMP_FILE.stat().st_mtime, 1)
        except OSError:
            pass

    emit("store.lifecycle", level="WARNING",
         store_type="chroma", lifecycle_event="build_start",
         trigger=_rebuild_trigger, **_ttl_kw)
    _build_t0 = time.perf_counter()

    try:
        # Lazy import to avoid circular dependencies:
        # store.py ← retriever.py ← (app.py at runtime)
        # ingestion and chunking are only imported when a build is needed.
        from rag.ingestion import ingest_pages
        from rag.chunking import chunk_documents

        if pages is None:
            # use_discovery=True: program pages are discovered and classified
            # automatically from the index page instead of using the static
            # PROGRAM_SOURCES list with hardcoded content_category values.
            pages = ingest_pages(use_discovery=True)

        if not pages:
            print("[store] No pages ingested — cannot build vector store")
            return None

        documents = chunk_documents(pages)

        # Phase 5 — unify master's knowledge into the SAME production build.
        # Config-gated (MASTERS_INGESTION_ENABLED, default off) and fail-safe:
        # returns [] when disabled or if acquisition errors, so the base build is
        # never broken. Master's docs are chunked with the same production chunker
        # and indexed by the same build_vector_store call — one unified collection,
        # no separate command, no duplicate index path.
        from rag.masters_ingest import masters_build_documents
        documents = list(documents) + masters_build_documents()

        if not documents:
            print("[store] No chunks produced — cannot build vector store")
            return None

        store = build_vector_store(documents)

        _build_elapsed = round((time.perf_counter() - _build_t0) * 1000, 1)
        try:
            _built_count = store._collection.count()
        except Exception:
            _built_count = len(documents)
        emit("store.lifecycle", level="WARNING",
             store_type="chroma", lifecycle_event="build_complete",
             trigger=_rebuild_trigger, elapsed_ms=_build_elapsed,
             num_chunks=_built_count)

        _STORE = store
        return store

    except Exception as exc:
        _build_elapsed = round((time.perf_counter() - _build_t0) * 1000, 1)
        emit("store.lifecycle", level="ERROR",
             store_type="chroma", lifecycle_event="build_failed",
             trigger=_rebuild_trigger, elapsed_ms=_build_elapsed,
             error=str(exc)[:200], error_type=type(exc).__name__)
        print(f"[store] Error during build: {exc}")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------

def invalidate_store() -> None:
    """
    Clear the in-process cache and remove the TTL timestamp.

    The next call to get_or_build_store() will trigger a full rebuild.

    Use this when:
      - CSULB pages are known to have updated (e.g. new deadlines published)
      - EMBEDDING_MODEL is changed (requires re-embedding with new model)
      - The chroma_db/ directory is manually deleted
    """
    global _STORE, _STORE_VALIDATED
    _STORE = None
    _STORE_VALIDATED = False
    if _TIMESTAMP_FILE.exists():
        try:
            _TIMESTAMP_FILE.unlink()
        except OSError:
            pass
    print("[store] Store cache invalidated — next query will trigger a full rebuild")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Build (or verify) the vector store from the command line."""
    import sys

    print("=" * 60)
    print("CSULB RAG Store — build / verify")
    print("=" * 60)

    rebuild = "--rebuild" in sys.argv

    if rebuild:
        print("\nForce-rebuild requested (--rebuild flag).")
        invalidate_store()

    store = get_or_build_store(force_rebuild=rebuild)

    if store is None:
        print("\n✗ Failed to build or load the vector store.")
        sys.exit(1)

    # Quick stats via the underlying ChromaDB client
    try:
        collection = store._collection
        count = collection.count()
        print(f"\n✓ Vector store ready: {count} chunks in collection '{COLLECTION_NAME}'")
        print(f"  Location: {CHROMA_DIR}")
        print(f"  Fresh:    {_store_is_fresh()}")
    except Exception as exc:
        print(f"\n✓ Vector store loaded (could not read stats: {exc})")
