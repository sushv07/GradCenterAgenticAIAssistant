"""
tools/application_links.py
Generic structured-link classifier for application resources (Option A).

Consumes the anchor entries ingestion already stores as `links_json`
(`[{"text", "url"}]`) and derives a structured link:

    {"label": str, "url": str, "kind": str, "section": str}

Everything is generic — kinds and labels come from URL / anchor-text / filename
patterns and a small canonical-portal map, never from a per-program branch. This
module changes NO ingestion behavior and requires NO Chroma rebuild; it only
re-interprets links that are already stored.

IMPORTANT — inferred sections:
    `section` here is INFERRED FROM `kind` (see _KIND_SECTION), NOT the true
    nearest-heading of the anchor on the source page. Real heading-section
    fidelity would require ingestion to record the enclosing heading per link
    (it currently flattens the page via get_text); that is a documented future
    ingestion enhancement, deliberately out of scope for this phase.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Kinds and their inferred sections
# ---------------------------------------------------------------------------

_KIND_SECTION: dict[str, str] = {
    "program_page":             "program_overview",
    "information_sheet":        "supporting_documents",
    "department_application":   "application_process",
    "university_application":   "application_process",
    "transcript_information":   "supporting_documents",
    "applicant_portal":         "post_submission",
    "application_guide":        "application_process",
    "employment_verification":  "supporting_documents",
    "other_official_resource":  "other",
}

ALL_KINDS = tuple(_KIND_SECTION)

# Anchor labels too weak to ever surface — derive a better one instead.
_WEAK_LABELS = frozenset({
    "resource", "resources", "apply now", "cal apply", "apply", "document",
    "documents", "click here", "here", "more info", "more information", "link",
    "read more", "learn more", "view", "download", "form", "online", "website",
    "page", "info",
})

# Canonical labels for well-known application destinations.
_CANONICAL_LABEL: dict[str, str] = {
    "university_application": "Cal State Apply",
    "applicant_portal":       "Applicant Self-Service",
    "transcript_information": "Official Transcripts Information",
    "employment_verification": "Employment Verification",
}


def section_for_kind(kind: str) -> str:
    """The inferred section for a kind (see module note on inference)."""
    return _KIND_SECTION.get(kind, "other")


# ---------------------------------------------------------------------------
# Kind classification (URL + anchor text + filename)
# ---------------------------------------------------------------------------

def classify_kind(text: str, url: str) -> str:
    """Derive a generic resource kind from the anchor text and URL."""
    t = (text or "").lower()
    u = (url or "").lower()
    path = unquote(urlparse(u).path)

    # Department / program-specific application portals: form builders
    # (Qualtrics/Formstack), centralized application services (PTCAS/CASPA/…),
    # or explicit "department/program application" phrasing.
    if "qualtrics.com" in u or "formstack" in u or "wufoo" in u:
        return "department_application"
    if re.search(r"\b(ptcas|caspa|sophas|nursingcas|otcas|atcas|gradcas|pharmcas|"
                 r"vmcas|cascas)\b", t + " " + u) \
       or "centralized application service" in t:
        return "department_application"
    if re.search(r"(department|program|school of|nursing|college of).{0,30}application", t):
        return "department_application"

    # University application — Cal State Apply
    if re.search(r"(calstate\.edu/apply|calstateapply|apply\.calstate|/apply(?:$|[/?]))", u) \
       or re.search(r"\b(cal\s*state\s*apply|cal\s*apply|calstate\s*apply)\b", t) \
       or ("apply now" in t):
        # ... unless it is clearly a *guide* PDF (handled below)
        if not (path.endswith(".pdf") and "guide" in (t + path)):
            return "university_application"

    # PDFs — information sheet vs application guide vs generic
    if path.endswith(".pdf"):
        blob = f"{t} {path.lower()}"
        if "guide" in blob:
            return "application_guide"
        if re.search(r"(information|info|fact)\s*sheet|factsheet", blob):
            return "information_sheet"
        return "other_official_resource"

    if re.search(r"application\s+guide|graduate\s+application\s+guide", t):
        return "application_guide"
    if "transcript" in t or "transcript" in path.lower():
        return "transcript_information"
    if re.search(r"employment\s+verification|verification\s+of\s+employment|employment\s+history", t):
        return "employment_verification"
    if re.search(r"applicant\s+self.?service|self.?service|\bmyced\b|applicant\s+portal|"
                 r"application\s+status|status\s+portal|check\s+your\s+status", t + " " + u):
        return "applicant_portal"

    # An official csulb.edu program/overview page.
    host = (urlparse(u).netloc or "").lower()
    if "csulb.edu" in host and re.search(r"program|overview|graduate|degree|dnp|drph|dpt|phd|edd",
                                         path.lower() + " " + t):
        return "program_page"

    return "other_official_resource"


# ---------------------------------------------------------------------------
# Label derivation
# ---------------------------------------------------------------------------

def _label_from_filename(url: str) -> str:
    """Turn a document URL's filename into a readable label.

    e.g. ".../BSN-DNP%20Information%20Sheet.pdf" -> "BSN-DNP Information Sheet".
    Preserves ALL-CAPS acronyms and hyphenated codes (BSN-DNP).
    """
    name = unquote(urlparse(url or "").path).rsplit("/", 1)[-1]
    name = re.sub(r"\.(pdf|docx?|pptx?)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[_]+", " ", name).strip()
    words = []
    for w in name.split():
        if w.isupper() or "-" in w or re.search(r"\d", w):
            words.append(w)                      # keep acronyms / codes as-is
        else:
            words.append(w[:1].upper() + w[1:])
    return " ".join(words).strip()


def _is_weak(label: str) -> bool:
    return re.sub(r"\s+", " ", (label or "").strip().lower()) in _WEAK_LABELS


def derive_label(text: str, url: str, kind: str) -> str:
    """Prefer a semantic label; never surface weak anchor text.

    Order: canonical label for the kind → a good (non-weak) anchor text →
    filename-derived label (documents) → a kind default.
    """
    anchor = re.sub(r"\s+", " ", (text or "").strip())

    if kind == "application_guide":
        # keep a descriptive anchor if it names a guide, else canonical
        if anchor and not _is_weak(anchor) and "guide" in anchor.lower():
            return anchor
        return "Cal State Apply Graduate Application Guide"

    if kind in _CANONICAL_LABEL:
        return _CANONICAL_LABEL[kind]

    if kind == "information_sheet":
        if anchor and not _is_weak(anchor) and "sheet" in anchor.lower():
            return anchor
        label = _label_from_filename(url)
        return label or "Program Information Sheet"

    if kind == "department_application":
        # strip filler ("HERE"/"click here"/"now"/"apply"); prefix a program
        # code if the anchor carries one (e.g. "DNP APPLICATION HERE" → "DNP
        # Department Application").
        cleaned = re.sub(r"\b(click\s+here|here|now|apply)\b", "", anchor,
                         flags=re.IGNORECASE).strip(" -–—:")
        code = re.search(r"\b([A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]{1,6})?)\b", anchor)
        if code:
            return f"{code.group(1)} Department Application"
        if cleaned and not _is_weak(cleaned) and "application" in cleaned.lower():
            return cleaned
        return "Department Application"

    if kind == "program_page":
        if anchor and not _is_weak(anchor):
            return anchor
        return "Official Program Page"

    # other_official_resource / fallback
    if anchor and not _is_weak(anchor):
        return anchor
    fn = _label_from_filename(url)
    if fn and not _is_weak(fn):
        return fn
    return "Official Resource"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_link(text: str, url: str) -> dict:
    """Classify one anchor into {label, url, kind, section}."""
    kind = classify_kind(text, url)
    return {
        "label":   derive_label(text, url, kind),
        "url":     url,
        "kind":    kind,
        "section": section_for_kind(kind),
    }


def _norm_url(url: str) -> str:
    p = urlparse((url or "").strip())
    netloc = (p.netloc or "").lower()
    path = p.path.rstrip("/")
    query = "&".join(q for q in p.query.split("&") if q and not q.lower().startswith("utm_"))
    return f"{netloc}{path}" + (f"?{query}" if query else "")


# Kinds that represent a single purpose — collapse to one even across distinct
# URLs (e.g. "Cal Apply" + "APPLY NOW" + "Cal State Apply" → one).
_SINGLETON_KINDS = frozenset({"university_application", "applicant_portal", "application_guide"})


def structured_links(entries: list[dict]) -> list[dict]:
    """Classify + deduplicate `links_json` entries into structured links.

    Dedup by (a) normalized URL and (b) semantic purpose: a kind in
    `_SINGLETON_KINDS` yields at most one link (same destination/purpose),
    preferring the canonical destination. Original URLs are preserved verbatim
    on the surviving link (grounding is never lost).
    """
    classified = [classify_link(e.get("text", ""), e.get("url", ""))
                  for e in (entries or []) if e.get("url")]

    out: list[dict] = []
    seen_url: set[str] = set()
    seen_singleton: set[str] = set()
    for link in classified:
        nu = _norm_url(link["url"])
        if nu in seen_url:
            continue
        if link["kind"] in _SINGLETON_KINDS:
            if link["kind"] in seen_singleton:
                continue
            seen_singleton.add(link["kind"])
        seen_url.add(nu)
        out.append(link)
    return out
