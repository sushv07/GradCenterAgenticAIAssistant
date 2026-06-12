"""
tools/program_interest_tool.py
Deterministic, template-based Program Interest Response generator.

Generates polished response messages for Graduate Center staff to send to
prospective students who express interest in a CSULB doctoral program.

No LLM or OpenAI required — pure string interpolation against approved templates.

Functions:
    generate_program_specific_response(program_query) → dict
    generate_general_interest_response()               → dict

Both return the standard schema:
    {
        "found":          bool,
        "tool":           "program_interest",
        "response_type":  "program_specific" | "general",
        "program_name":   str | None,
        "advisor_email":  str | None,
        "program_url":    str | None,
        "deadlines":      dict | None,
        "message":        str,
        "sources":        list[str],
        "error":          str | None,
        "suggestions":    list[str],
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from retrieval.advisor_retrieval import find_advisor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROGRAMS_JSON          = Path(__file__).parent.parent / "data" / "programs.json"
_GRAD_STUDIES_URL       = "https://www.csulb.edu/graduate-studies-csulb"
_GRAD_CENTER_EMAIL      = "GraduateCenter@csulb.edu"
_APPLICATION_CYCLE_YEAR = 2027   # next admissions cycle shown in templates

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_TEMPLATE_PROGRAM_SPECIFIC = """\
{PROGRAM_NAME} — Program Guidance

Getting Started

The {PROGRAM_NAME} program page is the recommended starting point for reviewing curriculum details, faculty, research areas, concentration options, and admission requirements:
{PROGRAM_URL}

Requirements, prerequisites, and available tracks vary by program — reviewing the program page before beginning your application is strongly encouraged.

Preparing a Strong Application

A competitive application typically includes:
- A statement of purpose or personal statement
- Official academic transcripts
- Letters of recommendation
- A current resume or CV

The Graduate Center offers free reviews of application materials to help you put your best application forward. Submit materials for review:
https://csulb.qualtrics.com/jfe/form/SV_6XARxv1fwI99C6i

Graduate Center Workshops

Graduate Center workshops are open to both CSULB students and prospective students. Topics include:
- Statement of Purpose / Personal Statement
- Funding Your Graduate Studies
- Resume / CV Writing
- Applying to Graduate School 101

View upcoming workshops and events:
https://www.csulb.edu/graduate-center/workshops-events

Program and Advisor Directory

For the full list of graduate programs, advisor contacts, and application deadlines across CSULB:
https://www.csulb.edu/graduate-studies/article/programs-advisors-and-deadlines-masters

For program-specific questions — including curriculum, prerequisites, and research opportunities — contact your graduate advisor directly. For general questions about graduate study at CSULB, reach the Graduate Center at GraduateCenter@csulb.edu."""

_TEMPLATE_GENERAL = """\
Exploring Graduate Programs at CSULB

California State University, Long Beach offers a wide range of graduate programs designed to support academic growth, career advancement, and original research. Whether you are entering graduate study for the first time or returning to deepen your expertise, the CSULB Graduate Center is here to guide you.

What CSULB Graduate Studies Offers

- Master's degrees, doctoral programs, credentials, and certificates across a broad range of disciplines
- Dedicated graduate advisors for each program
- A research-active academic community with faculty committed to graduate student success
- Flexible program formats to support working professionals and full-time students

Find Your Program

Browse the full list of graduate programs, advisor contacts, and application deadlines:
https://www.csulb.edu/graduate-studies

Use the program directory to filter by discipline, degree type, or area of interest.

Graduate Center Support

The Graduate Center provides centralized support for all prospective and current graduate students at CSULB. Services include:

- Application materials review (resume/CV, personal statement, statement of purpose)
- Workshops on applying to graduate school, funding, and professional development
- One-on-one advising and drop-in support

Submit application materials for review:
https://csulb.qualtrics.com/jfe/form/SV_6XARxv1fwI99C6i

View upcoming Graduate Center workshops and events:
https://www.csulb.edu/graduate-center/workshops-events

Workshop topics include:
- Statement of Purpose / Personal Statement
- Funding Your Graduate Studies
- Resume / CV Writing
- Applying to Graduate School 101

Next Steps

Once you identify a program of interest, visit its program page to review admission requirements, application deadlines, and advisor contact information. For general questions about graduate study at CSULB, contact the Graduate Center at GraduateCenter@csulb.edu."""

# ---------------------------------------------------------------------------
# Deadline matching
# ---------------------------------------------------------------------------

def _load_doctoral_programs() -> list[dict]:
    """Load doctoral program records from data/programs.json."""
    try:
        raw      = json.loads(_PROGRAMS_JSON.read_text(encoding="utf-8"))
        programs = raw["content"]["doctoral_programs"]["programs"]
        return programs if isinstance(programs, list) else []
    except (FileNotFoundError, KeyError, json.JSONDecodeError, OSError):
        return []


def _normalize_name(name: str) -> str:
    """
    Strip degree suffixes and normalize for comparison.

    "Educational Leadership - P-12 Specialization (Ed.D.)" →
    "educational leadership p 12 specialization"
    """
    name = re.sub(r"\([^)]*\)", "", name)   # remove (Ed.D.) etc.
    name = re.sub(
        r"\b(ed\.?d\.?|ph\.?d\.?|d\.?n\.?p\.?|dpt|dr\.?p\.?h\.?|dnp|drph)\b",
        "", name, flags=re.IGNORECASE,
    )
    name = re.sub(r"[-–/]", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def _match_deadline(program_name: str) -> Optional[dict]:
    """
    Return deadlines dict for the closest-matching doctoral program.

    Strategy:
      1. Exact normalized-name match.
      2. Highest word-overlap (≥ 60 % of significant query words present).
    """
    programs = _load_doctoral_programs()
    if not programs:
        return None

    norm_query = _normalize_name(program_name)
    _STOPWORDS = {"with", "from", "that", "this", "have", "more", "than", "also"}
    query_words = {
        w for w in norm_query.split()
        if len(w) >= 4 and w not in _STOPWORDS
    }

    best: Optional[dict] = None
    best_overlap = 0.0

    for prog in programs:
        norm_cand = _normalize_name(prog.get("name", ""))
        if norm_query == norm_cand:
            return prog.get("deadlines") or {}
        if query_words:
            overlap = len(query_words & set(norm_cand.split())) / len(query_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best = prog

    if best and best_overlap >= 0.60:
        return best.get("deadlines") or {}
    return None


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------

_MISSING_DEADLINE = "Please verify current application deadlines on the official program page."
_MISSING_ADVISOR  = "Please refer to the program page for advisor contact information."


def _is_not_accepting(value: str) -> bool:
    return "not accept" in value.lower()


def _fill_program_template(
    program_name:  str,
    program_url:   str,
    advisor_email: Optional[str],
    deadlines:     Optional[dict],
) -> str:
    """Substitute all placeholders in _TEMPLATE_PROGRAM_SPECIFIC."""
    year = str(_APPLICATION_CYCLE_YEAR)

    fall_period   = _MISSING_DEADLINE
    spring_period = _MISSING_DEADLINE
    fall_note     = "Please verify whether fall admission is available for this program."
    spring_note   = "Please verify whether spring admission is available for this program."

    if deadlines:
        fall_raw   = deadlines.get("fall", "")
        spring_raw = deadlines.get("spring", "")

        if fall_raw:
            fall_period = fall_raw
            if _is_not_accepting(fall_raw):
                fall_note = "Note: This program does not offer fall admission."
            else:
                fall_note = ""   # real date — no note needed

        if spring_raw:
            spring_period = spring_raw
            if _is_not_accepting(spring_raw):
                spring_note = "Note: This program does not offer spring admission."
            else:
                spring_note = ""   # real date — no note needed

    fall_note_block   = f"{fall_note}\n" if fall_note else ""
    spring_note_block = f"{spring_note}\n" if spring_note else ""
    advisor_block     = advisor_email if advisor_email else _MISSING_ADVISOR

    return _TEMPLATE_PROGRAM_SPECIFIC.format(
        PROGRAM_NAME              = program_name,
        PROGRAM_URL               = program_url,
        YEAR                      = year,
        FALL_APPLICATION_PERIOD   = fall_period,
        FALL_NOTE                 = fall_note_block,
        SPRING_APPLICATION_PERIOD = spring_period,
        SPRING_NOTE               = spring_note_block,
        ADVISOR_EMAIL             = advisor_block,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_program_specific_response(program_query: str) -> dict:
    """
    Generate a Program Interest Response for a specific doctoral program.

    1. Fuzzy-match program_query against advisor records.
    2. If ambiguous (suggestions present) → found=False with suggestions.
    3. If not found → found=False with error.
    4. Look up deadlines from programs.json.
    5. Fill the program-specific template.

    Args:
        program_query: e.g. "nursing DNP", "DPT physical therapy", "edd p-12".
    """
    if not program_query or not program_query.strip():
        return _error_response("program_specific", "Program query is empty.")

    try:
        result = find_advisor(program_query)
    except Exception as exc:
        return _error_response("program_specific", f"Advisor lookup failed: {exc}")

    match       = result.get("match")
    suggestions = result.get("suggestions", [])

    if match is None:
        if suggestions:
            return {
                "found":         False,
                "tool":          "program_interest",
                "response_type": "program_specific",
                "program_name":  None,
                "advisor_email": None,
                "program_url":   None,
                "deadlines":     None,
                "message":       "",
                "sources":       [],
                "error":         "Ambiguous program — please be more specific.",
                "suggestions":   suggestions,
            }
        return _error_response("program_specific", "Program not found in the database.")

    program_name  = match.get("program", "")
    advisor_email = match.get("email") or None
    program_url   = match.get("source") or _GRAD_STUDIES_URL
    deadlines     = _match_deadline(program_name)

    message = _fill_program_template(
        program_name  = program_name,
        program_url   = program_url,
        advisor_email = advisor_email,
        deadlines     = deadlines,
    )

    sources = [s for s in [program_url, _GRAD_STUDIES_URL] if s]

    return {
        "found":         True,
        "tool":          "program_interest",
        "response_type": "program_specific",
        "program_name":  program_name,
        "advisor_email": advisor_email,
        "program_url":   program_url,
        "deadlines":     deadlines,
        "message":       message,
        "sources":       sources,
        "error":         None,
        "suggestions":   [],
    }


def generate_general_interest_response() -> dict:
    """
    Generate a general Program Interest Response for any graduate program.

    No program-specific lookup required.
    """
    return {
        "found":         True,
        "tool":          "program_interest",
        "response_type": "general",
        "program_name":  None,
        "advisor_email": None,
        "program_url":   None,
        "deadlines":     None,
        "message":       _TEMPLATE_GENERAL,
        "sources":       [_GRAD_STUDIES_URL],
        "error":         None,
        "suggestions":   [],
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _error_response(response_type: str, error: str) -> dict:
    return {
        "found":         False,
        "tool":          "program_interest",
        "response_type": response_type,
        "program_name":  None,
        "advisor_email": None,
        "program_url":   None,
        "deadlines":     None,
        "message":       "",
        "sources":       [],
        "error":         error,
        "suggestions":   [],
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import textwrap

    TEST_CASES: list[tuple[str, str | None]] = [
        ("general",          None),
        ("program_specific", "nursing DNP"),
        ("program_specific", "physical therapy DPT"),
        ("program_specific", "edd p-12"),
        ("program_specific", "engineering phd"),
        ("program_specific", "educational leadership community college"),
        ("program_specific", "public health drph"),
        ("program_specific", "xyzunknown"),
        ("program_specific", "education"),    # expect ambiguous / suggestions
        ("program_specific", ""),             # expect empty error
    ]

    print("=" * 72)
    print("program_interest_tool — CLI smoke test")
    print("=" * 72)

    for rtype, query in TEST_CASES:
        if rtype == "general":
            result = generate_general_interest_response()
            label  = "[GENERAL]"
        else:
            result = generate_program_specific_response(query or "")
            label  = f"[SPECIFIC] {query!r}"

        status = "✓" if result["found"] else "✗"
        print(f"\n{status}  {label}")
        print(f"   program_name : {result['program_name']}")
        print(f"   advisor_email: {result['advisor_email']}")
        print(f"   deadlines    : {result['deadlines']}")
        print(f"   error        : {result['error']}")
        if result["suggestions"]:
            print(f"   suggestions  : {result['suggestions']}")
        if result["message"]:
            preview = textwrap.shorten(result["message"], width=110, placeholder="…")
            print(f"   message      : {preview}")
