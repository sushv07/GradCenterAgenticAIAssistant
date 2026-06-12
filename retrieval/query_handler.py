"""
CSULB Grad Center – Query Handler
Loads index.json, scores data files against the user query, and returns
the most relevant structured content from matching files.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gradcenter_logging import emit

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR      = Path(__file__).parent.parent / "data"
INDEX_FILE    = DATA_DIR / "index.json"
ADVISORS_FILE = Path(__file__).parent.parent / "advisors.json"

# How many data files to load when multiple match
MAX_FILES = 2

# Minimum score to consider a file relevant
MIN_SCORE = 1


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    query: str
    matched_files: list[str]
    content: list[dict[str, Any]]
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "matched_files": self.matched_files,
            "results": self.content,
            "next_steps": self.next_steps,
        }


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------

def load_index() -> dict:
    """Load and return the retrieval index."""
    with INDEX_FILE.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Lowercase and split text into word tokens."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score_file_entry(query_tokens: set[str], query_raw: str, entry: dict) -> int:
    """
    Score a single index entry against the query.

    Scoring rules (cumulative):
    - +3 per multi-word topic phrase fully present in the query
    - +1 per single-word topic token matching a query token
    - +2 per keyword_map key phrase fully present in the query (applied externally)
    """
    score = 0
    query_lower = query_raw.lower()

    for topic in entry.get("topics", []):
        topic_lower = topic.lower()
        if " " in topic_lower:
            if topic_lower in query_lower:
                score += 3
        else:
            if topic_lower in query_tokens:
                score += 1

    return score


def rank_files(query: str, index: dict) -> list[tuple[str, int]]:
    """
    Return data filenames sorted by relevance score (descending).
    Combines topic scoring with keyword_to_file_map boosting.
    """
    query_tokens = _tokenize(query)
    query_lower = query.lower()

    scores: dict[str, int] = {}

    # Score via topic lists
    for entry in index["data_files"]:
        filename = Path(entry["file"]).name
        scores[filename] = _score_file_entry(query_tokens, query, entry)

    # Boost via keyword_to_file_map (multi-word and single-word keys)
    for key, filenames in index["keyword_to_file_map"].items():
        key_lower = key.lower()
        matched = (
            key_lower in query_lower
            if " " in key_lower
            else key_lower in query_tokens
        )
        if matched:
            for filename in filenames:
                scores[filename] = scores.get(filename, 0) + 2

    ranked = sorted(
        [(name, score) for name, score in scores.items() if score >= MIN_SCORE],
        key=lambda x: x[1],
        reverse=True,
    )
    return ranked


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_data_file(filename: str) -> dict:
    """Load a data file by its basename."""
    path = DATA_DIR / filename
    with path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def extract_relevant_sections(query: str, data: dict) -> dict[str, Any]:
    """
    Walk the top-level sections of a data file and return only those whose
    keys or string values contain at least one query token.
    Falls back to the full data if nothing matches.
    """
    query_tokens = _tokenize(query)
    query_lower = query.lower()

    # Fields that are metadata, not content
    skip_keys = {"source", "last_scraped", "source_url", "last_updated",
                 "version", "description", "keyword_to_file_map", "data_files",
                 "id", "schema"}

    def _section_matches(key: str, value: Any) -> bool:
        key_tokens = _tokenize(key)
        if key_tokens & query_tokens:
            return True
        if isinstance(value, str) and any(t in value.lower() for t in query_tokens):
            return True
        if isinstance(value, dict):
            return any(_section_matches(k, v) for k, v in value.items())
        if isinstance(value, list):
            return any(
                _section_matches("", item) if isinstance(item, dict)
                else (isinstance(item, str) and any(t in item.lower() for t in query_tokens))
                for item in value
            )
        return False

    # Unwrap v2 envelope: walk inside "content" rather than treating it as one section
    walk_target = data.get("content") if isinstance(data.get("content"), dict) else data

    top_sections = {
        k: v for k, v in walk_target.items()
        if k not in skip_keys and _section_matches(k, v)
    }

    # Always include title and source for citation
    result: dict[str, Any] = {}
    if "title" in data:
        result["title"] = data["title"]
    if data.get("source_url"):
        result["source"] = data["source_url"]
    elif data.get("source"):
        result["source"] = data["source"]

    result.update(top_sections if top_sections else {
        k: v for k, v in walk_target.items() if k not in skip_keys
    })

    return result


def extract_faq_matches(query: str, faq_data: dict) -> list[dict]:
    """Return FAQ Q&A pairs whose question or answer contains query tokens."""
    query_tokens = _tokenize(query)
    matches = []

    # v2 schema wraps categories under "content"; fall back to legacy top-level
    categories = (faq_data.get("content") or {}).get("categories") or faq_data.get("categories", {})
    for category, items in categories.items():
        if not isinstance(items, list):
            continue
        for item in items:
            q = item.get("q", "")
            a = item.get("a", "")
            combined_tokens = _tokenize(q) | _tokenize(a)
            if combined_tokens & query_tokens:
                matches.append({
                    "category": category,
                    "question": q,
                    "answer": a,
                    "source": item.get("source", ""),
                })

    return matches


# ---------------------------------------------------------------------------
# Advisor routing
# ---------------------------------------------------------------------------

# Keywords that signal an advisor-related query
_ADVISOR_TRIGGERS: set[str] = {
    "advisor", "adviser", "contact",
    "email", "office", "reach", "talk", "speak",
    "program advisor", "graduate advisor", "academic advisor",
}

# Maps query terms → canonical program name (must match advisors.json "program" field)
_PROGRAM_ALIASES: dict[str, str] = {
    "cs":                       "Computer Science (M.S.)",
    "computer science":         "Computer Science (M.S.)",
    "ms cs":                    "Computer Science (M.S.)",
    "ms computer science":      "Computer Science (M.S.)",
    "computer engineering":     "Computer Engineering (M.S.)",
    "ce":                       "Computer Engineering (M.S.)",
}


def is_advisor_query(query: str) -> bool:
    """Return True if the query is asking about an advisor or contact info."""
    query_lower = query.lower()
    query_tokens = _tokenize(query)
    # Check single-word triggers against token set
    single = {t for t in _ADVISOR_TRIGGERS if " " not in t}
    multi  = {t for t in _ADVISOR_TRIGGERS if " " in t}
    if query_tokens & single:
        return True
    # Check multi-word trigger phrases
    return any(phrase in query_lower for phrase in multi)


def extract_program(query: str) -> str | None:
    """
    Extract a canonical program name from the query.
    Tries longest alias match first to avoid partial collisions.
    Returns None if no known program is found.
    """
    query_lower = query.lower()
    # Sort by length descending so multi-word aliases are tried first
    for alias in sorted(_PROGRAM_ALIASES, key=len, reverse=True):
        if alias in query_lower:
            return _PROGRAM_ALIASES[alias]
    return None


def load_advisors() -> list[dict]:
    """Load advisors.json; return empty list if file is missing."""
    if not ADVISORS_FILE.exists():
        return []
    with ADVISORS_FILE.open() as f:
        return json.load(f)


def handle_advisor_query(query: str) -> dict:
    """
    Look up advisor info for the program mentioned in the query.

    Returns a structured dict with:
        route, program, advisors (list of {advisor_name, email, office, role}),
        source, next_steps.
    Falls back to all programs if no specific program is detected.
    """
    program_name = extract_program(query)
    all_entries  = load_advisors()

    if not all_entries:
        return build_fallback(query, reason="no_match")

    # If the user asked about advisors but didn't name a program, ask gently
    if not program_name:
        known = sorted({e["program"] for e in all_entries})
        fb = build_fallback(query, reason="missing_program")
        fb["available_programs"] = known
        return fb

    # Filter to the requested program; if no exact match, surface what we have
    matched = [e for e in all_entries if e["program"].lower() == program_name.lower()]
    if not matched:
        fb = build_fallback(query, reason="missing_program")
        fb["available_programs"] = sorted({e["program"] for e in all_entries})
        return fb

    results = []
    for entry in matched:
        for adv in entry.get("advisors", []):
            results.append({
                "advisor_name": adv.get("advisor_name", ""),
                "role":         adv.get("role", ""),
                "email":        adv.get("email", ""),
                "office":       adv.get("office", ""),
                "notes":        adv.get("notes", ""),
            })

    source = matched[0].get("source_url", "") if matched else ""

    return {
        "route":      "advisor",
        "program":    matched[0]["program"] if matched else (program_name or ""),
        "advisors":   results,
        "source":     source,
        "next_steps": [
            f"Email {results[0]['email']} to schedule an advising appointment"
            if results else "Contact GraduateCenter@csulb.edu for advisor info"
        ],
    }


# ---------------------------------------------------------------------------
# Next-step suggestions
# ---------------------------------------------------------------------------

_NEXT_STEP_RULES: list[tuple[set[str], list[str]]] = [
    (
        {"apply", "application", "applying"},
        [
            "Review admission eligibility at /admissions/graduate-programs-admission-eligibility",
            "Submit your Cal State Apply application at calstate.edu/apply ($70 fee)",
            "Contact the Graduate Center to review your Statement of Purpose",
        ],
    ),
    (
        {"thesis", "dissertation", "formatting", "submission"},
        [
            "Book a pre-submission consultation with the Thesis & Dissertation Office (thesis@csulb.edu)",
            "Check the current submission window at /university-library/thesis-and-dissertation-office/submission-deadlines",
            "Download formatting templates from /thesis-and-dissertation-office/templates",
        ],
    ),
    (
        {"funding", "scholarship", "grant", "fellowship", "money", "financial"},
        [
            "Visit the Graduate Center campus-funding page for travel grants and fellowships",
            "Apply to the Sally Casanova Pre-Doctoral Scholars Program if pursuing a PhD",
            "Check the Financial Aid Office for FAFSA-based awards",
        ],
    ),
    (
        {"mentor", "gradmentor", "mentoring", "peer"},
        [
            "Apply to GradMentor at the start of the fall semester",
            "Contact GraduateCenter@csulb.edu for current program availability",
        ],
    ),
    (
        {"graduation", "graduate", "degree", "commencement"},
        [
            "Submit your graduation application via MyCSULB Student Records",
            "Confirm advancement to candidacy with your graduate advisor",
            "Review the graduation checklist at /registration-and-records/graduation-checklist-masters-students",
        ],
    ),
    (
        {"mental", "health", "counseling", "stress", "wellness"},
        [
            "Schedule a CAPS initial consultation at /student-affairs/counseling-and-psychological-services",
            "Explore Succeeding at the Beach resources at /navigating-grad-studies-at-the-beach/succeeding-at-the-beach",
        ],
    ),
]


def suggest_next_steps(query: str) -> list[str]:
    """Return contextual next steps based on query tokens."""
    query_tokens = _tokenize(query)
    for trigger_tokens, steps in _NEXT_STEP_RULES:
        if trigger_tokens & query_tokens:
            return steps
    return ["Visit https://www.csulb.edu/graduate-center for further guidance"]


# ---------------------------------------------------------------------------
# Friendly fallback (no "I don't know")
# ---------------------------------------------------------------------------

# Topics we *do* have data for — surfaced as alternatives when nothing matches
_TOPIC_SUGGESTIONS: list[dict] = [
    {"label": "Admissions & application steps",
     "example": '"How do I apply to a graduate program?"'},
    {"label": "Program advisors & contacts",
     "example": '"Who is the Computer Science advisor?"'},
    {"label": "Thesis & dissertation submission",
     "example": '"What are the thesis formatting requirements?"'},
    {"label": "Funding, scholarships & grants",
     "example": '"What scholarships are available?"'},
    {"label": "Graduation checklist",
     "example": '"What do I need to graduate this semester?"'},
    {"label": "Mentoring & student support",
     "example": '"How do I join GradMentor?"'},
]

# Always-available human contacts
_FALLBACK_CONTACTS: list[dict] = [
    {
        "name":  "Graduate Center",
        "email": "GraduateCenter@csulb.edu",
        "url":   "https://www.csulb.edu/graduate-center",
        "for":   "general graduate questions",
    },
    {
        "name":  "Thesis & Dissertation Office",
        "email": "thesis@csulb.edu",
        "url":   "https://www.csulb.edu/university-library/thesis-and-dissertation-office",
        "for":   "thesis or dissertation questions",
    },
]


def build_fallback(query: str, reason: str = "no_match") -> dict:
    """
    Friendly, structured fallback when the query can't be answered directly.

    `reason` is informational: "no_match", "empty_query", or "missing_program".
    The response always includes alternative topics, clear next steps, and
    a human contact — never the words "I don't know".
    """
    summaries = {
        "no_match":         "I couldn't find a direct answer for that, but I can definitely point you somewhere useful.",
        "empty_query":      "Looks like your question came through empty — happy to help once you share what you're looking for.",
        "missing_program":  "I'd love to help — could you tell me which program you're asking about? (e.g. Computer Science, Computer Engineering)",
    }

    return {
        "route":       "fallback",
        "query":       query,
        "summary":     summaries.get(reason, summaries["no_match"]),
        "suggestions": _TOPIC_SUGGESTIONS,
        "next_steps":  [
            "Try rephrasing with a specific topic — e.g. admissions, thesis, funding, or advisors",
            "Browse the full Grad Center site at https://www.csulb.edu/graduate-center",
            "Reach out to a human contact below if you'd rather just ask someone",
        ],
        "contacts":    _FALLBACK_CONTACTS,
    }


# ---------------------------------------------------------------------------
# Main query handler
# ---------------------------------------------------------------------------

def handle_query(query: str) -> dict:
    """
    Entry point.

    Args:
        query: Natural-language question from the user.

    Returns:
        Structured dict with matched files, extracted content, and next steps.
    """
    if not query or not query.strip():
        return build_fallback(query or "", reason="empty_query")

    # Advisor queries get their own fast path — no index scoring needed
    if is_advisor_query(query):
        return handle_advisor_query(query)

    index = load_index()
    _t0 = time.perf_counter()
    ranked = rank_files(query, index)
    _kw_elapsed = round((time.perf_counter() - _t0) * 1000, 1)
    _kw_top = [{"file": n, "score": s} for n, s in ranked[:MAX_FILES]]
    _kw_fields: dict = dict(
        num_ranked=len(ranked),
        num_loaded=len(_kw_top),
        top_score=ranked[0][1] if ranked else 0,
        fallback=not bool(ranked),
        elapsed_ms=_kw_elapsed,
    )
    if _kw_top:
        _kw_fields["top_files"] = _kw_top
    emit("keyword.retrieval",
         level="WARNING" if not ranked else "INFO",
         **_kw_fields)

    if not ranked:
        return build_fallback(query, reason="no_match")

    top_files = [name for name, _ in ranked[:MAX_FILES]]
    content = []

    for filename in top_files:
        data = load_data_file(filename)

        if filename == "faqs.json":
            faq_matches = extract_faq_matches(query, data)
            if faq_matches:
                content.append({
                    "file": filename,
                    "source": data.get("source", ""),
                    "title": data.get("title", ""),
                    "faqs": faq_matches,
                })
                continue

        sections = extract_relevant_sections(query, data)
        content.append({
            "file": filename,
            **sections,
        })

    result = QueryResult(
        query=query,
        matched_files=top_files,
        content=content,
        next_steps=suggest_next_steps(query),
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter your query: ")
    output = handle_query(query)
    print(json.dumps(output, indent=2))
