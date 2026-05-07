"""
rag/ingestion.py
Fetches and parses CSULB Graduate Center pages into structured page dicts.

Ingestion flow:
    1.  Define PAGE_SOURCES — the 4 primary CSULB pages with metadata.
    2.  fetch_page(url)     — GET the URL with retry; return raw HTML or None.
    3.  _find_main_content()— locate the <main> or equivalent content block.
    4.  _remove_noise()     — strip nav/header/footer/script/aside in-place.
    5.  parse_page()        — clean + extract text; return a structured page dict.
    6.  ingest_pages()      — orchestrate the above for all sources; deduplicate URLs.

HTML cleaning strategy (why two steps):
    Step 1 — extract the main content region first (if discoverable).
             CSULB pages use a <main> element or role="main" div that wraps
             only the body content, excluding the sitewide header/nav/footer.
             Targeting this element is more reliable than removing noise, because
             Drupal CMS class names can change unpredictably.
    Step 2 — run noise removal inside the extracted region to catch any residual
             breadcrumbs, related-links blocks, or inline navigation that survived.

Why not use faq_rag_module._fetch_faq_entries() here:
    That function is FAQ-specific — it walks accordion cards and pairs each
    question with its answer so they land in the same chunk.  The other 3 pages
    (deadlines, eligibility, application process) are prose/table pages without
    an accordion structure.  A single generic parser works for all 4 pages.
    NOTE: the downside for the FAQ page is that Q+A pairs may be split across
    chunk boundaries by the chunker.  The 75-token overlap and cosine similarity
    retrieval handle this acceptably for an MVP.  A FAQ-specific pre-processor
    can be added in Phase 2 if retrieval quality on FAQ queries needs improvement.

No OpenAI dependency — pure requests + BeautifulSoup.
"""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

# The 4 primary CSULB pages for Phase 1 ingestion.
# Each entry must have: url, page_type, title
#
# page_type values are used as metadata tags in the vector store and enable
# filtered retrieval (e.g. "only search eligibility chunks for GPA questions").
PAGE_SOURCES: list[dict] = [
    {
        "url":       "https://www.csulb.edu/graduate-center/frequently-asked-questions-faqs",
        "page_type": "faq",
        "title":     "CSULB Graduate Center FAQs",
    },
    {
        "url":       "https://www.csulb.edu/graduate-studies-csulb/article/programs-advisors-and-deadlines-doctoral",
        "page_type": "deadlines",
        "title":     "Doctoral Programs, Advisors and Deadlines",
    },
    {
        "url":       "https://www.csulb.edu/admissions/doctoral-programs-admission-eligibility",
        "page_type": "eligibility",
        "title":     "Doctoral Programs Admission Eligibility",
    },
    {
        "url":       "https://www.csulb.edu/admissions/doctoral-programs-application-process",
        "page_type": "application_process",
        "title":     "Doctoral Programs Application Process",
    },
]

_BASE_URL      = "https://www.csulb.edu"
_FETCH_TIMEOUT = 12        # seconds before giving up on a single fetch
_RETRY_PAUSE   = 1.5       # seconds to wait before retrying after a failure
_MIN_TEXT_LEN  = 150       # pages shorter than this (chars) are considered empty

_HEADERS = {
    "User-Agent": "CSULB-GradAssistant/3.0 (educational; non-commercial)",
    "Accept":     "text/html,application/xhtml+xml",
}

# ---------------------------------------------------------------------------
# Noise removal
# ---------------------------------------------------------------------------

# HTML5 structural tags that are universally navigation/chrome, never content.
_STRUCTURAL_NOISE_TAGS = ["nav", "header", "footer", "aside"]

# Script/style/media tags that add no readable text value.
_SCRIPT_NOISE_TAGS = ["script", "style", "noscript", "iframe", "svg", "form", "button"]

# CSS class/id substrings that reliably indicate non-content elements on CSULB pages.
# Matched as substrings (e.g. "breadcrumb" matches "breadcrumb-nav", "breadcrumbs").
_NOISE_KEYWORDS = {
    "breadcrumb",
    "utility-nav", "utility-bar", "global-nav", "local-nav",
    "site-header", "site-footer", "site-search",
    "social-media", "social-share", "share-bar",
    "cookie-banner", "cookie-notice",
    "skip-link", "skip-nav",
    "pagination", "pager",
    "back-to-top",
    "sidebar", "side-bar",
    "widget-area",
    "related-links", "also-see", "see-also",
    "print-header", "print-footer",
}


def _remove_noise(element) -> None:
    """
    Remove non-content tags from a BeautifulSoup element in-place.

    Applied to either the full soup (fallback path) or the extracted
    main-content region (preferred path).  Two passes:
      Pass 1 — remove structural and script tags by tag name.
      Pass 2 — remove any remaining element whose class or id contains a
               known noise keyword.  Uses substring matching so it catches
               class names like "site-breadcrumb" or "utility-nav-wrapper".
    """
    # Pass 1: remove by tag name
    for tag_name in _STRUCTURAL_NOISE_TAGS + _SCRIPT_NOISE_TAGS:
        for tag in element.find_all(tag_name):
            tag.decompose()

    # Pass 2: remove by class/id keyword match
    # We iterate over a copy of the tag list because decompose() modifies the tree.
    for tag in list(element.find_all(True)):
        try:
            combined = " ".join(tag.get("class", [])).lower() + " " + (tag.get("id") or "").lower()
        except Exception:
            continue

        for kw in _NOISE_KEYWORDS:
            if kw in combined:
                tag.decompose()
                break  # tag is gone; stop checking keywords for this tag


def _find_main_content(soup: BeautifulSoup):
    """
    Locate the primary content region of a CSULB page.

    Strategy: try specific selectors in order from most to least reliable.
    If none match, return None — the caller will fall back to full-page parsing.

    CSULB pages (Drupal CMS) typically have:
      <main>                          HTML5 semantic main element
      <div id="main-content">         Drupal-generated content wrapper
      <div role="main">               ARIA landmark (used in older Drupal themes)
      <div class="layout-container">  Drupal 9+ layout wrapper (contains main)
    """
    # Ordered by specificity / reliability
    checks = [
        lambda s: s.find("main"),
        lambda s: s.find(id="main-content"),
        lambda s: s.find(id="content"),
        lambda s: s.find(attrs={"role": "main"}),
        lambda s: s.find(id="page-content"),
        lambda s: s.find(attrs={"class": lambda c: c and "layout-container" in " ".join(c)}),
    ]

    for check in checks:
        try:
            elem = check(soup)
            if elem:
                return elem
        except Exception:
            continue

    return None


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------

def _extract_links(soup: BeautifulSoup) -> list[dict[str, str]]:
    """
    Extract unique, content-relevant links from the page before noise removal.

    We extract links before _remove_noise() because some legitimate resource
    links live inside elements that look like navigation (e.g. "Apply here"
    inside a sidebar call-to-action block).

    Skips: anchor-only hrefs, javascript: hrefs, mailto:, tel:, and duplicates.
    Resolves relative URLs to absolute csulb.edu URLs.
    """
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = a.get_text(strip=True).rstrip(".,;:")

        if not href or not text or len(text) < 3:
            continue

        if href.startswith(("#", "javascript", "mailto:", "tel:")):
            continue

        full_url = urljoin(_BASE_URL, href)

        if full_url not in seen:
            seen.add(full_url)
            links.append({"text": text, "url": full_url})

    return links


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> Optional[str]:
    """
    Fetch a URL and return the raw HTML string.

    Retries once after a brief pause on any RequestException.
    Returns None if both attempts fail — callers decide whether to skip or raise.

    User-Agent is set to identify this as an educational tool, not a scraper bot.
    """
    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=_FETCH_TIMEOUT, headers=_HEADERS)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == 0:
                print(f"[ingestion] Fetch attempt 1 failed for {url}: {exc} — retrying")
                time.sleep(_RETRY_PAUSE)
            else:
                print(f"[ingestion] Fetch failed after 2 attempts for {url}: {exc}")
                return None

    return None  # unreachable, satisfies type checker


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_page(html: str, url: str, page_type: str, title: str) -> Optional[dict]:
    """
    Parse a raw HTML string into a structured page dict.

    Returns:
        {
            "url":        str,         source URL for citation
            "page_type":  str,         faq | deadlines | eligibility | application_process
            "title":      str,         page title (from HTML <title> or our default)
            "text":       str,         cleaned body text, whitespace-normalized
            "links":      list[dict],  [{text, url}] extracted before noise removal
            "char_count": int,         length of cleaned text (for diagnostics)
        }
        Returns None if the page yields less than _MIN_TEXT_LEN chars after cleaning.

    Cleaning pipeline:
        1. Parse HTML with BeautifulSoup.
        2. Try to extract page title from <title> tag.
        3. Extract links BEFORE removing elements (some links live in elements
           that look like navigation but contain useful resource URLs).
        4. Try _find_main_content() to isolate the body region.
        5. Run _remove_noise() on the extracted region (or full soup if no region found).
        6. get_text() + whitespace normalization.
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── 1. Refine page title from <title> tag ────────────────────────────────
    html_title_tag = soup.find("title")
    if html_title_tag:
        raw_title = html_title_tag.get_text(strip=True)
        # CSULB title format: "Page Topic | CSULB" — keep only the topic part
        if " | " in raw_title:
            raw_title = raw_title.split(" | ")[0].strip()
        if raw_title and len(raw_title) > 5:
            title = raw_title

    # ── 2. Extract links before any DOM modification ─────────────────────────
    links = _extract_links(soup)

    # ── 3. Find and clean the main content region ────────────────────────────
    main_content = _find_main_content(soup)

    if main_content:
        # Remove noise inside the main region only (faster, more targeted)
        _remove_noise(main_content)
        text_source = main_content
    else:
        # Fallback: clean the entire page (noisier but covers all edge cases)
        _remove_noise(soup)
        text_source = soup

    # ── 4. Extract and normalize text ────────────────────────────────────────
    raw_text = text_source.get_text(separator=" ", strip=True)

    # Collapse runs of whitespace (spaces, tabs, newlines) to a single space.
    # This is important because get_text() with separator=" " can still produce
    # double-spaces around block elements.
    text = re.sub(r"\s+", " ", raw_text).strip()

    if len(text) < _MIN_TEXT_LEN:
        print(
            f"[ingestion] Very short content ({len(text)} chars) from {url} — skipping. "
            "Check if the page structure changed or the URL is correct."
        )
        return None

    return {
        "url":        url,
        "page_type":  page_type,
        "title":      title,
        "text":       text,
        "links":      links,
        "char_count": len(text),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def ingest_pages(
    sources: list[dict] = PAGE_SOURCES,
    skip_failed: bool = True,
) -> list[dict]:
    """
    Fetch and parse all source pages into structured page dicts.

    Args:
        sources:      List of {url, page_type, title} dicts.
                      Defaults to PAGE_SOURCES (the 4 primary CSULB pages).
        skip_failed:  If True, failed fetches are logged and skipped.
                      If False, the first failure raises RuntimeError.

    Returns:
        List of parsed page dicts.  Each dict has keys:
            url, page_type, title, text, links, char_count

    Error handling:
        - Failed HTTP fetches  → logged; skipped (if skip_failed=True)
        - Pages with < 150 chars after cleaning → skipped
        - Duplicate URLs (same URL appearing twice in sources) → deduplicated
    """
    pages: list[dict] = []
    seen_urls: set[str] = set()

    for source in sources:
        url       = source["url"]
        page_type = source["page_type"]
        title     = source["title"]

        # ── Deduplication ───────────────────────────────────────────────────
        if url in seen_urls:
            print(f"[ingestion] Skipping duplicate URL: {url}")
            continue
        seen_urls.add(url)

        # ── Fetch ────────────────────────────────────────────────────────────
        print(f"[ingestion] Fetching [{page_type}] {url}")
        html = fetch_page(url)

        if html is None:
            msg = f"[ingestion] Could not fetch {url}"
            if skip_failed:
                print(f"{msg} — skipping")
                continue
            raise RuntimeError(msg)

        # ── Parse ────────────────────────────────────────────────────────────
        page = parse_page(html, url, page_type, title)

        if page is None:
            msg = f"[ingestion] No usable content from {url}"
            if skip_failed:
                print(f"{msg} — skipping")
                continue
            raise RuntimeError(msg)

        print(
            f"[ingestion] ✓ [{page_type}] {page['char_count']:,} chars, "
            f"{len(page['links'])} links"
        )
        pages.append(page)

    print(f"\n[ingestion] Ingested {len(pages)} of {len(sources)} pages successfully")
    return pages


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Quick sanity-check: ingest all 4 pages and print a summary."""
    import sys

    print("=" * 60)
    print("CSULB RAG Ingestion — sanity check")
    print("=" * 60)

    pages = ingest_pages()

    if not pages:
        print("\n✗ No pages ingested. Check network connectivity and URL validity.")
        sys.exit(1)

    print(f"\n{'Page Type':<22} {'Chars':>8}  {'Links':>6}  Title")
    print("-" * 70)
    for p in pages:
        print(
            f"{p['page_type']:<22} {p['char_count']:>8,}  {len(p['links']):>6}  "
            f"{p['title'][:40]}"
        )

    print(f"\nTotal: {sum(p['char_count'] for p in pages):,} characters across {len(pages)} pages")

    # Show a sample of text from each page
    for p in pages:
        print(f"\n── {p['page_type']} sample (first 300 chars) ──")
        print(p["text"][:300].strip())
