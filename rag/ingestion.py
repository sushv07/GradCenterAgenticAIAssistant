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
        if page_type == "deadlines":
            # Specialist extractor: one dict per program to prevent cross-program
            # chunk merging.  Falls back to generic parse_page() if it returns [].
            specialist_pages = _parse_deadlines_page(html, url, title)
            if specialist_pages:
                total_chars = sum(p["char_count"] for p in specialist_pages)
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
