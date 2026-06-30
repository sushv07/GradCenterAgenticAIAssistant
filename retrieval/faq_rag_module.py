"""
faq_rag_module.py
Semantic FAQ RAG using LangChain + Chroma + HuggingFace embeddings.

Replaces hardcoded-intent faq_rag.py with vector-similarity retrieval over
ALL FAQ entries scraped live from the CSULB Graduate Center FAQ page.
No intents, no hardcoded answers — the embedding model finds the closest
FAQ card for any query.

Usage:
    from retrieval.faq_rag_module import faq_rag_lookup
    result = faq_rag_lookup("I don't know where to start")
    # {"guidance": "- You can [request an appointment](url)...", "source": "..."}
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from contracts.response_types import FaqRagResult
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from gradcenter_logging import emit
from rag.store import get_embeddings as _get_embeddings
from config.settings import (
    FAQ_VECTORSTORE_TTL_SECONDS as _VECTORSTORE_TTL,
    RETRIEVAL_MIN_RELEVANCE as _MIN_RELEVANCE,
)
from utils.retry import retry_call


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FAQ_URL  = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"
_BASE_URL = "https://www.csulb.edu"

# Vector store cache (rebuilt every hour so page changes are picked up)
_VECTORSTORE: Optional[Chroma] = None
_VECTORSTORE_BUILT_AT: float = 0.0
# _VECTORSTORE_TTL / _MIN_RELEVANCE now live in config/settings.py (Phase 5A),
# imported above under their original local names. Relevance score threshold —
# similarity_search_with_relevance_scores returns scores in [0, 1] where
# 1.0 = perfect match; queries scoring below this are "not covered by FAQ".

# Phase 4C: embeddings model is no longer instantiated here. It's loaded once
# by rag.store and shared via rag.store.get_embeddings() — same model name and
# kwargs ("all-MiniLM-L6-v2", device="cpu", normalize_embeddings=True), so
# this changes nothing about embedding output, only avoids a second load.


# ---------------------------------------------------------------------------
# 1. FAQ page scraper
# ---------------------------------------------------------------------------

def _extract_links(block: Tag) -> list[dict[str, str]]:
    """
    Extract all <a href> tags from a FAQ answer block.
    Resolves relative URLs; skips anchors and javascript hrefs.
    Returns a list of {"text": ..., "url": ...} dicts.
    """
    links: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for a in block.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True).rstrip(".,;:")

        if not href or not text:
            continue
        if href.startswith("#") or href.lower().startswith("javascript"):
            continue

        full_url = urljoin(_BASE_URL, href)
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            links.append({"text": text, "url": full_url})

    return links


def _fetch_faq_entries() -> list[dict]:
    """
    Fetch the CSULB FAQ page and extract ALL FAQ entries.

    Page structure (accordion):
        <div class="card">
            <div class="card-header">
                <h2 class="accordion-heading">QUESTION TEXT</h2>
            </div>
            <div class="collapse">ANSWER BODY WITH LINKS</div>
        </div>

    Returns:
        [{"question": "...", "answer": "...", "links": [...]}, ...]
    """
    def _fetch() -> requests.Response:
        resp = requests.get(
            _FAQ_URL,
            timeout=10,
            headers={"User-Agent": "CSULB-GradAssistant/2.0"},
        )
        resp.raise_for_status()
        return resp

    # Phase 6B: connection/timeout failures are retried before giving up;
    # everything else (including an HTTP error response) still falls
    # straight through to the existing except-and-return-[] fallback.
    try:
        resp = retry_call(_fetch, operation="faq_rag.fetch_page")
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    entries: list[dict] = []

    for h2 in soup.find_all("h2", class_="accordion-heading"):
        question_text = h2.get_text(separator=" ", strip=True)

        card_header = h2.parent
        card = card_header.parent if card_header else None
        if not card:
            continue

        collapse = card.find("div", class_="collapse")
        if not collapse:
            continue

        answer_raw = collapse.get_text(separator=" ", strip=True)
        answer_text = re.sub(r"\s+", " ", answer_raw).strip()

        links = _extract_links(collapse)

        entries.append({
            "question": question_text,
            "answer":   answer_text,
            "links":    links,
        })

    return entries


# ---------------------------------------------------------------------------
# 2. Document builder
# ---------------------------------------------------------------------------

def _build_documents(entries: list[dict]) -> list[Document]:
    """
    Convert FAQ entries into LangChain Documents.

    page_content  = "Q: <question>\nA: <answer>"
                    Leading "N. " numbering is stripped from question text
                    so the splitter never breaks on "Q: 8." mid-sentence.

    metadata      = {
        "question":   clean question string,
        "answer":     full answer string  (always available for formatting,
                      regardless of which sub-chunk the search matched),
        "links_json": JSON-serialised list[{"text", "url"}]
                      (Chroma metadata only supports scalar values)
    }
    """
    docs: list[Document] = []

    for entry in entries:
        # Strip leading "N. " numbering ("1. ", "12. " etc.) from question text
        question_clean = re.sub(r"^\d+\.\s*", "", entry["question"]).strip()
        page_content   = f"Q: {question_clean}\nA: {entry['answer']}"
        metadata = {
            "question":   question_clean,
            "answer":     entry["answer"],            # full text — always usable
            "links_json": json.dumps(entry["links"]), # serialise for Chroma
        }
        docs.append(Document(page_content=page_content, metadata=metadata))

    return docs


# ---------------------------------------------------------------------------
# 3. Vector store (cached)
# ---------------------------------------------------------------------------

def _build_vectorstore() -> Optional[Chroma]:
    """
    Fetch FAQ entries → build Documents → split → embed → store in Chroma.
    Returns the Chroma instance or None if the page was unreachable.
    """
    entries = _fetch_faq_entries()
    if not entries:
        return None

    docs = _build_documents(entries)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    splits = splitter.split_documents(docs)

    embeddings = _get_embeddings()

    # In-memory Chroma with cosine distance so relevance scores are in [0, 1].
    # Without this, Chroma defaults to L2 distance and similarity_search_with_
    # relevance_scores returns values outside [0, 1], making threshold checks
    # unreliable.
    vectorstore = Chroma.from_documents(
        splits,
        embeddings,
        collection_metadata={"hnsw:space": "cosine"},
    )
    return vectorstore


def _get_vectorstore() -> Optional[Chroma]:
    """Return the cached vector store, rebuilding when the TTL has expired."""
    global _VECTORSTORE, _VECTORSTORE_BUILT_AT

    now = time.monotonic()
    if _VECTORSTORE is None or (now - _VECTORSTORE_BUILT_AT) > _VECTORSTORE_TTL:
        _faq_trigger = "process_start" if _VECTORSTORE is None else "ttl_expired"
        _faq_t0 = time.perf_counter()

        emit("store.lifecycle", level="WARNING",
             store_type="faq_rag", lifecycle_event="build_start",
             trigger=_faq_trigger)

        _VECTORSTORE = _build_vectorstore()
        _VECTORSTORE_BUILT_AT = now

        _faq_elapsed = round((time.perf_counter() - _faq_t0) * 1000, 1)
        if _VECTORSTORE is not None:
            try:
                _faq_n = _VECTORSTORE._collection.count()
            except Exception:
                _faq_n = None
            _faq_kw = {"num_chunks": _faq_n} if _faq_n is not None else {}
            emit("store.lifecycle", level="WARNING",
                 store_type="faq_rag", lifecycle_event="build_complete",
                 trigger=_faq_trigger, elapsed_ms=_faq_elapsed, **_faq_kw)
        else:
            emit("store.lifecycle", level="ERROR",
                 store_type="faq_rag", lifecycle_event="build_failed",
                 trigger=_faq_trigger, elapsed_ms=_faq_elapsed,
                 error="_build_vectorstore() returned None")

    return _VECTORSTORE


# ---------------------------------------------------------------------------
# 4. Guidance formatter
# ---------------------------------------------------------------------------

def _format_guidance(answer_text: str, links: list[dict[str, str]]) -> str:
    """
    Build a markdown bullet list from the FAQ answer text.

    Each sentence (up to 4) becomes a bullet point.
    Links that appear in a sentence are embedded as [text](url).
    Output is compatible with st.markdown() — do NOT embed inside an HTML
    <div> or the link syntax will display as raw text.

    Example:
        - You can [request an appointment](url) with a Grad Center Coordinator.
        - Attend one of the [Grad School 101 workshops](url) each semester.
    """
    sentences = re.split(r"(?<=[.!?])\s+", answer_text.strip())

    bullets: list[str] = []
    for sentence in sentences[:4]:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Embed each link as [text](url) where the anchor text appears
        for link in links:
            anchor  = re.escape(link["text"])
            pattern = anchor + r"\s*[.,;:]?"
            md      = f"[{link['text']}]({link['url']})"
            sentence = re.sub(pattern, md, sentence, count=1, flags=re.IGNORECASE)

        # Clean up spacing artifacts
        sentence = re.sub(r"\s+([.,;:])", r"\1", sentence)   # no space before punctuation
        sentence = re.sub(r"\]\s+\(", "](", sentence)        # no space inside ](url)
        sentence = re.sub(r"\)([A-Za-z])", r") \1", sentence) # space after )(word)
        bullets.append(f"- {sentence}")

    # Fallback: one bullet per link if no sentences were extracted
    if not bullets and links:
        bullets = [f"- [{link['text']}]({link['url']})" for link in links]

    return "\n".join(bullets)


# ---------------------------------------------------------------------------
# 5. Public API
# ---------------------------------------------------------------------------

def faq_rag_lookup(query: str) -> Optional[FaqRagResult]:
    """
    Semantic FAQ lookup using vector similarity (no hardcoded intents).

    Embeds the query with all-MiniLM-L6-v2, finds the closest FAQ chunks
    in Chroma, and returns formatted guidance with embedded markdown links.

    Returns:
        {
            "guidance": "bullet-list markdown with [text](url) links",
            "source":   "https://www.csulb.edu/graduate-center/..."
        }
        or None if no sufficiently relevant FAQ entry is found.
    """
    if not query or not query.strip():
        return None

    vectorstore = _get_vectorstore()
    if not vectorstore:
        emit("faq_rag.query", level="ERROR",
             store_available=False, found=False, num_results=0,
             top_score=0.0, threshold_passed=False, elapsed_ms=0.0)
        return None

    # Retrieve top-2 chunks with cosine relevance scores in [0, 1]
    # (requires Chroma built with hnsw:space=cosine — see _build_vectorstore)
    _t0 = time.perf_counter()
    results = vectorstore.similarity_search_with_relevance_scores(query, k=2)
    _faq_elapsed = round((time.perf_counter() - _t0) * 1000, 1)

    if not results:
        emit("faq_rag.query", level="WARNING",
             store_available=True, found=False, num_results=0,
             top_score=0.0, threshold_passed=False, elapsed_ms=_faq_elapsed)
        return None

    top_doc, top_score = results[0]

    # Reject weak matches (query is outside the FAQ's domain)
    if top_score < _MIN_RELEVANCE:
        emit("faq_rag.query", level="WARNING",
             store_available=True, found=False, num_results=len(results),
             top_score=round(top_score, 4), threshold_passed=False,
             elapsed_ms=_faq_elapsed)
        return None

    # Always use the full answer stored in metadata rather than the raw chunk.
    # A chunk may contain only the "Q: ..." line with no answer body if the
    # Q+A was longer than chunk_size — using metadata["answer"] guarantees we
    # always have the complete, well-formed answer text for formatting.
    answer_text = top_doc.metadata.get("answer", "")
    if not answer_text:
        # Fallback: parse from chunk content if metadata is somehow empty
        content = top_doc.page_content
        answer_text = content.split("\nA: ", 1)[1] if "\nA: " in content else content

    # Deserialise links from Chroma metadata (stored as JSON string)
    links_json = top_doc.metadata.get("links_json", "[]")
    try:
        links = json.loads(links_json)
    except (json.JSONDecodeError, TypeError):
        links = []

    guidance = _format_guidance(answer_text, links)

    emit("faq_rag.query", level="INFO",
         store_available=True, found=True, num_results=len(results),
         top_score=round(top_score, 4), threshold_passed=True,
         matched_question=top_doc.metadata.get("question", ""),
         elapsed_ms=_faq_elapsed)
    return {
        "guidance": guidance,
        "source":   _FAQ_URL,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Query: ").strip()
    print(f"Building vector store from {_FAQ_URL} …")
    result = faq_rag_lookup(q)

    if result is None:
        print("No FAQ guidance found for that query.")
    else:
        print("\nGuidance:")
        print(result["guidance"])
        print(f"\nSource: {result['source']}")
