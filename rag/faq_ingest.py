"""
rag/faq_ingest.py
Phase 4.1 — structured, atomic FAQ extraction for the persistent Chroma store.

This is a *specialist extractor*, mirroring rag.ingestion._parse_deadlines_page:
given the raw HTML of the CSULB Graduate Center FAQ portal, it returns a list of
production-compatible page dicts — ONE per FAQ entry — which rag.ingestion feeds
through the SAME chunking/persistence pipeline as every other page type. It does
not build a vector store, embed, retrieve, or duplicate any production ingestion
logic; it only turns one coarse FAQ page into many atomic FAQ documents.

The guaranteed unit is ONE DOCUMENT PER FAQ (not one chunk per FAQ):
    The FAQ is the natural semantic + citation unit. A single whole-page document
    (the prior behavior) blurs dozens of unrelated Q/A pairs into one vector,
    destroying retrieval precision. Each FAQ becomes its own "Q: …\nA: …"
    document, preserving the question↔answer bond. Chunk COUNT then follows the
    existing production chunker's size rules: a short FAQ answer stays one chunk;
    a long answer may legitimately split into several. This module adds no
    FAQ-specific chunking.

Identity (the verified blocker), in preference order:
    document_id derives from md5(source_url) (ingestion/pipeline/ids.py). Every
    FAQ shares the portal URL, so without a unique per-FAQ URL their document_ids
    — and therefore chunk_ids — collide and Chroma upserts overwrite each other.
    1. PREFERRED — the portal's own stable anchor. Each FAQ answer is
       <div class="collapse" id="accordion-NNNNNNN">, so we use
       "{portal}#{collapse_id}". This is CMS-assigned (stable across reloads and
       independent of FAQ ordering) AND a genuine deep link that scrolls to the
       exact FAQ. Category plays no part in identity here.
    2. FALLBACK (no anchor) — a deterministic readable slug plus a short
       content-derived hash: "{portal}#faq-{question-slug}-{hash8}", where hash8 =
       sha256(normalized_category + question)[:8]. Order-independent (no "-2/-3"
       suffixes) and collision-safe for slug-equivalent-but-distinct questions.
    Both are deterministic and stable across re-ingestion; no random UUIDs.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

# Extensions that are not HTML articles — skipped during supporting-page
# discovery so the generic parser is never handed a binary blob.
_NON_HTML_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
    ".zip", ".rar", ".gz", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".mp4", ".mov", ".mp3", ".ics",
)

# The question accordion selector proven against the live portal (the same one
# retrieval/faq_rag_module.py uses). Category headings are the section headings
# that do NOT carry this class.
_QUESTION_CLASS = "accordion-heading"
_CATEGORY_TAGS = ("h1", "h2", "h3")
_SLUG_MAX = 60


def _slugify(text: str) -> str:
    """Deterministic, URL-safe slug: lowercase, non-alphanumeric → hyphen,
    collapsed and trimmed, length-capped. Stable for identical input."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:_SLUG_MAX].strip("-")


def _clean_question(text: str) -> str:
    """Strip leading list numbering ("1. ", "12. ") so slugs and display text are
    clean — matches faq_rag_module's convention. Note: the numbering is
    order-dependent and is intentionally removed BEFORE identity is derived, so
    reordering FAQs never changes their identity."""
    return re.sub(r"^\d+\.\s*", "", (text or "").strip()).strip()


def _norm(text: str) -> str:
    """Normalize text for hashing: lowercase, whitespace-collapsed, trimmed."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _content_hash8(category: str, question: str) -> str:
    """Deterministic 8-hex-char content hash from normalized category+question.
    Distinguishes identical-slug-but-distinct questions without any dependence on
    document order."""
    seed = f"{_norm(category)}\x00{_norm(question)}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:8]


def _faq_identity_url(source_url: str, collapse: Tag, category: str, question: str) -> str:
    """Unique per-FAQ URL. Preferred: the portal's stable collapse-element anchor
    ({portal}#accordion-NNNN) — order-independent and a real deep link. Fallback
    (no anchor present): {portal}#faq-{question-slug}-{content-hash}."""
    anchor = (collapse.get("id") or "").strip()
    if anchor:
        return f"{source_url}#{anchor}"
    slug = _slugify(question) or "faq"
    return f"{source_url}#faq-{slug}-{_content_hash8(category, question)}"


def _extract_links(block: Tag, base_url: str) -> list[dict]:
    """Absolute, de-duplicated content links inside one FAQ answer block."""
    links: list[dict] = []
    seen: set[str] = set()
    for a in block.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = a.get_text(strip=True).rstrip(".,;:")
        if not href or not text or len(text) < 3:
            continue
        if href.startswith(("#", "javascript", "mailto:", "tel:")):
            continue
        full = urljoin(base_url, href)
        if full not in seen:
            seen.add(full)
            links.append({"text": text, "url": full})
    return links


def _nearest_category(question_heading: Tag) -> str:
    """Best-effort category for a question: the nearest preceding section heading
    that is NOT itself an accordion question heading. Returns "" when the page has
    no discernible category structure — category is metadata, never identity, so
    an empty value is safe."""
    prev = question_heading.find_previous(
        lambda t: isinstance(t, Tag)
        and t.name in _CATEGORY_TAGS
        and _QUESTION_CLASS not in (t.get("class") or [])
    )
    return prev.get_text(separator=" ", strip=True) if prev else ""


def parse_faq_page(html: str, source_url: str, title: str) -> list[dict]:
    """Parse the FAQ portal HTML into atomic FAQ page dicts.

    Returns one production-compatible page dict per FAQ:
        {
          "url":                unique fragment URL (identity seed + citation),
          "page_type":          "faq",
          "title":              the FAQ question (readable per-doc title),
          "text":               "Q: <question>\\nA: <answer>",
          "links":              [{"text","url"}, ...],
          "char_count":         int,
          "category":           section heading text (best-effort, may be ""),
          "faq_question":       the clean question,
          "parent_faq_url":     "" (atomic FAQs are top-level; supporting pages
                                 in Phase 4.2 set this to their parent FAQ),
          "is_supporting_page": False,
          "source_url":         same as "url",
        }

    Returns [] when no accordion FAQ entries are found, so the caller
    (rag.ingestion.ingest_pages) can fall back to the generic parser — ingestion
    never breaks on an unexpected page shape.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []

    for h in soup.find_all("h2", class_=_QUESTION_CLASS):
        question = _clean_question(h.get_text(separator=" ", strip=True))
        if not question:
            continue

        # accordion-heading → card-header → card → div.collapse (answer body)
        card_header = h.parent
        card = card_header.parent if card_header else None
        collapse = card.find("div", class_="collapse") if card else None
        if not collapse:
            continue

        answer = re.sub(r"\s+", " ", collapse.get_text(separator=" ", strip=True)).strip()
        if not answer:
            continue

        category = _nearest_category(h)
        links = _extract_links(collapse, source_url)

        # Identity: prefer the portal's stable collapse anchor; deterministic
        # slug+content-hash fallback otherwise. Order-independent either way;
        # category is not a structural identity component.
        faq_url = _faq_identity_url(source_url, collapse, category, question)
        text = f"Q: {question}\nA: {answer}"

        entries.append({
            "url":                faq_url,
            "page_type":          "faq",
            "title":              question,
            "text":               text,
            "links":              links,
            "char_count":         len(text),
            "category":           category,
            "faq_question":       question,
            "parent_faq_url":     "",
            "is_supporting_page": False,
            "source_url":         faq_url,
        })

    return entries


# ---------------------------------------------------------------------------
# Supporting-page discovery (Phase 4.2) — PURE, no network.
# ---------------------------------------------------------------------------

def _canonical_url(url: str) -> str:
    """Canonical form for dedup + identity: http(s) only, fragment dropped,
    trailing slash normalized. Returns "" for non-http(s) or empty input."""
    p = urlsplit((url or "").strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme, p.netloc, path, p.query, ""))  # fragment removed


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().split(":")[0]


def _in_allowlist(url: str, allowlist_domain: str) -> bool:
    """Same-domain check: host equals the allowlisted domain or is a subdomain
    of it. External domains are rejected."""
    host = _host(url)
    dom = (allowlist_domain or "").strip().lower()
    return bool(dom) and (host == dom or host.endswith("." + dom))


def _is_non_html(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(_NON_HTML_SUFFIXES)


def discover_supporting_links(
    faq_pages: list[dict],
    *,
    allowlist_domain: str,
    known_source_urls: frozenset[str] | set[str] = frozenset(),
) -> list[dict]:
    """From already-parsed atomic FAQ pages, select the directly-linked
    supporting pages to ingest (depth-1). PURE and deterministic — no fetching.

    Rules (see Phase 4.2 crawl rules):
      * reuse the links Phase 4.1 already extracted (no new crawling),
      * same-domain only (allowlist), skip external domains,
      * skip obvious non-HTML resources (PDFs, images, …),
      * skip URLs that are already primary ingestion sources — they share the
        real URL, so ingesting them again as faq_supporting would collide on
        document_id (md5(url)) and overwrite; skipping avoids duplicates,
      * de-duplicate by canonical URL — a page linked from several FAQs is
        ingested ONCE; the FIRST referencing FAQ (document order) is recorded as
        its parent (deterministic parent linkage),
      * cycles are impossible by construction: depth is 1 (we never follow links
        of supporting pages) and each canonical URL is emitted at most once.

    Returns supporting SOURCE dicts (not fetched):
        {"url", "title", "parent_faq_url", "parent_faq_question"}
    ready for rag.ingestion to run through fetch_page()/parse_page().
    """
    known = {_canonical_url(u) for u in known_source_urls}
    known.discard("")
    seen: set[str] = set()
    out: list[dict] = []

    for faq in faq_pages:
        for link in faq.get("links", []):
            url = _canonical_url(link.get("url", ""))
            if not url or url in seen or url in known:
                continue
            if not _in_allowlist(url, allowlist_domain) or _is_non_html(url):
                continue
            seen.add(url)
            out.append({
                "url":                 url,
                "title":               (link.get("text") or "").strip(),
                "parent_faq_url":      faq.get("url", ""),
                "parent_faq_question": faq.get("faq_question", ""),
            })
    return out
