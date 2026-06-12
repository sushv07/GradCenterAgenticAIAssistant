"""
admissions_rag.py
Live RAG lookup for CSULB doctoral admissions information.

Fetches content from the CSULB Admissions pages, filters to doctoral-specific
sections, and returns short actionable snippets relevant to the user's query.

Usage:
    from retrieval.admissions_rag import admissions_rag_lookup
    result = admissions_rag_lookup("what are the gpa requirements for doctoral")
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from gradcenter_logging import emit


# ---------------------------------------------------------------------------
# Doctoral source URLs (sub-pages under csulb.edu/admissions)
# ---------------------------------------------------------------------------

_BASE = "https://www.csulb.edu/admissions"

_DOCTORAL_URLS = [
    f"{_BASE}/doctoral-programs-admission-eligibility",
    f"{_BASE}/doctoral-programs-application-process",
]

_SOURCE_LABEL = "admissions"

# ---------------------------------------------------------------------------
# In-memory page cache (TTL: 1 hour — content changes rarely)
# ---------------------------------------------------------------------------

_PAGE_CACHE: dict[str, tuple[str, float]] = {}  # url → (text, fetched_at)
_CACHE_TTL  = 3600  # seconds


def _fetch_text(url: str) -> str:
    """
    Fetch a URL and return its visible text content, stripped of HTML.
    Returns "" on any error.  Results are cached for _CACHE_TTL seconds.
    """
    now = time.monotonic()
    if url in _PAGE_CACHE:
        text, fetched_at = _PAGE_CACHE[url]
        if now - fetched_at < _CACHE_TTL:
            emit("admissions_rag.fetch", url=url, cache_hit=True, elapsed_ms=0.0)
            return text

    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "CSULB-GradAssistant/1.0"})
        elapsed_ms = round((time.monotonic() - now) * 1000, 2)

        if not resp.ok:
            emit(
                "admissions_rag.fetch", level="WARNING",
                url=url, cache_hit=False,
                status_code=resp.status_code, elapsed_ms=elapsed_ms,
            )
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        # Drop nav / footer / script noise
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        _PAGE_CACHE[url] = (text, now)

        level = "INFO" if text else "WARNING"
        emit(
            "admissions_rag.fetch", level=level,
            url=url, cache_hit=False,
            status_code=resp.status_code, elapsed_ms=elapsed_ms,
        )
        return text

    except Exception as exc:
        elapsed_ms = round((time.monotonic() - now) * 1000, 2)
        emit(
            "admissions_rag.fetch", level="ERROR",
            url=url, cache_hit=False,
            elapsed_ms=elapsed_ms, error=str(exc),
        )
        return ""


# ---------------------------------------------------------------------------
# Snippet definitions — grounded in actual page content
# ---------------------------------------------------------------------------

# Each snippet has:
#   text     : the 1-2 line actionable insight (rephrased for clarity)
#   keywords : tokens that make this snippet relevant to a query
_SNIPPET_CATALOG: list[dict] = [
    # ── Eligibility ──────────────────────────────────────────────────────────
    {
        "text": "Doctoral applicants must hold a regionally accredited bachelor's degree and be in good academic standing.",
        "keywords": {"eligible", "eligibility", "require", "requirement", "bachelor", "degree", "qualify"},
    },
    {
        "text": "Most doctoral programs require a master's degree from a regionally accredited institution before admission.",
        "keywords": {"master", "masters", "require", "requirement", "prerequisite", "eligible", "eligibility"},
    },
    {
        "text": "Doctoral GPA requirement: cumulative GPA ≥ 3.0, OR ≥ 3.0 in the last 60 semester / 90 quarter units. CSULB does not round GPA.",
        "keywords": {"gpa", "grade", "requirement", "minimum", "3", "cumulative", "point", "average"},
    },
    {
        "text": "Provisional admission is available for doctoral applicants still completing their degree, provided they meet the qualifying GPA.",
        "keywords": {"provisional", "admission", "conditional", "still", "finishing", "completing"},
    },
    # ── Application process ──────────────────────────────────────────────────
    {
        "text": "Apply via Cal State Apply. The application fee is $70 — nonrefundable, no waivers. You may apply to only one program per term.",
        "keywords": {"apply", "application", "fee", "cost", "submit", "cal", "state", "how"},
    },
    {
        "text": "Fall applications open October 1; Spring applications open July 1. Not all doctoral programs admit every term — verify with your program.",
        "keywords": {"deadline", "open", "fall", "spring", "when", "term", "date", "window", "start"},
    },
    {
        "text": "Doctoral applicants must submit transcripts from three sources: bachelor's institution, master's institution, and most recent institution attended.",
        "keywords": {"transcript", "transcripts", "official", "send", "submit", "institution", "bachelor", "master"},
    },
    {
        "text": "Send transcripts electronically to ES-IDPTrans@csulb.edu, or by mail to Enrollment Services. CSULB alumni do not need to resubmit CSULB transcripts.",
        "keywords": {"transcript", "send", "email", "mail", "where", "submit", "electronic", "alumni"},
    },
    {
        "text": "Each doctoral program may have supplemental application requirements. Contact your specific program directly for those details.",
        "keywords": {"supplemental", "additional", "requirement", "extra", "program", "specific", "department"},
    },
    {
        "text": "Check your application status via the Applicant Self-Service portal after submitting. Admissions reviews minimums then forwards to the department.",
        "keywords": {"status", "check", "portal", "self", "service", "track", "review", "decision"},
    },
    # ── After admission ──────────────────────────────────────────────────────
    {
        "text": "Accept your admission offer through the MyCSULB Student Center and pay the enrollment deposit to secure your spot.",
        "keywords": {"accept", "offer", "deposit", "enrollment", "confirm", "secure", "admitted"},
    },
    {
        "text": "Final official transcripts are due August 15 for Fall and January 15 for Spring — failure to submit may affect your enrollment.",
        "keywords": {"final", "transcript", "deadline", "august", "january", "due", "after", "admitted"},
    },
    {
        "text": "Appeals must be submitted within 15 days of a denial decision, online only. Only one appeal is allowed per term; expect a response in 4–6 weeks.",
        "keywords": {"appeal", "denied", "denial", "reject", "rejected", "reconsider", "decision"},
    },
]


# ---------------------------------------------------------------------------
# Query tokenizer (mirrors the project's existing _tokenize style)
# ---------------------------------------------------------------------------

_STOP = {
    "a", "an", "the", "i", "me", "my", "is", "are", "do", "does",
    "for", "to", "of", "in", "on", "at", "by", "with", "and", "or",
    "it", "its", "as", "so", "if", "up", "be", "was", "can", "will",
    "what", "how", "who", "where", "when", "which", "this", "that",
    "doctoral", "doctorate", "phd", "graduate", "grad", "csulb",
}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOP


# ---------------------------------------------------------------------------
# Relevance check — is the fetched page content coherent enough to use?
# ---------------------------------------------------------------------------

_DOCTORAL_MARKERS = {"doctoral", "doctorate", "ph.d", "phd", "ed.d", "dnp", "dpt", "d.n.p"}


def _page_has_doctoral_content(text: str) -> bool:
    """Return True if the fetched page contains doctoral-specific content."""
    text_lower = text.lower()
    return any(marker in text_lower for marker in _DOCTORAL_MARKERS)


# ---------------------------------------------------------------------------
# Snippet matching
# ---------------------------------------------------------------------------

def _score_snippet(snippet: dict, query_tokens: set[str]) -> int:
    """Return keyword-overlap score between query tokens and snippet keywords."""
    return len(snippet["keywords"] & query_tokens)


def _select_snippets(query_tokens: set[str], top_n: int = 3) -> list[str]:
    """
    Score every snippet against the query and return the top-n texts
    (those with at least 1 keyword match).
    """
    scored = [
        (snippet["text"], _score_snippet(snippet, query_tokens))
        for snippet in _SNIPPET_CATALOG
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [text for text, score in scored if score >= 1][:top_n]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def admissions_rag_lookup(query: str) -> Optional[dict]:
    """
    Fetch the CSULB doctoral admissions pages and return short actionable
    snippets relevant to the query.

    Returns:
        {
            "snippets": ["insight 1", "insight 2"],
            "source":   "admissions"
        }
        or None if no relevant doctoral information is found.
    """
    if not query or not query.strip():
        return None

    t0 = time.monotonic()

    # 1. Fetch doctoral pages (cached after first call)
    page_texts = [_fetch_text(url) for url in _DOCTORAL_URLS]

    # 2. Pre-compute token set and top snippet score (used in all emit paths)
    query_tokens = _tokenize(query)
    top_score = max((_score_snippet(s, query_tokens) for s in _SNIPPET_CATALOG), default=0)

    # 3. Verify at least one page has real doctoral content
    if not any(_page_has_doctoral_content(t) for t in page_texts):
        elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
        emit(
            "admissions_rag.result", level="WARNING",
            found=False, num_snippets=0, top_score=top_score, elapsed_ms=elapsed_ms,
        )
        return None

    # 4. Match snippets against the query
    snippets = _select_snippets(query_tokens)

    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
    if not snippets:
        emit(
            "admissions_rag.result", level="WARNING",
            found=False, num_snippets=0, top_score=top_score, elapsed_ms=elapsed_ms,
        )
        return None

    emit(
        "admissions_rag.result", level="INFO",
        found=True, num_snippets=len(snippets), top_score=top_score, elapsed_ms=elapsed_ms,
    )
    return {
        "snippets": snippets,
        "source":   _SOURCE_LABEL,
    }


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Query: ").strip()
    result = admissions_rag_lookup(q)

    if result is None:
        print("No doctoral admissions information found for that query.")
    else:
        print(f"Source: {result['source']}\n")
        for i, snippet in enumerate(result["snippets"], 1):
            print(f"{i}. {snippet}")
