"""
rag/discovery.py
Automatic discovery and classification of doctoral program application pages.

Purpose:
    Replace hardcoded per-program content_category values with a signal-based
    classifier that works generically across ALL doctoral programs.

    The system:
        1. Starts from the doctoral programs index page.
        2. Extracts program names and linked department/program URLs.
        3. For each program, fetches its page(s) and classifies the content.
        4. Follows application-relevant nested links (depth=1 by default).
        5. Returns enriched source dicts ready for ingest_pages().

Classification signals → content_category:
    "department_application"    — external portal (PTCAS, CASPA, SOPHAS, NursingCAS, …)
                                  or "do not apply via Cal State Apply"
    "supplemental_application"  — additional form on top of Cal State Apply (Qualtrics, etc.)
    "program_requirements"      — admission requirements, GRE, portfolio, interview
    "program_eligibility"       — eligibility criteria, who can apply, minimum GPA thresholds
    "transcript_instructions"   — how to submit official transcripts
    "international_instructions"— international student requirements, TOEFL/IELTS, credential eval
    "generic_application"       — standard Cal State Apply instructions
    "overview_only"             — program description; no actionable application steps

Workflow priority (lower integer = surface first):
    1  department_application
    2  supplemental_application
    3  program_requirements / program_eligibility
    4  transcript_instructions / international_instructions
    5  generic_application
    6  overview_only / unknown

Output page dict keys (same shape as ingest_pages() sources):
    url, page_type, title, program_name,
    content_category, discovered_from, workflow_priority,
    parent_program_url   ← "" for seed pages; seed URL for nested subpages

Design notes:
    - No program names are hardcoded in classification logic.
    - Classification is purely content-signal based; the same classifier
      runs on EdD, DPT, DNP, Engineering, Public Health, and any future program.
    - Nested links: up to _MAX_NESTED_LINKS followed per seed page; overview-only
      pages are discarded to keep the corpus focused.
    - Polite crawl: _CRAWL_DELAY seconds between requests; two-attempt retry
      is delegated to ingestion.fetch_page().
"""

from __future__ import annotations

import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE_CSULB = "https://www.csulb.edu"

# Polite crawl delay between nested-link fetches (seconds)
_CRAWL_DELAY = 0.4

# Maximum nested links to follow per seed page (bounded crawl).
# Increased from 8 → 15 to reach deeper application subpages on programs
# that structure their workflow across multiple linked pages (e.g. Ed.D., DPT).
_MAX_NESTED_LINKS = 15

# Minimum relevance score for a link to be followed
_MIN_LINK_SCORE = 0.25

# ---------------------------------------------------------------------------
# Classification signals
# ---------------------------------------------------------------------------
# Each category maps to a list of regex patterns (case-insensitive).
# Checked in the order listed below — first match wins.
# The order encodes priority: more specific patterns come before generic ones.

_SIGNALS: dict[str, list[str]] = {
    # External portals / systems that replace Cal State Apply entirely.
    "department_application": [
        r"\bPTCAS\b",                                    # Physical Therapy
        r"\bCASPA\b",                                    # Physician Assistant
        r"\bSOPHAS\b",                                   # Public Health
        r"\bNursingCAS\b",                               # Nursing
        r"\bOTCAS\b",                                    # Occupational Therapy
        r"\bATCAS\b",                                    # Athletic Training
        r"\bGradCAS\b",                                  # Generic graduate portal
        r"centralized application service",
        r"do\s+not\s+apply.{0,50}cal\s*state",
        r"(?:department|program).{0,40}application\s+portal",
        r"apply.{0,60}(?:through|via).{0,40}(?:portal|external|system)",
        r"external\s+application\s+(?:system|service|portal|process)",
    ],

    # A separate form required in addition to Cal State Apply.
    "supplemental_application": [
        r"\bqualtrics\b",
        r"supplemental\s+application",
        r"program\s+application\s+form",
        r"in\s+addition\s+to.{0,80}(?:cal\s*state|university)\s+apply",
        r"separate\s+(?:application|form)",
        r"(?:additional|second)\s+application\s+(?:form|required)",
        r"program[- ]specific\s+application",
        r"complete.{0,60}(?:additional|separate|supplemental).{0,60}(?:form|application)",
    ],

    # Admission requirements, prerequisites, portfolio, interview, etc.
    "program_requirements": [
        r"admission\s+requirements",
        r"admissions?\s+requirements",
        r"prerequisites?",
        r"required\s+documents",
        r"letters?\s+of\s+recommendation",
        r"statement\s+of\s+purpose",
        r"writing\s+sample",
        r"\bGRE\b",
        r"\bGMAT\b",
        r"(?:application|admissions?)\s+portfolio",
        r"interview\s+(?:required|process|component)",
        r"audition\s+(?:required|process)",
        r"minimum\s+(?:gpa|grade\s*point)",
    ],

    # Eligibility criteria — who can apply and what baseline qualifications are needed.
    # Distinct from program_requirements (which focuses on what to submit):
    # eligibility pages answer "can I apply?" while requirements pages answer "what do I need?".
    "program_eligibility": [
        r"eligibility\s+criteria",
        r"admission\s+eligibility",
        r"minimum\s+eligibility",
        r"who\s+(?:can|may)\s+apply",
        r"eligible\s+applicants?",
        r"eligibility\s+requirements?",
        r"applicant\s+eligibility",
        r"(?:qualify|qualifying)\s+(?:for|to)\s+apply",
        r"admission\s+criteria",
    ],

    # Step-by-step transcript submission instructions.
    "transcript_instructions": [
        r"official\s+transcripts?",
        r"submit\s+(?:your\s+)?(?:official\s+)?transcripts?",
        r"sealed\s+(?:official\s+)?transcripts?",
        r"transcript\s+(?:submission|requirement|policy|instructions?)",
        r"electronic\s+transcript",
        r"national\s+student\s+clearinghouse",
        r"(?:send|mail)\s+(?:official\s+)?transcripts?\s+to",
        r"transcript\s+deadline",
    ],

    # International-student-specific instructions (TOEFL, IELTS, credential eval, etc.).
    "international_instructions": [
        r"international\s+applicants?",
        r"\bTOEFL\b",
        r"\bIELTS\b",
        r"english\s+(?:language\s+)?proficiency",
        r"foreign\s+(?:education|credential|degree|institution)",
        r"credential\s+evaluation",
        r"\bWES\b",
        r"english\s+language\s+requirement",
        r"f-1\s+visa",
        r"\bi-20\b",
        r"international\s+students?\s+(?:must|are\s+required)",
    ],

    # Generic Cal State Apply instructions (broad baseline category).
    "generic_application": [
        r"cal\s*state\s*apply",
        r"calstateapply\.edu",
        r"apply\.calstate\.edu",
        r"doctoral.{0,60}application\s+process",
        r"how\s+to\s+apply.{0,40}(?:doctoral|graduate|phd)",
        r"(?:step|steps).{0,40}to\s+apply",
        r"application\s+(?:checklist|timeline)",
    ],
}

# Workflow priority: lower = higher priority = surface first in tool results.
# Tied categories (same integer) are both considered "specific" at the same threshold.
WORKFLOW_PRIORITY: dict[str, int] = {
    "department_application":    1,  # external portal — highest urgency
    "supplemental_application":  2,  # extra form beyond Cal State Apply
    "program_requirements":      3,  # requirements, GRE, portfolio, interview
    "program_eligibility":       3,  # eligibility criteria (tied with requirements)
    "transcript_instructions":   4,  # how to submit official transcripts
    "international_instructions":4,  # TOEFL / IELTS / credential eval
    "generic_application":       5,  # standard Cal State Apply instructions
    "overview_only":             6,  # program description only
    "":                          6,  # unknown / unclassified
}

# Link text/URL keywords that indicate application relevance.
# When a link's combined text+URL contains one of these keywords it scores above
# _MIN_LINK_SCORE and is considered a candidate for nested crawling.
# Covers all sublink types requested: eligibility, transcripts, international,
# online submission, department forms, review/notification, etc.
_LINK_KEYWORDS = {
    # Core application vocab (original set)
    "apply", "application", "admission", "admissions", "applying",
    "requirements", "prerequisite", "process", "steps", "how-to",
    "supplemental", "doctoral", "doctorate", "graduate", "enroll",
    "checklist", "portal", "materials", "admissions-requirements",
    "application-process", "how-to-apply",
    # Eligibility
    "eligibility", "eligible",
    # Transcripts
    "transcript", "transcripts",
    # International students
    "international",
    # Forms and submissions
    "forms", "form",
    "submit", "submission", "online-application",
    # Review / decision flow
    "review", "notification", "decision",
    # Department-specific application links
    "department",
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_page(html: str, url: str = "") -> tuple[str, int]:
    """
    Classify a page into a content_category based on workflow signals.

    Strips script/style tags, extracts visible text, and scans for signal
    patterns in priority order (most specific → most generic).  The URL
    itself is included in the search corpus to catch portal-name fragments
    embedded in URLs (e.g. "ptcas" in a link href).

    Args:
        html: Raw HTML string of the page to classify.
        url:  Source URL (included in search corpus; safe to omit).

    Returns:
        (content_category, workflow_priority) tuple, e.g. ("department_application", 1).
        Falls back to ("overview_only", 5) if no signal patterns match.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Combine visible text + URL so portal names in links are findable
    corpus = (text + " " + url).lower()

    for category in [
        "department_application",
        "supplemental_application",
        "program_requirements",
        "program_eligibility",
        "transcript_instructions",
        "international_instructions",
        "generic_application",
    ]:
        for pattern in _SIGNALS[category]:
            if re.search(pattern, corpus, re.IGNORECASE):
                return category, WORKFLOW_PRIORITY[category]

    return "overview_only", WORKFLOW_PRIORITY["overview_only"]


# ---------------------------------------------------------------------------
# Link scoring
# ---------------------------------------------------------------------------

def score_link_relevance(link_text: str, link_url: str = "") -> float:
    """
    Score a link's relevance to application/admissions workflows (0.0–1.0).

    Counts how many _LINK_KEYWORDS appear in the combined text+URL string.
    Any 2+ matches produces a score ≥ 0.8 (well above _MIN_LINK_SCORE=0.25).
    A single keyword match scores 0.4.

    Args:
        link_text: Anchor text of the link.
        link_url:  Destination URL (path segments are also keyword-matched).

    Returns:
        float in [0.0, 1.0].
    """
    combined = (link_text + " " + link_url).lower()
    matches = sum(1 for kw in _LINK_KEYWORDS if kw in combined)
    return min(matches / 2.5, 1.0)


def _is_csulb_url(url: str) -> bool:
    """Return True if the URL is hosted on csulb.edu."""
    return "csulb.edu" in (urlparse(url).netloc or "").lower()


def _extract_title_from_html(html: str, fallback: str = "") -> str:
    """Extract the primary page title from the HTML <title> tag."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    if tag:
        raw = tag.get_text(strip=True)
        if " | " in raw:
            raw = raw.split(" | ")[0].strip()
        if raw and len(raw) > 3:
            return raw
    return fallback


# ---------------------------------------------------------------------------
# Single-program discovery
# ---------------------------------------------------------------------------

def discover_program_pages(
    program_name:   str,
    seed_url:       str,
    index_url:      str = "",
    depth:          int = 1,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> list[dict]:
    """
    Discover and classify application-relevant pages for one doctoral program.

    Starts at seed_url, classifies it, then follows the most application-relevant
    nested links (up to _MAX_NESTED_LINKS) until `depth` is exhausted.

    Pages classified as "overview_only" during nested crawl are discarded to
    keep the corpus focused.  The seed page is always kept regardless of category
    (so that overview context is available if no better page is found).

    Args:
        program_name: Canonical program name (e.g. "Physical Therapy (DPT)").
        seed_url:     Starting URL for this program's discovery.
        index_url:    The index page that led to this program (stored as metadata).
        depth:        Levels of nested links to follow.  depth=0 classifies seed only.
        fetch_fn:     HTTP fetch override — (url: str) -> Optional[str].
                      Defaults to rag.ingestion.fetch_page.

    Returns:
        List of source dicts sorted by workflow_priority ascending (most specific first).
        Each dict has: url, page_type, title, program_name,
                       content_category, discovered_from, workflow_priority,
                       parent_program_url (""  for seed; seed_url for nested pages).
        Returns [] if the seed URL cannot be fetched.
    """
    if fetch_fn is None:
        from rag.ingestion import fetch_page
        fetch_fn = fetch_page

    discovered: list[dict] = []
    seen_urls: set[str] = {seed_url}

    # ── Classify seed page ────────────────────────────────────────────────────
    html = fetch_fn(seed_url)
    if html is None:
        print(f"[discovery] Seed fetch failed: {seed_url}")
        return []

    category, priority = classify_page(html, seed_url)
    title = _extract_title_from_html(html, fallback=program_name)

    discovered.append({
        "url":                seed_url,
        "page_type":          "program_application",
        "title":              title,
        "program_name":       program_name,
        "content_category":   category,
        "discovered_from":    index_url,
        "workflow_priority":  priority,
        "parent_program_url": "",          # seed IS the program page; no parent
    })
    print(f"[discovery]   seed [{category} p={priority}]: {seed_url}")

    if depth <= 0:
        return discovered

    # ── Extract and score candidate nested links ──────────────────────────────
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[float, str, str]] = []  # (score, text, url)

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = a.get_text(strip=True)

        if not href or not text or len(text) < 3:
            continue
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        full_url = urljoin(_BASE_CSULB, href)
        if full_url in seen_urls or not _is_csulb_url(full_url):
            continue

        rel = score_link_relevance(text, full_url)
        if rel >= _MIN_LINK_SCORE:
            candidates.append((rel, text, full_url))

    # Highest relevance first; cap at _MAX_NESTED_LINKS
    candidates.sort(key=lambda x: x[0], reverse=True)
    candidates = candidates[:_MAX_NESTED_LINKS]

    # ── Fetch and classify each candidate ────────────────────────────────────
    for rel, link_text, link_url in candidates:
        if link_url in seen_urls:
            continue
        seen_urls.add(link_url)

        nested_html = fetch_fn(link_url)
        if nested_html is None:
            continue

        nested_cat, nested_pri = classify_page(nested_html, link_url)

        # Discard overview-only nested pages — they add noise, not workflow steps
        if nested_cat == "overview_only":
            continue

        nested_title = _extract_title_from_html(nested_html, fallback=link_text)

        discovered.append({
            "url":                link_url,
            "page_type":          "program_application",
            "title":              nested_title,
            "program_name":       program_name,
            "content_category":   nested_cat,
            "discovered_from":    seed_url,
            "workflow_priority":  nested_pri,
            "parent_program_url": seed_url,  # nested page's parent is the seed
        })
        print(
            f"[discovery]     nested [{nested_cat} p={nested_pri} rel={rel:.2f}]: "
            f"{link_url}"
        )
        time.sleep(_CRAWL_DELAY)

    discovered.sort(key=lambda d: d["workflow_priority"])
    return discovered


# ---------------------------------------------------------------------------
# Index-page link extraction
# ---------------------------------------------------------------------------

def _extract_program_links_from_index(html: str, index_url: str) -> list[dict]:
    """
    Extract {program_name, url} pairs from the doctoral programs index page.

    The CSULB deadlines/index page uses <a class="button light"> tags for
    program names inside a two-column table layout.

    Strategy:
        1. If a button <a> has an href pointing to a csulb.edu page → use it.
        2. Otherwise, look for the highest-scoring application-relevant link
           inside the same parent <td> element.

    Returns:
        List of {"program_name": str, "url": str} dicts.
        Programs with no discoverable URL are omitted (covered by seed_overrides).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen_names: set[str] = set()

    for btn in soup.find_all("a", class_=lambda c: c and "button" in c and "light" in c):
        program_name = btn.get_text(strip=True)
        if not program_name or program_name in seen_names:
            continue
        seen_names.add(program_name)

        # Case 1: the button itself is a link to a program page
        href = (btn.get("href") or "").strip()
        if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
            full_url = urljoin(index_url, href)
            if _is_csulb_url(full_url):
                results.append({"program_name": program_name, "url": full_url})
                continue

        # Case 2: find the best application-relevant link in the same <td>
        parent_td = btn.find_parent("td")
        if not parent_td:
            continue

        best_url = ""
        best_score = 0.0
        for a in parent_td.find_all("a", href=True):
            a_href = (a.get("href") or "").strip()
            if a_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full_url = urljoin(index_url, a_href)
            if not _is_csulb_url(full_url):
                continue
            s = score_link_relevance(a.get_text(strip=True), full_url)
            if s > best_score:
                best_score = s
                best_url = full_url

        if best_url and best_score > 0:
            results.append({"program_name": program_name, "url": best_url})

    return results


# ---------------------------------------------------------------------------
# All-programs discovery
# ---------------------------------------------------------------------------

def discover_all_programs(
    index_url:      str,
    seed_overrides: Optional[list[dict]] = None,
    depth:          int = 1,
    fetch_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> list[dict]:
    """
    Discover all doctoral program application pages from an index page.

    Workflow:
        1. Fetch the index page; extract program name → URL pairs.
        2. For programs not found on the index page, fall back to seed_overrides.
        3. For each program, call discover_program_pages() to classify and crawl.
        4. Deduplicate by URL; sort by (program_name, workflow_priority).

    Args:
        index_url:      URL of the doctoral programs index/deadlines page.
        seed_overrides: {"program_name": str, "url": str} fallback seeds.
                        Each program in seed_overrides that is NOT discovered
                        from the index page is added to the processing queue.
        depth:          Nested crawl depth per program (default 1).
        fetch_fn:       HTTP fetch override for testing.

    Returns:
        List of source dicts with full metadata, ready for ingest_pages().
        Sorted by (program_name, workflow_priority).
    """
    if fetch_fn is None:
        from rag.ingestion import fetch_page
        fetch_fn = fetch_page

    print(f"\n[discovery] Starting full program discovery")
    print(f"[discovery] Index URL: {index_url}")

    # ── 1. Extract program links from index page ──────────────────────────────
    index_html = fetch_fn(index_url)
    if index_html is not None:
        index_links = _extract_program_links_from_index(index_html, index_url)
        print(f"[discovery] Index page: {len(index_links)} program link(s) found")
    else:
        print("[discovery] Index page unavailable — using seed_overrides only")
        index_links = []

    # ── 2. Build program → seed URL map ──────────────────────────────────────
    # Index-page links take precedence; seed_overrides fill the gaps.
    programs: dict[str, str] = {}

    for entry in index_links:
        name = (entry.get("program_name") or "").strip()
        url  = (entry.get("url") or "").strip()
        if name and url:
            programs[name] = url

    if seed_overrides:
        for seed in seed_overrides:
            name = (seed.get("program_name") or "").strip()
            url  = (seed.get("url") or "").strip()
            if name and url and name not in programs:
                programs[name] = url
                print(f"[discovery]   seed fallback: {name}")

    print(f"[discovery] {len(programs)} program(s) to process")

    # ── 3. Discover pages for each program ───────────────────────────────────
    all_sources: list[dict] = []
    seen_urls:   set[str]   = set()

    for prog_name in sorted(programs):
        seed_url = programs[prog_name]
        print(f"\n[discovery] → {prog_name}")

        pages = discover_program_pages(
            program_name=prog_name,
            seed_url=seed_url,
            index_url=index_url,
            depth=depth,
            fetch_fn=fetch_fn,
        )

        for page in pages:
            u = page.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                all_sources.append(page)

        time.sleep(_CRAWL_DELAY)

    all_sources.sort(key=lambda d: (
        d.get("program_name", ""),
        d.get("workflow_priority", 5),
    ))

    print(f"\n[discovery] Complete: {len(all_sources)} page(s) across {len(programs)} program(s)")
    return all_sources


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Standalone discovery run — prints all discovered program pages.

    Run from the project root:
        python -m rag.discovery
        python -m rag.discovery --depth 0   # classify seeds only (faster)
        python -m rag.discovery --depth 1   # default: follow nested links
    """
    import sys

    depth = 1
    if "--depth" in sys.argv:
        idx = sys.argv.index("--depth")
        try:
            depth = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    # Import after package init to avoid circular dependency issues
    from rag.ingestion import PAGE_SOURCES, PROGRAM_SOURCES

    INDEX_URL = PAGE_SOURCES[1]["url"]  # deadlines / index page
    seeds = [
        {"program_name": s.get("program_name", ""), "url": s["url"]}
        for s in PROGRAM_SOURCES
        if s.get("program_name")
    ]

    print("=" * 70)
    print(f"CSULB RAG Discovery  (depth={depth})")
    print("=" * 70)

    results = discover_all_programs(
        index_url=INDEX_URL,
        seed_overrides=seeds,
        depth=depth,
    )

    print(f"\n{'Program':<45} {'Category':<28} {'P':>2}  URL")
    print("-" * 110)
    for r in results:
        print(
            f"{r['program_name']:<45} "
            f"{r['content_category']:<28} "
            f"{r['workflow_priority']:>2}  "
            f"{r['url']}"
        )
    print(f"\nTotal: {len(results)} page(s)")
