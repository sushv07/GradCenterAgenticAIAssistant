"""
tools/application_steps_tool.py
Retrieve doctoral application process information via RAG with JSON fallback.

Program-aware retrieval strategy:
  1. Detect a specific doctoral program from the query (alias matching).
  2. If a program is detected:
       Pass 1 — retrieve(page_type="program_application", program_name=X, k=8)
       Split results into:
         specific_results: workflow_priority ≤ 4  (department_application,
             supplemental_application, program_requirements, program_eligibility,
             transcript_instructions, international_instructions)
             → program_specific = True
             → overview context merged into supplemental
         overview_results: workflow_priority > 4  (generic_application, overview_only)
             → fall through to generic path; include as supplemental context
       Specificity check uses ANY result (not just top) so that programs whose
       seed page is overview-only but whose nested subpages are specific are
       correctly identified as having program-specific content.
  3. Generic path: page_type="application_process" + supplemental probe.
  4. Fallback: data/admissions.json.

Key design principle: program_specific is determined by workflow_priority
(a discovery-computed value based on page content signals), NOT by hardcoded
per-program logic.  Works identically for all programs, including any future
programs added to the CSULB doctoral index.

workflow_priority scale (from rag.discovery.WORKFLOW_PRIORITY):
    1  department_application    — distinct external portal (e.g. PTCAS)
    2  supplemental_application  — additional form beyond Cal State Apply
    3  program_requirements      — admission requirements, interview, portfolio
    3  program_eligibility       — eligibility criteria, who can apply
    4  transcript_instructions   — how to submit official transcripts
    4  international_instructions— TOEFL/IELTS, credential evaluation
    5  generic_application       — standard Cal State Apply instructions
    6  overview_only             — program description, no actionable steps

Output schema:
    {
        "found":                bool,
        "tool":                 "application_steps_tool",
        "sources":              list[str],
        "error":                None | str,
        "results":              list[dict],   # primary workflow chunks
        "supplemental_results": list[dict],   # context / generic process chunks
        "has_supplemental":     bool,
        "top_score":            float,
        "query":                str,
        "fallback_used":        bool,
        "fallback_data":        list | None,
        "disclaimer":           str,
        "program_name":         str | None,   # detected canonical program, or None
        "program_specific":     bool,         # True when actionable steps exist
        "content_category":     str,          # top result's content_category
        "workflow_priority":    int,          # top result's workflow_priority (1–5)
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from rag import retrieve

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROCESS_URL     = "https://www.csulb.edu/admissions/doctoral-programs-application-process"
_ADMISSIONS_JSON = Path(__file__).parent.parent / "data" / "admissions.json"

# Fixed supplemental probe — always run alongside the main query
_SUPPLEMENTAL_QUERY = "supplemental application doctoral program requirements"

# Workflow priority threshold for program_specific=True.
# Any page whose discovery-computed workflow_priority is ≤ this value is
# considered to have actionable, program-specific application steps.
#
#   1 = department_application      (external portal like PTCAS)
#   2 = supplemental_application    (extra form on top of Cal State Apply)
#   3 = program_requirements        (requirements, interview, portfolio, etc.)
#   3 = program_eligibility         (eligibility criteria, who can apply)
#   4 = transcript_instructions     (how to submit transcripts)
#   4 = international_instructions  (TOEFL/IELTS, credential evaluation)
#
# generic_application (5) and overview_only (6) do NOT qualify as specific.
# Threshold raised from 3 → 4 to include transcript and international pages
# as program-specific context (they are program-specific even if not the
# core application workflow).
# This threshold is the single place to adjust specificity sensitivity;
# no per-program logic is needed.
_SPECIFIC_PRIORITY_THRESHOLD: int = 4

# Program alias → canonical program_name mapping (checked in order; longer phrases first)
_PROGRAM_ALIAS_LIST: list[tuple[str, str]] = [
    # Ed.D.
    ("educational leadership",       "Educational Leadership (Ed.D.)"),
    ("educational doctorate",        "Educational Leadership (Ed.D.)"),
    ("doctor of education",          "Educational Leadership (Ed.D.)"),
    ("edd",                          "Educational Leadership (Ed.D.)"),
    ("ed.d",                         "Educational Leadership (Ed.D.)"),
    # Engineering / Ph.D.
    ("engineering computational",    "Engineering & Computational Mathematics (Ph.D.)"),
    ("computational mathematics",    "Engineering & Computational Mathematics (Ph.D.)"),
    ("engineering phd",              "Engineering & Computational Mathematics (Ph.D.)"),
    ("engineering doctorate",        "Engineering & Computational Mathematics (Ph.D.)"),
    ("engineering doctoral",         "Engineering & Computational Mathematics (Ph.D.)"),
    ("engineering",                  "Engineering & Computational Mathematics (Ph.D.)"),
    # Physical Therapy
    ("physical therapy",             "Physical Therapy (DPT)"),
    ("doctor of physical therapy",   "Physical Therapy (DPT)"),
    ("dpt",                          "Physical Therapy (DPT)"),
    # Public Health
    ("public health",                "Public Health (DR.P.H.)"),
    ("doctor of public health",      "Public Health (DR.P.H.)"),
    ("drph",                         "Public Health (DR.P.H.)"),
    ("dr.p.h",                       "Public Health (DR.P.H.)"),
    # Nursing / DNP
    ("nursing",                      "Nursing (D.N.P.)"),
    ("doctor of nursing practice",   "Nursing (D.N.P.)"),
    ("dnp",                          "Nursing (D.N.P.)"),
    ("d.n.p",                        "Nursing (D.N.P.)"),
    ("bsn-dnp",                      "Nursing (D.N.P.)"),
    ("bsn dnp",                      "Nursing (D.N.P.)"),
]

_DISCLAIMER = (
    "ℹ️  Most doctoral programs require a supplemental application in addition "
    "to the university application via Cal State Apply. Requirements and "
    "deadlines vary by program — contact your program directly to confirm all "
    "required materials before you apply."
)

# Human-readable step title for each content_category.
# Used by _build_steps_from_results() to label each step card.
_CATEGORY_STEP_TITLE: dict[str, str] = {
    "department_application":    "Complete Department Application Portal",
    "supplemental_application":  "Submit Supplemental Application",
    "program_requirements":      "Review Admission Requirements",
    "program_eligibility":       "Check Eligibility Criteria",
    "transcript_instructions":   "Submit Official Transcripts",
    "international_instructions":"International Applicant Requirements",
    "generic_application":       "Apply via Cal State Apply",
    "overview_only":             "Program Overview",
    "":                          "Application Information",
}

# Goal description and optional warning note per content_category.
# Shown in the step card header (matching generic guidance panel format).
_CATEGORY_GOAL: dict[str, str] = {
    "department_application":    "Complete the department's application portal — this is separate from Cal State Apply.",
    "supplemental_application":  "Submit the program's supplemental application in addition to Cal State Apply.",
    "program_requirements":      "Review all admission requirements and confirm you meet every criterion before applying.",
    "program_eligibility":       "Confirm you meet the eligibility requirements for this program.",
    "transcript_instructions":   "Prepare and submit all required transcripts and supporting documents by the deadline.",
    "international_instructions":"Complete the additional steps required for international applicants.",
    "generic_application":       "Submit your university application through Cal State Apply.",
    "":                          "Complete this application requirement.",
}

_CATEGORY_NOTE: dict[str, str] = {
    "department_application":    "This program uses its own portal — do not submit only through Cal State Apply.",
    "supplemental_application":  "Both the Cal State Apply and supplemental applications must be completed.",
    "transcript_instructions":   "Official transcripts must be sent directly from your institution — unofficial copies are not accepted.",
    "international_instructions":"Requirements for international applicants are in addition to, not instead of, domestic requirements.",
}

_DISCLAIMER_DEPT = (
    "⚠️  This program uses a department-specific application portal (not Cal State Apply). "
    "Submit through the department's designated system and verify all requirements "
    "directly with the program."
)

_DISCLAIMER_SUPPLEMENTAL = (
    "⚠️  This program requires a supplemental application in addition to Cal State Apply. "
    "Complete both applications and confirm all deadlines with the program directly."
)

# ---------------------------------------------------------------------------
# Workflow extraction constants
# ---------------------------------------------------------------------------

# Portal links always shown when mentioned in page text
_KNOWN_APP_LINKS: dict[str, str] = {
    "Cal State Apply":        "https://www.calstate.edu/apply",
    "MyCED":                  "https://myced.csulb.edu/",
    "CSULB Graduate Studies": "https://www.csulb.edu/graduate-studies-csulb",
}

# Compiled regex: sentence MUST match one of these to be kept as a bullet.
# Uses word boundaries to prevent "meeting" matching "meet", "applying" matching
# "apply", etc.  Covers all critical application items.
_APP_SIGNAL_RE = re.compile(
    r"\b("
    r"submit|application|apply|deadline|transcript|gpa|"
    r"recommendation|letter of recommendation|statement of purpose|"
    r"resume|writing sample|interview|portal|form\b|materials|"
    r"admissions|supplemental|official|toefl|ielts|english proficiency|"
    r"cal state apply|myced|application fee|non-refundable|"
    r"notification|review committee|international applicant|"
    r"credential evaluation|foreign coursework|"
    r"@[a-z]+\.edu|562-\d{3}-\d{4}|"
    r"next steps?|how to apply|application process|step \d|"
    r"required materials?|required documents?|"
    r"complete.*application|upload.*document|contact.*office|"
    r"visit.*page|admitted|admission committee"
    r")\b",
    re.IGNORECASE,
)

# Compiled noise patterns — sentences matching ANY of these are dropped.
_NOISE_RES: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    # Pure blank / punctuation / fragments
    r"^[\s\.\-\–\—\|]*$",
    # Course codes  e.g. EDLD 732A, NURS 810
    r"^[A-Z]{2,6}\s*\d{3}[A-Z]?\b",
    # Semester / year headers
    r"^\s*(spring|fall|summer|winter)\s+\d{4}\s*$",
    # Prerequisites / co-reqs / grading
    r"^(Prerequisites?:|Co-?req|Letter grade only)",
    # Testimonials: quoted text ≥ 20 chars
    r'"[^"]{20,}"',
    # Marketing / aspirational language
    r"\b(vibrant|dreams?\s+take\s+flight|fuels?|nurtures?|empowers?|unwavering|"
    r"incalculable|transformative|thrilled|delighted|honored|more than just a university|"
    r"make your mark|make their mark|where dreams|take flight)\b",
    # Generic marketing leads (anchored AND unanchored for mid-sentence occurrences)
    r"^We (want|are proud|look forward|believe|strive|are here|hope|encourage|consider)",
    r"\bWe want to be part\b",
    r"\bWe are here to help\b",
    r"\bpart of your journey\b",
    # Undergraduate / credential-only content (doctoral applicants don't need this)
    r"\b(first-time\s+first-year|high\s+school\s+grad|ITEP|post-baccalaureate|"
    r"single\s+subject\s+credential|multiple\s+subject\s+credential|"
    r"education\s+specialist\s+credential|bachelor'?s?\s+degree\s+pathway|"
    r"undergraduate\s+(student|program|credential))\b",
    # Program description leads (not process steps)
    r"^(Prepares?\s+(therapists?|teachers?|counselors?|administrators?|leaders?|students?)\s+to\b|"
    r"Provides?\s+foundations?\s+and|Develops?\s+highly\s+trained|"
    r"Examines?\s+the\s+literacy|Equips?\s+leaders?\s+to|"
    r"Embark\s+on|Strengthen\s+graduate|Become\s+a\s+credentialed)",
    # Navigation / UI instructions
    r"(left-hand|navigation menu|check out the|explore our programs|back to top|"
    r"click here to|see the .{0,20} page)",
    # Social / survey fluff
    r"(student experience|survey results|social media|follow us|like us on)",
    # Pure title fragments (very short all-caps phrases or lone headings)
    r"^[A-Z][a-z]+(\s+[A-Z][a-z]+){0,3}\s*$",   # e.g. "Program Requirements for Ed. D."
    # Accreditation / legal boilerplate
    r"(accredited by|Title IX|equal opportunity|ADA|affirmative action)\b",
    # Course description leads — these describe curriculum, not application steps
    r"^(Exploration of|Examination of|Investigation of|Analysis of|Overview of|"
    r"Study of|Survey of|Introduction to|Foundation[s]? of|Principles of)\b",
    # Course-related content (remove trailing \b so prefixes like "epistemological" match)
    r"\b(epistemolog|ontolog|pedagog|curriculum design|conceptual framework|"
    r"theoretical framework|literature review|dissertation|coursework)",
    # Course unit notation e.g. "Methods (2) Exploration..."
    r"\(\d\)\s+\w",
    # "Explore Next Steps Here" — button/header text
    r"^Explore\s+(Next|Our|Programs|Steps)",
    # Clery / safety act boilerplate
    r"(Clery|Annual Security Report|Campus Safety Plan|Hate Crimes)",
]]

# Case-sensitive noise patterns (compiled WITHOUT re.IGNORECASE).
# Python's re module does not support (?-i) inline flag disabling, so patterns
# that rely on exact-case matching must live in a separate list.
#
# Nav-menu concatenations: a line composed ENTIRELY of CamelCase words with no
# lowercase connectors (no "the", "of", "through", "your", etc.).  With
# re.IGNORECASE those connectors would also satisfy [A-Z][a-z]+, so we need
# strict case here.
#
# Matches: "Educational Leadership Application Process"
#          "Review Notification Admissions Requirements"
# Does NOT match: "Submit your application through Cal State Apply"
#                 ("your", "through" start with lowercase → break the chain)
_NOISE_RES_CS: list[re.Pattern] = [
    re.compile(r"(?:[A-Z][a-z]+\s){3,}[A-Z][a-z]+$"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric except spaces."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _detect_program(query: str) -> Optional[str]:
    """
    Return the canonical program name if the query mentions a known alias,
    or None if no program is identified.

    Checks aliases in order (longer/more specific phrases first).
    Strips punctuation from both query and alias before matching so that
    "d.n.p." and "dnp" both resolve to the same canonical name.
    """
    norm = _normalize(query)
    for alias, canonical in _PROGRAM_ALIAS_LIST:
        alias_norm = _normalize(alias)
        if alias_norm in norm:
            return canonical
    return None


def _load_application_steps_json() -> list | None:
    """
    Load doctoral_application_steps.steps from data/admissions.json.
    Returns None if the file is missing, unreadable, or malformed.
    """
    try:
        raw   = json.loads(_ADMISSIONS_JSON.read_text(encoding="utf-8"))
        block = raw.get("content", {}).get("doctoral_application_steps", {})
        steps = block.get("steps")
        return steps if isinstance(steps, list) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _dedup_sources(*url_lists: list[str]) -> list[str]:
    """Return a deduplicated, order-preserving list of URLs."""
    seen:    set[str]  = set()
    sources: list[str] = []
    for urls in url_lists:
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                sources.append(url)
    return sources


def _top_content_category(results: list[dict]) -> str:
    """Return the content_category of the top result, or '' if none."""
    if not results:
        return ""
    return results[0].get("content_category") or ""


def _top_workflow_priority(results: list[dict]) -> int:
    """
    Return the workflow_priority of the top result.

    workflow_priority is a discovery-computed integer (1–5):
        1  department_application
        2  supplemental_application
        3  program_requirements
        4  generic_application
        5  overview_only / unknown

    Returns 5 if results is empty or the field is missing.
    """
    if not results:
        return 5
    return results[0].get("workflow_priority", 5)


def _is_program_specific(results: list[dict]) -> bool:
    """
    Return True when ANY result has actionable program-specific steps.

    Checks ALL results rather than only the top result so that a program
    whose seed page is "overview_only" but whose discovered nested pages
    include transcript_instructions or department_application is correctly
    identified as having specific content.

    Uses workflow_priority (set by rag.discovery) rather than hardcoded
    content_category names, so any new category below the threshold is
    automatically treated as specific without modifying this code.
    """
    return any(
        r.get("workflow_priority", 6) <= _SPECIFIC_PRIORITY_THRESHOLD
        for r in results
    )


def _choose_disclaimer(content_category: str, program_specific: bool) -> str:
    """Return the most appropriate disclaimer string."""
    if content_category == "department_application":
        return _DISCLAIMER_DEPT
    if content_category == "supplemental_application":
        return _DISCLAIMER_SUPPLEMENTAL
    return _DISCLAIMER


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_application_steps(
    query:            str,
    k:                int   = 14,   # increased from 8: program may have 10+ subpages
    min_score:        float = 0.30,
    supplemental_k:   int   = 3,
    supplemental_min: float = 0.30,
) -> dict:
    """
    Retrieve doctoral application process steps — program-aware.

    Detection logic:
      1. Detect a specific doctoral program from the query.
      2. If detected, run a program-specific RAG pass (page_type=program_application).
         - If actionable steps found (_SPECIFIC_CATEGORIES): return those as primary
           results plus generic context as supplemental.
         - If only overview content found: fall through to generic path.
      3. Generic path: page_type=application_process + supplemental probe.
      4. Fallback: admissions.json.

    Returns the standard tool dict with program_name, program_specific, and
    content_category fields appended.
    """
    if not query or not query.strip():
        return _empty_response(query)

    detected_program = _detect_program(query)
    rag_error: str | None = None

    # ── Program-specific path ─────────────────────────────────────────────────
    if detected_program:
        try:
            prog_results = retrieve(
                query,
                k=k,
                min_score=min_score,
                page_type="program_application",
                program_name=detected_program,
            )
        except Exception as exc:
            rag_error = f"RAG retrieval failed: {exc}"
            prog_results = []

        # Sort by workflow_priority (ascending) so the most actionable chunk
        # comes first.  similarity_search already sorts by score; re-sort by
        # priority to prefer specific workflow steps over generic overviews.
        if prog_results:
            prog_results.sort(key=lambda r: (r.get("workflow_priority", 6), -r["score"]))

        # Split into specific (p ≤ threshold) and overview/generic (p > threshold).
        # Specific pages are the primary results; overview pages become supplemental context.
        specific_results = [
            r for r in prog_results
            if r.get("workflow_priority", 6) <= _SPECIFIC_PRIORITY_THRESHOLD
        ]
        overview_results = [
            r for r in prog_results
            if r.get("workflow_priority", 6) > _SPECIFIC_PRIORITY_THRESHOLD
        ]

        top_category = _top_content_category(specific_results or prog_results)
        top_priority = _top_workflow_priority(specific_results or prog_results)

        # Has actionable program-specific content (ANY result has priority ≤ threshold)
        if specific_results:
            # Merge overview context into supplemental alongside generic process chunks
            generic_context = _generic_supplemental(
                query, supplemental_k, supplemental_min,
                exclude_ids={r.get("chunk_id") for r in specific_results},
            )
            # Append overview chunks not already in generic context (dedup by chunk_id)
            generic_ids = {r.get("chunk_id") for r in generic_context}
            spec_ids    = {r.get("chunk_id") for r in specific_results}
            for chunk in overview_results:
                cid = chunk.get("chunk_id")
                if cid and cid not in generic_ids and cid not in spec_ids:
                    generic_context.append(chunk)
                    generic_ids.add(cid)

            sources = _dedup_sources(
                [r.get("url", "") for r in specific_results],
                [r.get("url", "") for r in generic_context],
                [_PROCESS_URL],
            )
            return {
                "found":                True,
                "tool":                 "application_steps_tool",
                "sources":              sources,
                "error":                None,
                "results":              specific_results,
                "steps":                _build_steps_from_results(specific_results),
                "supplemental_results": generic_context,
                "has_supplemental":     len(generic_context) > 0,
                "top_score":            specific_results[0]["score"],
                "query":                query,
                "fallback_used":        False,
                "fallback_data":        None,
                "disclaimer":           _choose_disclaimer(top_category, True),
                "program_name":         detected_program,
                "program_specific":     True,
                "content_category":     top_category,
                "workflow_priority":    top_priority,
                "workflow_steps":       _extract_workflow_steps(specific_results),
            }

        # Program page found but only overview / generic content — use as context
        overview_context = prog_results  # may be empty (overview_results ≡ prog_results here)

    else:
        overview_context = []

    # ── Generic path ──────────────────────────────────────────────────────────
    main_results: list[dict] = []
    try:
        main_results = retrieve(
            query,
            k=k,
            min_score=min_score,
            page_type="application_process",
        )
    except Exception as exc:
        rag_error = rag_error or f"RAG retrieval failed: {exc}"

    # Supplemental probe — dedup against main results
    main_ids = {r.get("chunk_id") for r in main_results}
    supp_results = _generic_supplemental(
        _SUPPLEMENTAL_QUERY, supplemental_k, supplemental_min,
        exclude_ids=main_ids,
    )

    # Merge overview/requirements context into supplemental (dedup)
    all_supp_ids = {r.get("chunk_id") for r in supp_results}
    for chunk in overview_context:
        cid = chunk.get("chunk_id")
        if cid and cid not in all_supp_ids and cid not in main_ids:
            supp_results.append(chunk)
            all_supp_ids.add(cid)

    sources = _dedup_sources(
        [_PROCESS_URL],
        [r.get("url", "") for r in main_results],
        [r.get("url", "") for r in supp_results],
    )
    top_category = _top_content_category(main_results)
    top_priority = _top_workflow_priority(main_results)

    if main_results:
        return {
            "found":                True,
            "tool":                 "application_steps_tool",
            "sources":              sources,
            "error":                None,
            "results":              main_results,
            "steps":                _build_steps_from_results(main_results),
            "supplemental_results": supp_results,
            "has_supplemental":     len(supp_results) > 0,
            "top_score":            main_results[0]["score"],
            "query":                query,
            "fallback_used":        False,
            "fallback_data":        None,
            "disclaimer":           _choose_disclaimer(top_category, False),
            "program_name":         detected_program,
            "program_specific":     False,
            "content_category":     top_category,
            "workflow_priority":    top_priority,
            "workflow_steps":       _extract_workflow_steps(main_results),
        }

    # ── Fallback: admissions.json ─────────────────────────────────────────────
    fallback_steps = _load_application_steps_json()

    return {
        "found":                fallback_steps is not None,
        "tool":                 "application_steps_tool",
        "sources":              sources,
        "error":                rag_error,
        "results":              [],
        "steps":                [],
        "supplemental_results": supp_results,
        "has_supplemental":     len(supp_results) > 0,
        "top_score":            0.0,
        "query":                query,
        "fallback_used":        True,
        "fallback_data":        fallback_steps,
        "disclaimer":           _choose_disclaimer("", False),
        "program_name":         detected_program,
        "program_specific":     False,
        "content_category":     "",
        "workflow_priority":    6,
        "workflow_steps":       [],
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_all_chunks_for_url(url: str) -> tuple[list[str], list[dict]]:
    """
    Retrieve ALL stored text chunks AND their metadata for a given page URL.

    Returns (docs, metas) sorted by chunk_id (which encodes ingest order) so
    they can be reassembled into the original page text.
    Falls back to ([], []) if the store is unavailable or the URL has no chunks.
    """
    try:
        from rag.store import get_or_build_store
        store = get_or_build_store()
        if store is None:
            return [], []
        result = store._collection.get(
            where={"url": {"$eq": url}},
            include=["documents", "metadatas"],
        )
        docs   = result.get("documents", [])
        metas  = result.get("metadatas", [])
        if not docs:
            return [], []
        # Sort by chunk_id (format: {hash}_{index:04d}) to restore page order
        pairs = sorted(
            zip(docs, metas),
            key=lambda x: x[1].get("chunk_id", ""),
        )
        sorted_docs  = [doc  for doc,  _ in pairs if doc]
        sorted_metas = [meta for _,  meta in pairs]
        return sorted_docs, sorted_metas
    except Exception:
        return [], []


def _merge_raw_chunks(texts: list[str], max_chars: int = 4000) -> str:
    """
    Join raw chunk texts preserving ALL sentence content for bullet extraction.

    Unlike _merge_ordered_chunks (which calls _clean_chunk_text and truncates
    each chunk to 1-2 sentences), this function normalises whitespace only,
    then merges with overlap detection.  Use this as the source text for
    _extract_application_bullets() so no content is discarded before filtering.
    """
    if not texts:
        return ""

    cleaned: list[str] = []
    for t in texts:
        t = re.sub(r"^[\s.·\-–—•]+", "", t).strip()
        t = re.sub(r"\s+", " ", t)
        if t:
            cleaned.append(t)

    if not cleaned:
        return ""

    merged = cleaned[0]
    for nxt in cleaned[1:]:
        tail  = merged[-300:]
        found = False
        for probe_len in range(60, 19, -10):
            pos = tail.rfind(nxt[:probe_len])
            if pos != -1:
                merged += nxt[probe_len:]
                found   = True
                break
        if not found:
            merged += "\n\n" + nxt
        if len(merged) >= max_chars:
            break

    if len(merged) > max_chars:
        merged = merged[:max_chars].rsplit(" ", 1)[0] + "…"
    return merged.strip()


def _merge_ordered_chunks(texts: list[str], max_chars: int = 2400) -> str:
    """
    Reassemble ordered, overlapping sliding-window chunks into a single text.

    Adjacent chunks share ~50 % overlap.  We detect the overlap by searching for
    the start of chunk[i+1] in the tail of the running ``merged`` buffer and
    appending only the non-overlapping suffix.  Falls back to a paragraph-join
    when no overlap is detectable (e.g. non-contiguous chunks).
    """
    if not texts:
        return ""

    merged = _clean_chunk_text(texts[0], max_chars=500)

    for raw in texts[1:]:
        nxt = _clean_chunk_text(raw, max_chars=500)
        if not nxt:
            continue

        # Search window: last 300 chars of merged; probe: first 60-20 chars of nxt
        tail    = merged[-300:]
        found   = False
        for probe_len in range(60, 19, -10):
            needle = nxt[:probe_len]
            pos    = tail.rfind(needle)
            if pos != -1:
                # Append only the part of nxt that doesn't overlap
                merged += nxt[probe_len:]
                found   = True
                break

        if not found:
            # No overlap detected — separate paragraph
            merged += "\n\n" + nxt

        if len(merged) >= max_chars:
            break

    if len(merged) > max_chars:
        merged = merged[:max_chars].rsplit(" ", 1)[0] + "…"

    return merged.strip()


def _merge_chunk_texts(chunks: list[dict], max_chars: int = 900) -> str:
    """
    Merge multiple overlapping RAG chunks from the same page URL into a single
    readable text block.

    Strategy:
      1. Clean each chunk with _clean_chunk_text().
      2. Deduplicate: if a cleaned chunk is a near-substring of another, skip it.
      3. Join the remaining unique chunks with paragraph breaks.
      4. Cap at max_chars.
    """
    cleaned: list[str] = []
    for c in chunks:
        t = _clean_chunk_text(c.get("text", ""), max_chars=500)
        if t:
            cleaned.append(t)

    if not cleaned:
        return ""

    # Remove chunks fully contained in a longer chunk (simple substring dedup)
    deduped: list[str] = []
    for t in cleaned:
        if not any(t in other and t != other for other in cleaned):
            deduped.append(t)

    merged = "\n\n".join(deduped)
    if len(merged) > max_chars:
        merged = merged[:max_chars].rsplit(" ", 1)[0] + "…"
    return merged.strip()


def _clean_chunk_text(text: str, max_chars: int = 220) -> str:
    """
    Extract a readable description from a raw RAG chunk.

    RAG chunks are sliding-window splits, so they often begin with the tail
    of the previous sentence (e.g. ". Please contact the office…").  This
    function skips leading punctuation/whitespace and finds the first full
    sentence that starts with a capital letter.
    """
    if not text:
        return ""
    # Strip leading punctuation / whitespace / bullets
    text = re.sub(r"^[\s.·\-–—•]+", "", text).strip()
    # If the chunk still starts oddly, advance to the first uppercase letter
    m = re.search(r"[A-Z]", text)
    if m and 0 < m.start() < 40:
        text = text[m.start():]
    # Split into sentences and pick 1–2
    sentences = re.split(r"(?<=[.!?])\s+", text)
    desc = sentences[0] if sentences else text
    if len(desc) < 60 and len(sentences) > 1:
        desc = desc + " " + sentences[1]
    if len(desc) > max_chars:
        desc = desc[:max_chars].rsplit(" ", 1)[0] + "…"
    return desc.strip()


def _build_steps_from_results(results: list[dict]) -> list[dict]:
    """
    Convert RAG result chunks into structured numbered step dicts for UI rendering.

    Processing:
      1. Group ALL chunks by URL — multiple chunks from the same page are merged
         into a single coherent ``full_text`` via ``_merge_chunk_texts()``.
      2. Sort URL groups by (workflow_priority ASC, score DESC) — most actionable first.
      3. Use the page's own title as the step title; fall back to category label.
      4. Carry ``discovered_from`` / ``parent_program_url`` for hierarchy linkage.
      5. Add ``related_links`` — other steps whose ``discovered_from`` or
         ``parent_program_url`` matches this step's URL (i.e. pages found via
         this page during discovery).

    Returns a list of step dicts:
        {
            "step":              int,        # 1-based step number
            "title":             str,        # page title (most specific label)
            "category_label":    str,        # human-readable category badge text
            "full_text":         str,        # merged page content (~900 chars)
            "url":               str,        # source URL
            "content_category":  str,        # original content_category value
            "workflow_priority": int,        # 1–6 (lower = more specific)
            "score":             float,      # best cosine similarity for this URL
            "discovered_from":   str,        # URL this page was found via
            "parent_program_url":str,        # program seed URL (or "" for seeds)
            "related_links":     list[dict], # [{title, url, step}] sublinks
        }
    """
    if not results:
        return []

    # ── 1. Group all chunks by URL ────────────────────────────────────────────
    url_groups: dict[str, list[dict]] = {}
    for r in results:
        url = r.get("url", "")
        if url:
            url_groups.setdefault(url, []).append(r)

    # Sort each group: best chunk first (highest score)
    for url in url_groups:
        url_groups[url].sort(key=lambda r: -r.get("score", 0.0))

    # ── 2. Sort URL groups: most actionable (lowest priority) first ────────────
    sorted_urls = sorted(
        url_groups.keys(),
        key=lambda u: (
            url_groups[u][0].get("workflow_priority", 6),
            -url_groups[u][0].get("score", 0.0),
        ),
    )

    # ── 3. Build step dicts ────────────────────────────────────────────────────
    steps: list[dict] = []
    for i, url in enumerate(sorted_urls, 1):
        chunks     = url_groups[url]
        best       = chunks[0]
        category   = best.get("content_category", "")
        page_title = (best.get("title") or "").strip()
        cat_lbl    = _CATEGORY_STEP_TITLE.get(category, "Application Information")
        step_title = page_title if (page_title and len(page_title) > 4) else cat_lbl

        steps.append({
            "step":              i,
            "title":             step_title,
            "category_label":    cat_lbl,
            "full_text":         _merge_chunk_texts(chunks),
            "url":               url,
            "content_category":  category,
            "workflow_priority": best.get("workflow_priority", 6),
            "score":             round(float(best.get("score", 0.0)), 4),
            "discovered_from":   best.get("discovered_from", ""),
            "parent_program_url":best.get("parent_program_url", ""),
            "related_links":     [],   # filled in pass-2 below
        })

    # ── 4. Enrich every step with ALL stored chunks for its URL ──────────────
    # The query-matched chunks in full_text may cover only a fraction of the page.
    # Fetch ALL chunks from ChromaDB for each unique URL and reassemble the full
    # page text.  This gives the user complete, readable content per step.
    for step in steps:
        all_texts, _ = _get_all_chunks_for_url(step["url"])
        if all_texts:
            step["full_text"] = _merge_ordered_chunks(all_texts)
        # else: keep the query-matched full_text already set in step 3

    # ── 5. Add related_links with full inline content ─────────────────────────
    # A step at URL X is a "related link" on step at URL Y when:
    #   discovered_from == Y  (found via Y during discovery crawl)
    #   OR parent_program_url == Y  (Y is the parent seed)
    # Carry full_text so the UI can render each linked page's content inline.
    for step in steps:
        step_url = step["url"]
        related: list[dict] = []
        for other in steps:
            if other["url"] == step_url:
                continue
            if (other.get("discovered_from") == step_url
                    or other.get("parent_program_url") == step_url):
                related.append({
                    "title":          other["title"],
                    "url":            other["url"],
                    "step":           other["step"],
                    "full_text":      other["full_text"],   # full page content
                    "category_label": other["category_label"],
                })
        step["related_links"] = related

    return steps


def _extract_application_bullets(full_text: str, max_bullets: int = 7) -> list[str]:
    """
    Extract concise, actionable application bullets from merged page text.

    Algorithm:
      1. Split on sentence-end boundaries and newlines.
      2. Strip list markers (•, -, *, 1., etc.) from each segment.
      3. Drop any segment that matches a _NOISE_RES pattern.
      4. Drop any segment without an _APP_SIGNAL_RE match (word-boundary, not
         substring — prevents "meet" matching "to meet the needs of society").
      5. Deduplicate by normalised prefix (first 90 chars, lowercase, collapsed
         whitespace).
      6. Capitalise first char, ensure terminal punctuation, cap at max_bullets.
    """
    # Split on:
    #   • sentence-ending punctuation (.!?) followed by whitespace
    #   • newlines (one or more)
    #   • colon + space + capital/digit  — separates preamble ("Please see ... steps:")
    #     from the actual numbered/bulleted items that follow
    #   • inline numbered list markers   — "1. Step text 2. Step text" on one line
    segments = re.split(
        r"(?<=[.!?])\s+"          # sentence end
        r"|\n+"                    # newline break
        r"|:\s+(?=[A-Z0-9])"       # colon before capital/digit (list intro)
        r"|\s+(?=\d+\.\s+[A-Z])",  # space before "1. Capital" inline list item
        full_text,
    )

    bullets: list[str] = []
    seen: set[str] = set()

    for raw_seg in segments:
        # Strip leading list / numbering markers
        seg = re.sub(r"^[\s\-\•\*\d+\.\)]+\s*", "", raw_seg).strip()

        if not seg or len(seg) < 25 or len(seg) > 420:
            continue

        # Drop noise (case-insensitive patterns + case-sensitive patterns)
        if any(pat.search(seg) for pat in _NOISE_RES):
            continue
        if any(pat.search(seg) for pat in _NOISE_RES_CS):
            continue

        # Must have application signal (word-boundary)
        if not _APP_SIGNAL_RE.search(seg):
            continue

        # Deduplicate by normalised 90-char prefix
        norm = re.sub(r"\s+", " ", seg[:90].lower().rstrip("."))
        if norm in seen:
            continue
        seen.add(norm)

        # Normalise capitalisation and terminal punctuation
        seg = seg[0].upper() + seg[1:]
        if seg[-1] not in ".!?":
            seg += "."

        bullets.append(seg)
        if len(bullets) >= max_bullets:
            break

    return bullets


def _extract_page_links(full_text: str, page_metas: list[dict] | None = None) -> list[dict]:
    """
    Return application-relevant links for a page.

    Priority order:
      1. Links embedded in the actual page HTML (stored as links_json in chunk
         metadata during ingestion).  These are the real hrefs — no hardcoding.
         Filtered to keep only links whose text matches an application keyword
         OR whose URL is a known application portal domain.
      2. Fallback: well-known portal names found in full_text mapped to hardcoded
         URLs (_KNOWN_APP_LINKS) — used when links_json is absent (old store
         built before this field was added; cleared on next 24h TTL rebuild).
      3. CSULB email addresses found in full_text (always included).
    """
    links: list[dict] = []
    seen_urls: set[str] = set()

    # ── 1. Real embedded links from ingestion ────────────────────────────────
    # Keep only genuine application portals by exact link-text match or URL pattern.
    # Avoid keyword matching on link text — that pulls in hundreds of site nav links.
    _PORTAL_TEXT_RE = re.compile(
        r"^(MyCED|Cal\s+State\s+Apply|CSULB\s+Graduate\s+Studies|Graduate\s+Studies"
        r"|International\s+Admissions|Applicant\s+Self.Service"
        r"|Cal\s+State\s+Apply\s+Application\s+Support)$",
        re.IGNORECASE,
    )
    _PORTAL_URL_RE = re.compile(
        r"(calstate\.edu/apply|myced|csulb\.edu/graduate-studies)",
        re.IGNORECASE,
    )

    if page_metas:
        for meta in page_metas:
            raw_json = meta.get("links_json", "")
            if not raw_json:
                continue
            try:
                stored_links: list[dict] = json.loads(raw_json)
            except (ValueError, TypeError):
                continue
            for lk in stored_links:
                lk_url  = lk.get("url", "")
                lk_text = (lk.get("text") or "").strip()
                if not lk_url or lk_url in seen_urls:
                    continue
                # Keep only exact portal names or portal-domain URLs
                if _PORTAL_TEXT_RE.match(lk_text) or _PORTAL_URL_RE.search(lk_url):
                    seen_urls.add(lk_url)
                    links.append({"text": lk_text or lk_url, "url": lk_url})
            if links:
                break  # first chunk with links_json is enough (same for whole page)

    # ── 2. Hardcoded fallback (old store without links_json) ─────────────────
    if not links:
        for name, url in _KNOWN_APP_LINKS.items():
            if name.lower() in full_text.lower() and url not in seen_urls:
                seen_urls.add(url)
                links.append({"text": name, "url": url})

    # ── 3. CSULB email addresses ─────────────────────────────────────────────
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@csulb\.edu", full_text)
    for email in dict.fromkeys(emails):
        mailto = f"mailto:{email}"
        if mailto not in seen_urls:
            seen_urls.add(mailto)
            links.append({"text": email, "url": mailto})

    return links


def _extract_workflow_steps(results: list[dict]) -> list[dict]:
    """
    Convert RAG results into concise, deterministic workflow steps.

    Processing:
      1. Group results by URL (each unique URL = one workflow step).
      2. Sort URL groups by (workflow_priority ASC, score DESC).
      3. For each URL, fetch ALL stored chunks from ChromaDB and reassemble
         the full page text via _merge_ordered_chunks().
      4. Extract 3-5 actionable summary points via _extract_summary_points().
      5. Extract related application portal links via _extract_page_links().

    Returns:
        [
            {
                "step":             int,
                "title":            str,   # page title
                "category_label":   str,   # human-readable category
                "summary_points":   list[str],   # 3-5 concise bullets
                "source_url":       str,
                "content_category": str,
                "related_links":    list[{"text": str, "url": str}],
            },
            ...
        ]
    """
    if not results:
        return []

    # ── 1. Group by URL ───────────────────────────────────────────────────────
    url_groups: dict[str, list[dict]] = {}
    for r in results:
        url = r.get("url", "")
        if url:
            url_groups.setdefault(url, []).append(r)

    for url in url_groups:
        url_groups[url].sort(key=lambda r: -r.get("score", 0.0))

    # Derive the program's canonical URL tree root so we can rank program-specific
    # subpages above general college/university pages regardless of RAG score.
    # Example: "/college-of-education/educational-doctorate-educational-leadership"
    # Pages whose URL starts with that root are program-specific (tier 0).
    # Everything else (e.g. /admissions, /college-of-education/admissions-and-how-to-apply)
    # is a general page (tier 1) — shown only if no program-specific content exists.
    _program_root = ""
    for _grp in url_groups.values():
        _ppu = _grp[0].get("parent_program_url", "").rstrip("/")
        if _ppu:
            _program_root = _ppu
            break

    def _url_sort_key(u: str) -> tuple:
        best        = url_groups[u][0]
        specificity = 0 if (_program_root and u.startswith(_program_root + "/")) else 1
        priority    = best.get("workflow_priority", 6)
        neg_score   = -best.get("score", 0.0)
        return (specificity, priority, neg_score)

    sorted_urls = sorted(url_groups.keys(), key=_url_sort_key)

    # ── 2. Skip categories and build raw steps ────────────────────────────────
    _SKIP_CATEGORIES = frozenset({"overview_only", "generic_application"})

    # Regex: at least one summary_point must match to keep the step
    _STEP_SIGNAL_RE = re.compile(
        r"\b("
        r"submit|application|apply|deadline|transcript|gpa|"
        r"recommendation|statement|resume|writing sample|interview|"
        r"portal|form\b|materials|admissions|supplemental|official|"
        r"toefl|ielts|application fee|non-refundable|notification|"
        r"review committee|international applicant|credential evaluation|"
        r"@[a-z]+\.edu|562-\d{3}-\d{4}|how to apply|required"
        r")\b",
        re.IGNORECASE,
    )

    raw_steps: list[dict] = []   # intermediate list before numbering

    for url in sorted_urls:
        best       = url_groups[url][0]
        category   = best.get("content_category", "")

        if category in _SKIP_CATEGORIES:
            continue

        page_title = (best.get("title") or "").strip()
        cat_lbl    = _CATEGORY_STEP_TITLE.get(category, "Application Information")

        # Full text: all stored chunks reassembled, fall back to matched chunks
        all_texts, all_metas = _get_all_chunks_for_url(url)
        # Use _merge_raw_chunks (not _merge_ordered_chunks) so all sentences
        # in every chunk are preserved for _extract_application_bullets().
        # _merge_ordered_chunks internally truncates each chunk to 1-2 sentences
        # via _clean_chunk_text, silently dropping content like "Submit program
        # materials through MyCED" that lives in the second sentence of a chunk.
        full_text = _merge_raw_chunks(all_texts) if all_texts else _merge_chunk_texts(url_groups[url])

        # Strip title-bleed: chunk 0 often starts with the page title concatenated
        # directly into the first sentence, e.g. "Review & Notification The..."
        # Strip the exact page title prefix (with optional trailing whitespace) so
        # the actual sentence content survives bullet filtering.
        extraction_text = full_text
        if page_title and extraction_text.startswith(page_title):
            extraction_text = extraction_text[len(page_title):].lstrip()

        points = _extract_application_bullets(extraction_text)

        # Skip steps with no application signal in extracted bullets
        if not any(_STEP_SIGNAL_RE.search(pt) for pt in points):
            continue

        # Pass chunk metas so _extract_page_links can use the real embedded
        # links (links_json stored during ingestion) rather than hardcoded URLs.
        portal_links = _extract_page_links(full_text, page_metas=all_metas)

        raw_steps.append({
            "title":            page_title or cat_lbl,
            "category_label":   cat_lbl,
            "goal":             _CATEGORY_GOAL.get(category, _CATEGORY_GOAL[""]),
            "note":             _CATEGORY_NOTE.get(category, ""),
            "summary_points":   points,
            "source_url":       url,
            "content_category": category,
            "portal_links":     portal_links,
            "raw_evidence":     full_text[:1800],
        })

    # ── 3. Suppress tier-1 (general) pages when tier-0 content is sufficient ───
    # If we have ≥ 2 program-specific subpages (tier 0), drop general college/
    # university pages (tier 1) — they add noise not useful to the applicant.
    tier0_count = sum(
        1 for rs in raw_steps
        if _program_root and rs["source_url"].startswith(_program_root + "/")
    )
    if tier0_count >= 2:
        raw_steps = [
            rs for rs in raw_steps
            if _program_root and rs["source_url"].startswith(_program_root + "/")
        ]

    # ── 4. Add cross-step related links and assign step numbers ──────────────
    # For each step, related_links = portal links + other steps as cross-refs
    workflow: list[dict] = []
    for i, rs in enumerate(raw_steps, 1):
        cross_links = [
            {"text": other["title"], "url": other["source_url"]}
            for j, other in enumerate(raw_steps)
            if j != i - 1 and other["source_url"] != rs["source_url"]
        ]
        # Merge: portal links first, then cross-step links (dedup by URL)
        seen_link_urls: set[str] = set()
        related: list[dict] = []
        for lk in rs["portal_links"] + cross_links:
            if lk["url"] not in seen_link_urls:
                seen_link_urls.add(lk["url"])
                related.append(lk)

        workflow.append({
            "step":             i,
            "title":            rs["title"],
            "category_label":   rs["category_label"],
            "goal":             rs["goal"],
            "note":             rs["note"],
            "summary_points":   rs["summary_points"],
            "source_url":       rs["source_url"],
            "content_category": rs["content_category"],
            "related_links":    related,
            "raw_evidence":     rs["raw_evidence"],
        })

    return workflow


def _empty_response(query: str) -> dict:
    return {
        "found":                False,
        "tool":                 "application_steps_tool",
        "sources":              [_PROCESS_URL],
        "error":                "Query is empty.",
        "results":              [],
        "supplemental_results": [],
        "has_supplemental":     False,
        "top_score":            0.0,
        "query":                query,
        "fallback_used":        False,
        "fallback_data":        None,
        "disclaimer":           _DISCLAIMER,
        "program_name":         None,
        "program_specific":     False,
        "content_category":     "",
        "workflow_priority":    6,
        "workflow_steps":       [],
    }


def _generic_supplemental(
    query: str,
    k: int,
    min_score: float,
    exclude_ids: set,
) -> list[dict]:
    """
    Run a generic application_process query and return deduplicated results.
    Used as context alongside program-specific primary results.
    """
    try:
        raw = retrieve(
            query,
            k=k,
            min_score=min_score,
            page_type="application_process",
        )
        return [r for r in raw if r.get("chunk_id") not in exclude_ids]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test get_application_steps() with representative queries.

    Run from the project root:
        python -m tools.application_steps_tool
    """
    import textwrap

    TEST_CASES = [
        # Program-specific
        ("DNP",     "how do I apply for the DNP program?"),
        ("DPT",     "physical therapy application steps"),
        ("Ed.D.",   "how do I apply for the edd program?"),
        ("Eng",     "engineering phd application process"),
        # Generic
        (None,      "how do I apply for a doctoral program at CSULB?"),
        (None,      "what documents do I need to submit my application?"),
        # Edge
        (None,      ""),
    ]

    print("=" * 70)
    print("application_steps_tool — CLI smoke test (program-aware)")
    print("=" * 70)

    for expected_prog, query in TEST_CASES:
        result = get_application_steps(query)
        status = "✓" if result["found"] else ("—" if not query else "✗")
        fb_tag = "  [JSON fallback]" if result["fallback_used"] else ""
        prog_tag = f"  [program={result['program_name']}]" if result["program_name"] else ""
        spec_tag = "  [SPECIFIC]" if result["program_specific"] else ""
        cat_tag  = f"  [{result['content_category']}]" if result["content_category"] else ""

        print(
            f"\n  {status}  found={result['found']}  "
            f"top_score={result['top_score']:.4f}"
            f"{fb_tag}{prog_tag}{spec_tag}{cat_tag}"
        )
        print(f"     query: {query!r}  (expected program: {expected_prog})")

        if result["error"]:
            print(f"     error: {result['error']}")

        if result["results"]:
            for i, r in enumerate(result["results"][:2], 1):
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"     [{i}] score={r['score']:.4f}  {snippet}")
            if len(result["results"]) > 2:
                print(f"     … {len(result['results']) - 2} more main result(s)")

        if result["supplemental_results"]:
            print(f"     supplemental ({len(result['supplemental_results'])} chunks):")
            for r in result["supplemental_results"][:1]:
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"       score={r['score']:.4f}  {snippet}")

        if result["fallback_data"]:
            steps = result["fallback_data"]
            print(f"     fallback: {len(steps)} steps loaded from admissions.json")
            if steps:
                s = steps[0]
                print(f"       step 1: {s.get('title')} — {str(s.get('details',''))[:60]}…")

        print(f"     disclaimer: {result['disclaimer'][:80]}…")

    print(f"\n{'='*70}")
    print("application_steps_tool smoke test complete.")


if __name__ == "__main__":
    run_cli_test()
