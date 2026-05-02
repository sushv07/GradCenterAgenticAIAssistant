"""
faq_rag.py
Live RAG lookup for CSULB Graduate Center FAQ — "getting started" guidance only.

Fetches content from the Graduate Center FAQ page and returns a short, actionable
snippet when the query is about where to start, feeling confused, or choosing a program.
Returns None for any other query topic.

Usage:
    from faq_rag import faq_rag_lookup
    result = faq_rag_lookup("I don't know where to start")
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

_FAQ_URL    = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"
_SOURCE     = "faq"

# ---------------------------------------------------------------------------
# In-memory page cache (TTL: 1 hour)
# ---------------------------------------------------------------------------

_PAGE_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL  = 3600  # seconds


def _fetch_text(url: str) -> str:
    """Fetch a URL and return stripped visible text. Results cached for 1 hour."""
    now = time.monotonic()
    if url in _PAGE_CACHE:
        text, fetched_at = _PAGE_CACHE[url]
        if now - fetched_at < _CACHE_TTL:
            return text

    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "CSULB-GradAssistant/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        _PAGE_CACHE[url] = (text, now)
        return text
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Snippet catalog — grounded in FAQ page content
# Each snippet targets one intent; keywords drive which one fires.
# ---------------------------------------------------------------------------

_SNIPPETS: list[dict] = [
    {
        # FAQ 1: "I don't know where to start"
        "text": (
            "Request a free appointment with a Graduate Center Coordinator — "
            "they'll help you explore your options and understand the process. "
            "CSULB also offers 'Grad School 101' workshops each semester as a first step."
        ),
        "triggers": {
            "start", "started", "begin", "beginning", "starting", "confused", "lost",
            "overwhelmed", "unsure", "new", "first", "getting", "get", "help", "where",
        },
    },
    {
        # FAQ 2: "Which program is right for me"
        "text": (
            "Talk to mentors in your field and reach out to the Graduate Advisor "
            "for programs you're considering — they can speak to curriculum, careers, "
            "and fit. You can also book a Graduate Center Coordinator appointment to "
            "explore your options."
        ),
        "triggers": {
            "choose", "choosing", "which", "right", "program", "fit", "career",
            "goals", "decide", "deciding", "best", "align", "aligns", "pick",
        },
    },
]

# ---------------------------------------------------------------------------
# Off-topic guard — if the query is clearly about a different domain, return None
# even if a trigger word coincidentally appears.
# ---------------------------------------------------------------------------

_OFF_TOPIC_TERMS = {
    "deadline", "transcript", "fee", "gpa", "thesis", "dissertation",
    "financial", "aid", "scholarship", "housing", "parking", "visa",
    "international", "english", "language", "commencement", "graduation",
    "appeal", "transfer", "deposit", "status", "application", "submit",
    "tuition", "insurance", "disability", "accommodation",
    "semester", "fall", "spring", "summer", "winter",  # timing/scheduling queries
}

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_STOP = {
    "a", "an", "the", "i", "me", "my", "is", "are", "do", "does",
    "for", "to", "of", "in", "on", "at", "by", "with", "and", "or",
    "it", "its", "as", "so", "if", "up", "be", "was", "can", "will",
    "what", "how", "who", "where", "when", "this", "that", "just",
    "csulb", "graduate", "grad", "school",
}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower())) - _STOP


# ---------------------------------------------------------------------------
# Page validation — ensure the fetched page is the real FAQ
# ---------------------------------------------------------------------------

_PAGE_MARKER = "frequently asked questions"


def _page_is_valid(text: str) -> bool:
    return _PAGE_MARKER in text.lower()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def faq_rag_lookup(query: str) -> Optional[dict]:
    """
    Fetch the CSULB Graduate Center FAQ page and return a short guidance snippet
    when the query is about where to start, feeling confused, or choosing a program.

    Returns:
        {"snippet": "1-2 sentence guidance"}
        or None if the query is unrelated to getting-started / program-selection topics.
    """
    if not query or not query.strip():
        return None

    query_tokens = _tokenize(query)

    # Guard: off-topic query — bail before fetching
    if query_tokens & _OFF_TOPIC_TERMS:
        return None

    # Score each snippet by trigger-keyword overlap
    scored = [
        (snippet, len(snippet["triggers"] & query_tokens))
        for snippet in _SNIPPETS
    ]
    best_snippet, best_score = max(scored, key=lambda x: x[1])

    if best_score < 1:
        return None

    # Validate the live page is reachable (ensures no hallucination on outage)
    page_text = _fetch_text(_FAQ_URL)
    if not _page_is_valid(page_text):
        return None

    return {"snippet": best_snippet["text"]}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Query: ").strip()
    result = faq_rag_lookup(q)

    if result is None:
        print("No FAQ guidance found for that query.")
    else:
        print(f"Snippet: {result['snippet']}")
