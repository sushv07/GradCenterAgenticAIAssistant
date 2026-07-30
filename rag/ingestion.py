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
    7.  _parse_deadlines_page() — specialist extractor for the deadlines page that
                              produces one structured dict per program entry instead
                              of one merged blob for the whole page.

HTML cleaning strategy (why two steps):
    Step 1 — extract the main content region first (if discoverable).
             CSULB pages use a <main> element or role="main" div that wraps
             only the body content, excluding the sitewide header/nav/footer.
             Targeting this element is more reliable than removing noise, because
             Drupal CMS class names can change unpredictably.
    Step 2 — run noise removal inside the extracted region to catch any residual
             breadcrumbs, related-links blocks, or inline navigation that survived.

Deadlines page — why a specialist extractor:
    The doctoral deadlines page lays out 6 program cards as nested HTML tables
    inside two side-by-side column divs.  The generic flat-text path merges all
    6 programs into one continuous string; the 500-char chunker then cuts across
    program boundaries, producing chunks that mix unrelated programs (e.g. a chunk
    that starts mid-Engineering-deadline and ends mid-Nursing-deadline).

    _parse_deadlines_page() walks the DOM and extracts each program card into its
    own structured text block:

        Educational Leadership - P-12 Specialization (Ed.D.) — Application Deadlines
        Advisor: Kimberly Word | Email: eddinfo@csulb.edu | Phone: 562-985-4998
        Application:    Spring: Not Accepting | Fall: January 15
        Accept/Decline: Spring: Not Applicable | Fall: April 20

    Each block is ~150–220 chars — well under CHUNK_SIZE=500 — so chunking keeps
    every program as its own isolated chunk.  Retrieval now scores program-specific
    queries (e.g. "deadlines for DNP") against the matching single-program chunk
    rather than a noisy merged blob.

    Falls back to generic parse_page() if the expected DOM structure is absent.

Why not use faq_rag_module._fetch_faq_entries() here:
    That function is FAQ-specific — it walks accordion cards and pairs each
    question with its answer so they land in the same chunk.  The other 3 pages
    (deadlines, eligibility, application process) are prose/table pages without
    an accordion structure.  A single generic parser works for those 3 pages.

No OpenAI dependency — pure requests + BeautifulSoup.
"""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from obs.ingestion_events import (
    emit_ingestion_started,
    emit_ingestion_page_fetched,
    emit_ingestion_page_retry,
    emit_ingestion_page_parsed,
    emit_ingestion_page_failed,
    emit_ingestion_completed,
)

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
        "content_category": "generic_application",
    },
]

# Program-specific application / department pages — SEED ENTRIES ONLY.
#
# These are used as fallback seeds when the index page does not directly link
# to a program's department page.  content_category is intentionally absent:
# it is computed automatically by rag.discovery.classify_page() at ingest time
# so that no individual program is special-cased.
#
# Fields:
#   url          — seed URL to start discovery from for this program
#   page_type    — "program_application" (required by retriever filter)
#   title        — human-readable title (may be overridden by <title> tag at fetch)
#   program_name — canonical program name; must match the deadlines page entries
#
# content_category and workflow_priority are NOT listed here — they are derived
# by rag.discovery at build time via content-signal classification.
PROGRAM_SOURCES: list[dict] = [
    {
        "url": (
            "https://www.csulb.edu/college-of-education/"
            "educational-doctorate-educational-leadership"
        ),
        "page_type":    "program_application",
        "title":        "Educational Doctorate in Educational Leadership",
        "program_name": "Educational Leadership (Ed.D.)",
    },
    {
        "url": "https://www.csulb.edu/college-of-engineering/engineering-doctoral-studies",
        "page_type":    "program_application",
        "title":        "Engineering Doctoral Studies",
        "program_name": "Engineering & Computational Mathematics (Ph.D.)",
    },
    {
        "url": (
            "https://www.csulb.edu/college-of-health-human-services/"
            "physical-therapy/applying-to-the-dpt-program"
        ),
        "page_type":    "program_application",
        "title":        "Applying to the DPT Program",
        "program_name": "Physical Therapy (DPT)",
    },
    {
        "url": (
            "https://www.csulb.edu/college-of-health-human-services/"
            "health-science/doctor-of-public-health-drph/doctor-of-public-3"
        ),
        "page_type":    "program_application",
        "title":        "Doctor of Public Health (DR.P.H.)",
        "program_name": "Public Health (DR.P.H.)",
    },
    {
        "url": (
            "https://www.csulb.edu/college-of-health-human-services/"
            "school-of-nursing/bsn-dnp-program"
        ),
        "page_type":    "program_application",
        "title":        "BSN-DNP Program",
        "program_name": "Nursing (D.N.P.)",
    },
]

# Combined source list — static fallback used when use_discovery=False.
# When use_discovery=True (default), get_or_build_store() calls
# ingest_pages() without this list and builds program sources via discovery.
ALL_SOURCES: list[dict] = PAGE_SOURCES + PROGRAM_SOURCES

# Workflow priority by content_category (used for metadata on non-discovered pages).
# Must stay in sync with rag.discovery.WORKFLOW_PRIORITY.
_WORKFLOW_PRIORITY: dict[str, int] = {
    "department_application":    1,
    "supplemental_application":  2,
    "program_requirements":      3,
    "program_eligibility":       3,
    "transcript_instructions":   4,
    "international_instructions":4,
    "generic_application":       5,
    "overview_only":             6,
    "":                          6,
}


def _workflow_priority_from_category(category: str) -> int:
    """Return the workflow_priority integer for a given content_category string."""
    return _WORKFLOW_PRIORITY.get(category, 5)

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
                emit_ingestion_page_retry(
                    url=url, error_type=type(exc).__name__, error=str(exc)[:200]
                )
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
# Deadlines page specialist extractor
# ---------------------------------------------------------------------------

def _extract_program_entry(td_elem, source_url: str) -> Optional[dict]:
    """
    Extract one doctoral program's deadline data from its <td> DOM element.

    Expected DOM shape (confirmed against live CSULB deadlines page):
        <td>
          <div>
            <a class="button light">Program Name</a>      ← program name
            Advisor: Advisor Name
            <a href="mailto:...">email</a>                ← advisor email
            <p>Phone: 562-985-XXXX</p>                    ← optional phone
            <table>                                        ← deadlines table
              <tbody>
                <tr><td colspan="3">Deadlines*</td></tr>   ← header row (skip)
                <tr><td/><td>Spring</td><td>Fall</td></tr> ← season labels
                <tr><td>Application</td><td>…</td><td>…</td></tr>
                <tr><td>Accept/Decline</td><td>…</td><td>…</td></tr>
              </tbody>
            </table>
          </div>
        </td>

    Returns a page dict (same shape as parse_page()):
        {
            "url":        str,
            "page_type":  "deadlines",
            "title":      str,          (e.g. "Educational Leadership (Ed.D.) — Application Deadlines")
            "text":       str,          structured ~150-220 char block
            "links":      list[dict],
            "char_count": int,
        }
    Returns None if the required <a class="button light"> is absent (unexpected DOM).
    """
    # ── 1. Program name ──────────────────────────────────────────────────────
    # The CSULB deadlines page wraps each program name in <a class="button light">.
    # Do NOT fall back to <strong> — that would match row labels ("Application",
    # "Accept/Decline") inside the nested deadline table cells.
    name_tag = td_elem.find("a", class_=lambda c: c and "button" in c and "light" in c)
    if not name_tag:
        return None

    program_name = name_tag.get_text(strip=True)
    if not program_name:
        return None

    # ── 2. Advisor name ──────────────────────────────────────────────────────
    # The advisor name is plain text in the div, between the button <a> and
    # the mailto <a>.  We grab all text nodes from the div and hunt for "Advisor:".
    div_elem = name_tag.find_parent("div") or td_elem
    raw_div_text = div_elem.get_text(separator=" ", strip=True)

    advisor_name = ""
    advisor_match = re.search(r"Advisor[s]?:\s*([^|Email\n]+?)(?=\s*\||\s*Email|\s*<|$)", raw_div_text)
    if advisor_match:
        advisor_name = advisor_match.group(1).strip().rstrip(",|")

    # ── 3. Advisor email ─────────────────────────────────────────────────────
    email_tag = td_elem.find("a", href=re.compile(r"^mailto:", re.I))
    advisor_email = ""
    if email_tag:
        advisor_email = email_tag.get("href", "").replace("mailto:", "").strip()
        if not advisor_email:
            advisor_email = email_tag.get_text(strip=True)

    # ── 4. Phone (optional) ──────────────────────────────────────────────────
    phone = ""
    for p_tag in td_elem.find_all("p"):
        p_text = p_tag.get_text(strip=True)
        if "Phone" in p_text or "phone" in p_text:
            # Extract just the number portion
            phone_match = re.search(r"[\d\-\(\)\s]{7,}", p_text)
            if phone_match:
                phone = phone_match.group(0).strip()
            break

    # ── 5. Deadline table ────────────────────────────────────────────────────
    # Live CSULB page has a 2-column table (confirmed):
    #   Row 0: ['Deadlines*']                  ← header (skip)
    #   Row 1: ['Application', 'Accept/Decline'] ← column labels
    #   Row 2: ['Spring: Not Accepting', 'Spring: Not Applicable']  ← spring
    #   Row 3: ['Fall: January 15',      'Fall: April 20']          ← fall
    #
    # Each cell already embeds the season prefix ("Spring: …" / "Fall: …").
    # We split on ": " to isolate the value.
    deadline_table = td_elem.find("table")
    app_spring = app_fall = acc_spring = acc_fall = "N/A"

    if deadline_table:
        rows = deadline_table.find_all("tr")
        # Find the label row: contains both "Application" and "Accept" (or "Decline")
        label_row_idx = None
        for idx, row in enumerate(rows):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            joined = " ".join(cells).lower()
            if "application" in joined and ("accept" in joined or "decline" in joined):
                label_row_idx = idx
                break

        if label_row_idx is not None:
            data_rows = rows[label_row_idx + 1:]
            for row in data_rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                # cells[0] = Application spring/fall value, cells[1] = Accept/Decline value
                # Each value looks like "Spring: Not Accepting" or "Fall: January 15"
                def _extract_val(cell_text: str) -> str:
                    """Strip the 'Spring: ' / 'Fall: ' prefix if present."""
                    if ": " in cell_text:
                        return cell_text.split(": ", 1)[1].strip() or "N/A"
                    return cell_text.strip() or "N/A"

                row_text = cells[0].lower()
                if "spring" in row_text:
                    app_spring = _extract_val(cells[0])
                    acc_spring = _extract_val(cells[1]) if len(cells) > 1 else "N/A"
                elif "fall" in row_text:
                    app_fall = _extract_val(cells[0])
                    acc_fall = _extract_val(cells[1]) if len(cells) > 1 else "N/A"

    # ── 6. Build structured text block ───────────────────────────────────────
    lines = [f"{program_name} — Application Deadlines"]

    contact_parts = []
    if advisor_name:
        contact_parts.append(f"Advisor: {advisor_name}")
    if advisor_email:
        contact_parts.append(f"Email: {advisor_email}")
    if phone:
        contact_parts.append(f"Phone: {phone}")
    if contact_parts:
        lines.append(" | ".join(contact_parts))

    lines.append(
        f"Application:    Spring: {app_spring} | Fall: {app_fall}"
    )
    lines.append(
        f"Accept/Decline: Spring: {acc_spring} | Fall: {acc_fall}"
    )

    text = "\n".join(lines)

    # ── 7. Links ─────────────────────────────────────────────────────────────
    links: list[dict] = []
    if advisor_email:
        links.append({"text": f"Email {program_name} advisor", "url": f"mailto:{advisor_email}"})

    return {
        "url":        source_url,
        "page_type":  "deadlines",
        "title":      f"{program_name} — Application Deadlines",
        "text":       text,
        "links":      links,
        "char_count": len(text),
    }


def _parse_deadlines_page(html: str, url: str, title: str) -> list[dict]:
    """
    Specialist extractor for the CSULB doctoral deadlines page.

    Produces one structured page dict per program (up to 6) plus an optional
    introductory page dict for any preamble text above the program cards.

    DOM layout (confirmed against live page):
        Two side-by-side column divs:
            div.container-inline-block.column-2   (left)
            div.container-inline-block.column-2   (right)
        Each div contains 3 program cards.
        Each program card is a <table> inside a <td> inside a <tr> inside the
        column-level <table>.  The card's outer container is the inner <td>
        that holds both the program info block and the deadlines nested table.

    Falls back to an empty list if the expected column divs are not found —
    callers should then call parse_page() as a fallback.

    Returns:
        List of 0–7 page dicts (0 = DOM structure changed; 1 intro + up to 6 programs).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    # ── 1. Extract preamble / intro text ────────────────────────────────────
    main_content = _find_main_content(soup)
    if main_content:
        # Grab any introductory paragraphs before the program-card columns
        intro_parts: list[str] = []
        for elem in main_content.children:
            # Stop when we hit the first column div
            if hasattr(elem, "get") and elem.get("class"):
                cls = " ".join(elem.get("class", []))
                if "column" in cls or "container-inline-block" in cls:
                    break
            if hasattr(elem, "get_text"):
                t = elem.get_text(strip=True)
                if t and len(t) > 20:
                    intro_parts.append(t)

        if intro_parts:
            intro_text = re.sub(r"\s+", " ", " ".join(intro_parts)).strip()
            if len(intro_text) >= _MIN_TEXT_LEN:
                links = _extract_links(soup)
                results.append({
                    "url":        url,
                    "page_type":  "deadlines",
                    "title":      title,
                    "text":       intro_text,
                    "links":      links,
                    "char_count": len(intro_text),
                })

    # ── 2. Find all program card <td> elements ───────────────────────────────
    # Strategy: find all divs that have both "container-inline-block" and
    # "column-2" in their class list; each such div contains 3 program cards.
    search_root = main_content if main_content else soup

    column_divs = search_root.find_all(
        "div",
        class_=lambda c: c and "column-2" in c and "container-inline-block" in c,
    )

    if not column_divs:
        # Try alternate selector: any div with class containing "column-2"
        column_divs = search_root.find_all(
            "div", class_=lambda c: c and "column-2" in c
        )

    if not column_divs:
        print(
            "[ingestion] _parse_deadlines_page: no column-2 divs found — "
            "falling back to parse_page()"
        )
        return []

    print(f"[ingestion] _parse_deadlines_page: found {len(column_divs)} column div(s)")

    # ── 3. Walk each column div → find inner <td> program containers ─────────
    seen_programs: set[str] = set()

    for col_div in column_divs:
        # Each program card lives in a top-level <td> inside the column table.
        # We want the outermost <td> per card, not nested <td>s from the
        # deadlines sub-table.  We use the presence of an <a class="button light">
        # (or <strong>) as the "this is a program card" signal.
        for td in col_div.find_all("td"):
            # Only <td>s that contain an <a class="button light"> program-name link.
            # Do NOT use a <strong> fallback — that matches row labels in nested tables.
            name_tag = td.find(
                "a", class_=lambda c: c and "button" in c and "light" in c
            )
            if not name_tag:
                continue

            prog_name = name_tag.get_text(strip=True)
            if not prog_name or prog_name in seen_programs:
                continue

            entry = _extract_program_entry(td, url)
            if entry:
                seen_programs.add(prog_name)
                results.append(entry)
                print(
                    f"[ingestion]   ✓ program entry: {prog_name[:60]} "
                    f"({entry['char_count']} chars)"
                )

    if not seen_programs:
        print(
            "[ingestion] _parse_deadlines_page: found column divs but extracted "
            "0 program entries — falling back to parse_page()"
        )
        return []

    print(f"[ingestion] _parse_deadlines_page: extracted {len(seen_programs)} program entries")
    return results


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def ingest_pages(
    sources:         list[dict] | None = None,
    skip_failed:     bool = True,
    use_discovery:   bool = True,
    discovery_depth: int  = 1,
) -> list[dict]:
    """
    Fetch and parse all source pages into structured page dicts.

    When sources is None and use_discovery=True (the default for store rebuilds):
        - Processes PAGE_SOURCES normally.
        - Calls rag.discovery.discover_all_programs() to build program sources
          dynamically, using PROGRAM_SOURCES as seed URL fallbacks.
        - content_category and workflow_priority are computed from page content
          signals — no values are hardcoded per program.

    When sources is None and use_discovery=False:
        - Falls back to ALL_SOURCES (PAGE_SOURCES + static PROGRAM_SOURCES).
        - content_category comes from the PROGRAM_SOURCES entries (empty strings).
        - workflow_priority is computed from content_category.

    When sources is provided explicitly:
        - Processes the given list as-is.
        - Supports source dicts from discovery (with discovered_from + workflow_priority)
          and static dicts (without, for backward compat).

    Args:
        sources:         Explicit source list.  Each must have url, page_type, title.
                         Optional fields: program_name, content_category,
                         discovered_from, workflow_priority.
        skip_failed:     Skip failed/empty pages instead of raising (default True).
        use_discovery:   When sources is None, run automatic discovery to build
                         program sources (default True).
        discovery_depth: Nested-link crawl depth for discovery (default 1).
                         depth=0 = classify seed pages only (faster, no crawling).

    Returns:
        List of parsed page dicts, each with keys:
            url, page_type, title, text, links, char_count,
            program_name        (str, "" for non-program pages),
            content_category    (str, from discovery or "" when not set),
            discovered_from     (str, "" for manually specified / static sources),
            parent_program_url  (str, "" for seed pages; seed URL for nested subpages),
            workflow_priority   (int, 1–6; computed from content_category).

    Error handling:
        - Failed HTTP fetches  → logged; skipped (if skip_failed=True)
        - Pages with < 150 chars after cleaning → skipped
        - Duplicate URLs → deduplicated
    """
    # ── Build sources list ─────────────────────────────────────────────────────
    if sources is None:
        if use_discovery:
            try:
                from rag.discovery import discover_all_programs
                index_url = PAGE_SOURCES[1]["url"]  # deadlines / index page
                seeds = [
                    {"program_name": s.get("program_name", ""), "url": s["url"]}
                    for s in PROGRAM_SOURCES
                    if s.get("program_name")
                ]
                program_sources = discover_all_programs(
                    index_url=index_url,
                    seed_overrides=seeds,
                    depth=discovery_depth,
                )
                sources = list(PAGE_SOURCES) + program_sources
                print(
                    f"[ingestion] Discovery built {len(program_sources)} program "
                    f"source(s) across {len({s.get('program_name') for s in program_sources})} "
                    f"program(s)"
                )
            except Exception as exc:
                print(
                    f"[ingestion] Discovery failed ({exc}); falling back to ALL_SOURCES"
                )
                sources = ALL_SOURCES
        else:
            sources = ALL_SOURCES

    emit_ingestion_started(len(sources), use_discovery)
    _t_total = time.perf_counter()

    pages:     list[dict] = []
    seen_urls: set[str]   = set()
    _pages_failed = 0

    for source in sources:
        url              = source["url"]
        page_type        = source["page_type"]
        title            = source["title"]
        # Extended metadata — populated by discovery; empty for static/generic pages
        prog_name           = source.get("program_name", "")
        content_category    = source.get("content_category", "")
        discovered_from     = source.get("discovered_from", "")
        parent_program_url  = source.get("parent_program_url", "")
        # workflow_priority: from discovery dict, or computed from content_category
        workflow_priority = source.get(
            "workflow_priority",
            _workflow_priority_from_category(content_category),
        )

        # ── Deduplication ───────────────────────────────────────────────────
        if url in seen_urls:
            print(f"[ingestion] Skipping duplicate URL: {url}")
            continue
        seen_urls.add(url)

        # ── Fetch ────────────────────────────────────────────────────────────
        prog_label = f" [{prog_name}]" if prog_name else ""
        print(f"[ingestion] Fetching [{page_type}]{prog_label} {url}")
        _t_fetch = time.perf_counter()
        html = fetch_page(url)
        _fetch_elapsed = round((time.perf_counter() - _t_fetch) * 1000, 1)

        if html is None:
            _pages_failed += 1
            emit_ingestion_page_failed(url, page_type, prog_name, "fetch", "fetch_failed")
            msg = f"[ingestion] Could not fetch {url}"
            if skip_failed:
                print(f"{msg} — skipping")
                continue
            raise RuntimeError(msg)

        emit_ingestion_page_fetched(
            url=url, page_type=page_type, program_name=prog_name,
            fetch_elapsed_ms=_fetch_elapsed,
            response_size_bytes=len(html.encode("utf-8", errors="replace")),
        )

        # ── Parse ────────────────────────────────────────────────────────────
        _t_parse = time.perf_counter()
        if page_type == "faq":
            # Phase 4.1 specialist: one dict per FAQ entry (atomic), each with a
            # unique fragment URL so document_ids/chunk_ids don't collide. Falls
            # back to generic parse_page() if it finds no accordion FAQ entries,
            # so ingestion never breaks on an unexpected page shape.
            from rag.faq_ingest import parse_faq_page
            specialist_pages = parse_faq_page(html, url, title)
            if specialist_pages:
                _parse_elapsed = round((time.perf_counter() - _t_parse) * 1000, 1)
                total_chars = sum(p["char_count"] for p in specialist_pages)
                emit_ingestion_page_parsed(
                    url=url, page_type=page_type, program_name=prog_name,
                    char_count=total_chars, parse_elapsed_ms=_parse_elapsed,
                    entry_count=len(specialist_pages),
                )
                print(
                    f"[ingestion] ✓ [{page_type}] specialist: "
                    f"{len(specialist_pages)} atomic FAQ(s), {total_chars:,} chars total"
                )
                pages.extend(specialist_pages)
                continue
            else:
                print(
                    f"[ingestion] [{page_type}] specialist returned empty — "
                    "falling back to generic parse_page()"
                )

        if page_type == "deadlines":
            # Specialist extractor: one dict per program to prevent cross-program
            # chunk merging.  Falls back to generic parse_page() if it returns [].
            specialist_pages = _parse_deadlines_page(html, url, title)
            if specialist_pages:
                _parse_elapsed = round((time.perf_counter() - _t_parse) * 1000, 1)
                total_chars = sum(p["char_count"] for p in specialist_pages)
                emit_ingestion_page_parsed(
                    url=url, page_type=page_type, program_name=prog_name,
                    char_count=total_chars, parse_elapsed_ms=_parse_elapsed,
                    entry_count=len(specialist_pages),
                )
                print(
                    f"[ingestion] ✓ [{page_type}] specialist: "
                    f"{len(specialist_pages)} entries, {total_chars:,} chars total"
                )
                pages.extend(specialist_pages)
                continue
            else:
                print(
                    f"[ingestion] [{page_type}] specialist returned empty — "
                    "falling back to generic parse_page()"
                )

        page = parse_page(html, url, page_type, title)
        _parse_elapsed = round((time.perf_counter() - _t_parse) * 1000, 1)

        if page is None:
            _pages_failed += 1
            emit_ingestion_page_failed(url, page_type, prog_name, "parse", "parse_failed")
            msg = f"[ingestion] No usable content from {url}"
            if skip_failed:
                print(f"{msg} — skipping")
                continue
            raise RuntimeError(msg)

        emit_ingestion_page_parsed(
            url=url, page_type=page_type, program_name=prog_name,
            char_count=page["char_count"], parse_elapsed_ms=_parse_elapsed,
            entry_count=1,
        )

        # Inject extended metadata from the source definition.
        # These propagate into ChromaDB chunk metadata via chunk_documents().
        page["program_name"]        = prog_name
        page["content_category"]    = content_category
        page["discovered_from"]     = discovered_from
        page["parent_program_url"]  = parent_program_url
        page["workflow_priority"]   = workflow_priority

        print(
            f"[ingestion] ✓ [{page_type}]{prog_label} "
            f"[{content_category or 'no-category'} p={workflow_priority}] "
            f"{page['char_count']:,} chars, {len(page['links'])} links"
        )
        pages.append(page)

    _total_elapsed = round((time.perf_counter() - _t_total) * 1000, 1)
    _total_chars   = sum(p.get("char_count", 0) for p in pages)
    emit_ingestion_completed(
        pages_attempted=len(sources),
        pages_succeeded=len(pages),
        pages_failed=_pages_failed,
        elapsed_ms=_total_elapsed,
        total_chars=_total_chars,
    )
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
