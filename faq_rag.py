"""
faq_rag.py
Dynamic RAG lookup for the CSULB Graduate Center FAQ page.

Fetches live content, identifies the relevant FAQ card based on query intent,
extracts links directly from the answer block (no hardcoding), and returns a
structured response with markdown-embedded links.

Usage:
    from faq_rag import faq_rag_lookup
    result = faq_rag_lookup("I don't know where to start")
"""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

_FAQ_URL  = "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs"
_BASE_URL = "https://www.csulb.edu"

# ---------------------------------------------------------------------------
# Page cache (TTL: 1 hour) — stores parsed BeautifulSoup objects
# ---------------------------------------------------------------------------

_PAGE_CACHE: dict[str, tuple[BeautifulSoup, float]] = {}
_CACHE_TTL  = 3600


def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch URL and return a cached BeautifulSoup object (1-hour TTL)."""
    now = time.monotonic()
    if url in _PAGE_CACHE:
        soup, fetched_at = _PAGE_CACHE[url]
        if now - fetched_at < _CACHE_TTL:
            return soup

    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "CSULB-GradAssistant/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        _PAGE_CACHE[url] = (soup, now)
        return soup
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

_START_INTENT  = ["start", "confused", "help", "begin", "stuck", "lost"]
_CHOICE_INTENT = ["choose", "which program", "decide", "right for me"]

# Keywords matched against FAQ question heading text
_START_Q_KEYWORDS  = ["where to start", "don't know", "get help", "apply to graduate school"]
_CHOICE_Q_KEYWORDS = ["which program", "right for me", "career goals"]


# ---------------------------------------------------------------------------
# FAQ card finder
# ---------------------------------------------------------------------------

def _find_faq_card(soup: BeautifulSoup, heading_keywords: list[str]) -> Optional[Tag]:
    """
    Find the FAQ card (div.card) whose question heading contains any of
    the given keywords.  Returns the div.collapse answer block or None.

    Page structure (CSULB FAQ accordion):
        <div class="card">
            <div class="card-header">
                <h2 class="accordion-heading">QUESTION TEXT</h2>
            </div>
            <div class="collapse">ANSWER BODY WITH LINKS</div>
        </div>
    """
    kws = [k.lower() for k in heading_keywords]

    for h2 in soup.find_all("h2", class_="accordion-heading"):
        question_text = h2.get_text(separator=" ", strip=True).lower()
        if any(kw in question_text for kw in kws):
            # card-header is h2's parent; card is card-header's parent
            card_header = h2.parent
            card        = card_header.parent if card_header else None
            if card:
                collapse = card.find("div", class_="collapse")
                if collapse:
                    return collapse
    return None


# ---------------------------------------------------------------------------
# Link extractor
# ---------------------------------------------------------------------------

def _extract_links(block: Tag) -> list[dict[str, str]]:
    """
    Extract all anchor links from a FAQ answer block.
    Resolves relative URLs; skips anchors and javascript hrefs.
    Strips trailing punctuation from link text.
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


# ---------------------------------------------------------------------------
# Guidance formatter
# ---------------------------------------------------------------------------

def _format_guidance(block: Tag, links: list[dict[str, str]]) -> str:
    """
    Build a markdown bullet list from the FAQ answer block.

    Each sentence in the answer body becomes its own bullet point.
    Links extracted from the block are embedded as [text](url) within
    the sentence they appear in.

    Output is compatible with st.markdown() — do NOT embed it inside
    an HTML <div> or the link syntax will render as raw text.

    Example output:
        - You can [request an appointment](url) with a Grad Center Coordinator.
        - Attend one of the [Grad School 101 workshops](url) each semester.
    """
    raw = block.get_text(separator=" ", strip=True)
    raw = re.sub(r"\s+", " ", raw).strip()

    sentences = re.split(r"(?<=[.!?])\s+", raw)

    bullets: list[str] = []
    for sentence in sentences[:4]:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Embed each link as [text](url) within this sentence
        for link in links:
            anchor  = re.escape(link["text"])
            pattern = anchor + r"\s*[.,;:]?"
            md      = f"[{link['text']}]({link['url']})"
            sentence = re.sub(pattern, md, sentence, count=1, flags=re.IGNORECASE)

        # Clean up residual spacing artifacts
        sentence = re.sub(r"\s+([.,;:])", r"\1", sentence)
        sentence = re.sub(r"\]\s+\(", "](", sentence)
        bullets.append(f"- {sentence}")

    # Fallback: one bullet per link when no sentences were extracted
    if not bullets and links:
        bullets = [f"- [{link['text']}]({link['url']})" for link in links]

    return "\n".join(bullets)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def faq_rag_lookup(query: str) -> Optional[dict]:
    """
    Dynamically fetch the CSULB Graduate Center FAQ page, find the relevant
    FAQ block based on query intent, extract links from the live answer,
    and return a structured response.

    Intent routing:
      START  → FAQ Q1 "I don't know where to start"
      CHOICE → FAQ Q2 "Which program is right for me"

    Returns:
        {
            "guidance":  "Markdown string with embedded [text](url) links",
            "source":    "https://..."
        }
        or None if intent doesn't match or page is unreachable.
    """
    if not query or not query.strip():
        return None

    q = query.lower()

    is_start  = any(k in q for k in _START_INTENT)
    is_choice = any(k in q for k in _CHOICE_INTENT)

    if not (is_start or is_choice):
        return None

    soup = _fetch_soup(_FAQ_URL)
    if not soup:
        return None

    # Pick heading keywords based on intent
    heading_kws = _START_Q_KEYWORDS if is_start else _CHOICE_Q_KEYWORDS

    answer_block = _find_faq_card(soup, heading_kws)
    if not answer_block:
        return None

    links    = _extract_links(answer_block)
    guidance = _format_guidance(answer_block, links)

    return {
        "guidance": guidance,
        "source":   _FAQ_URL,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Query: ").strip()
    result = faq_rag_lookup(q)

    if result is None:
        print("No FAQ guidance found for that query.")
    else:
        print(json.dumps(result, indent=2))
