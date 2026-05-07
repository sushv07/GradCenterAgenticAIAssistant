"""
tools/deadlines_tool.py
Retrieve deadline information from the CSULB doctoral deadlines page via RAG.

This tool performs a page_type="deadlines" filtered retrieval so results come
exclusively from the "Doctoral Programs, Advisors and Deadlines" source page.

No JSON fallback is used for deadlines — deadline data changes frequently and
stale JSON would be worse than a low-confidence RAG result.  Instead, the tool
attaches a disclaimer directing users to verify against the official CSULB page.

Output schema:
    {
        "found":               bool,
        "tool":                "deadlines_tool",
        "sources":             list[str],    # citation URLs from results
        "error":               None | str,
        "results":             list[dict],   # raw chunk dicts (possibly filtered)
        "top_score":           float,
        "query":               str,
        "disclaimer":          str,          # always present
        "deadline_card":       dict | None,  # structured card for dominant match
        "deadline_cards":      list[dict],   # all parsed program cards (for disambiguation)
        "needs_clarification": bool,         # True when query is too vague
        "clarification_hint":  str,          # "Which program?" prompt text
    }

deadline_card shape:
    {
        "program":      str,
        "application":  {"spring": str, "fall": str},
        "accept_decline": {"spring": str, "fall": str},
        "advisor_contact": {"email": str, "phone": str, "name": str},
        "source_url":   str,
        "score":        float,
    }

Scoring / disambiguation thresholds:
    _CARD_THRESHOLD  — min cosine similarity for the top card to qualify as a
                       "confident" program-specific match that gets a dedicated
                       deadline_card.  Set lower (0.42) than normal RAG because
                       the tabular chunks embed at lower absolute similarity than
                       FAQ prose for natural-language queries.
    _DOMINANT_GAP    — when the top card beats the 2nd card by at least this
                       margin, unrelated lower-ranked chunks are suppressed from
                       the results list (they remain accessible in sources).
"""

from __future__ import annotations

import re
from typing import Optional

from rag import retrieve

# Generic deadline / query words that carry NO program-specificity signal.
_QUERY_STOP = frozenset({
    "the", "a", "an", "for", "of", "and", "or", "in", "is", "are",
    "what", "when", "which", "where", "how", "tell", "show", "me", "all",
    "deadlines", "deadline", "application", "doctoral", "programs", "program",
    "phd", "graduate", "admission", "admissions", "date", "dates", "due",
    "fall", "spring", "semester", "cycle", "submission", "apply",
})

# Canonical source URL — always included in sources even when no RAG results.
_DEADLINES_URL = (
    "https://www.csulb.edu/graduate-studies-csulb/article/"
    "programs-advisors-and-deadlines-doctoral"
)

_DISCLAIMER = (
    "⚠️  Deadlines change each cycle. Always verify the latest dates on the "
    "official CSULB Doctoral Programs, Advisors and Deadlines page before applying."
)

# Thresholds — see module docstring.
_CARD_THRESHOLD    = 0.42   # min score + program-token match → confident card
_DOMINANT_SCORE    = 0.60   # score alone is strong enough even without token match
_DOMINANT_GAP      = 0.10   # top card must beat 2nd by this to suppress others


# ---------------------------------------------------------------------------
# Program-specificity check
# ---------------------------------------------------------------------------

def _query_matches_program(query: str, program_name: str) -> bool:
    """
    Return True if the query contains significant tokens that identify the given
    program, indicating the user asked about that specific program.

    Two passes:
      Pass 1 — word match: any word (≥4 chars, not in _QUERY_STOP) from the
               program name appears in the query after normalisation.
      Pass 2 — abbreviation match: dot-separated abbreviations in the program
               name (e.g. "D.N.P." → "dnp", "Ph.D." → "phd") appear in the
               query string after all non-alphanumeric chars are stripped.

    Examples:
      "deadlines for dnp"    vs. "Nursing (D.N.P.)"          → True  (dnp)
      "physical therapy dpt" vs. "Physical Therapy (DPT)"    → True  (therapy)
      "what are the deadlines" vs. "Engineering (Ph.D.)"     → False
    """
    q_norm   = re.sub(r'[^a-z0-9]', '', query.lower())          # "deadlinesfordnp"
    q_words  = set(re.findall(r'[a-z]{2,}', query.lower())) - _QUERY_STOP

    # Pass 1: significant words from the program name
    for word in re.findall(r'[a-z]{4,}', program_name.lower()):
        if word not in _QUERY_STOP and word in q_words:
            return True

    # Pass 2: abbreviations (strip dots, lowercase, e.g. "D.N.P." → "dnp")
    for token in re.findall(r'\b[\w.]+\b', program_name):
        abbrev = re.sub(r'[^a-z0-9]', '', token.lower())
        if 2 <= len(abbrev) <= 6 and abbrev not in _QUERY_STOP and abbrev in q_norm:
            return True

    return False


# ---------------------------------------------------------------------------
# Chunk → structured card parser
# ---------------------------------------------------------------------------

def _parse_chunk_to_card(chunk: dict) -> Optional[dict]:
    """
    Parse a structured program deadline chunk into a deadline_card dict.

    Recognises chunks produced by rag/ingestion._extract_program_entry():
        Educational Leadership - P-12 Specialization (Ed.D.) — Application Deadlines
        Advisor: Kimberly Word | Email: eddinfo@csulb.edu | Phone: 562-985-4998
        Application:    Spring: Not Accepting | Fall: February 15
        Accept/Decline: Spring: Not Applicable | Fall: April 20

    The "— Application Deadlines" marker on the first line distinguishes program
    chunks from the generic intro chunk (which starts with "Programs, Advisors,
    and Deadlines (Doctoral) …").

    Returns None for non-program chunks (intro text, empty input, etc.)
    """
    text = (chunk.get("text") or "").strip()
    if not text or "— Application Deadlines" not in text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or "— Application Deadlines" not in lines[0]:
        return None

    # ── Program name ─────────────────────────────────────────────────────────
    program = lines[0].split(" — Application Deadlines")[0].strip()
    if not program:
        return None

    # ── Contact line ─────────────────────────────────────────────────────────
    # Format: "Advisor: Name | Email: x@y | Phone: 562-xxx"
    # Advisor and Phone are optional; the line is absent when no contact info.
    advisor_name = email = phone = ""
    contact_line_idx = None

    for i, ln in enumerate(lines[1:], start=1):
        if not (ln.startswith("Application:") or ln.startswith("Accept/Decline:")):
            contact_line_idx = i
            break

    if contact_line_idx is not None:
        for part in lines[contact_line_idx].split("|"):
            part = part.strip()
            if part.startswith("Advisor:"):
                advisor_name = part[8:].strip()
            elif part.startswith("Email:"):
                email = part[6:].strip()
            elif part.startswith("Phone:"):
                phone = part[6:].strip()

    # ── Deadline rows ─────────────────────────────────────────────────────────
    # Format: "Application:    Spring: Not Accepting | Fall: January 15"
    #         "Accept/Decline: Spring: Not Applicable | Fall: April 20"
    app_spring = app_fall = acc_spring = acc_fall = "N/A"

    for ln in lines[1:]:
        if ln.startswith("Application:"):
            rest = ln[len("Application:"):].strip()
            for part in rest.split("|"):
                part = part.strip()
                if part.startswith("Spring:"):
                    app_spring = part[7:].strip() or "N/A"
                elif part.startswith("Fall:"):
                    app_fall = part[5:].strip() or "N/A"

        elif ln.startswith("Accept/Decline:"):
            rest = ln[len("Accept/Decline:"):].strip()
            for part in rest.split("|"):
                part = part.strip()
                if part.startswith("Spring:"):
                    acc_spring = part[7:].strip() or "N/A"
                elif part.startswith("Fall:"):
                    acc_fall = part[5:].strip() or "N/A"

    return {
        "program":         program,
        "application":     {"spring": app_spring,  "fall": app_fall},
        "accept_decline":  {"spring": acc_spring,   "fall": acc_fall},
        "advisor_contact": {"email": email, "phone": phone, "name": advisor_name},
        "source_url":      chunk.get("url") or _DEADLINES_URL,
        "score":           chunk.get("score", 0.0),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_deadlines(
    query:     str,
    k:         int   = 8,
    min_score: float = 0.25,
) -> dict:
    """
    Retrieve deadline-related information scoped to the deadlines source page.

    Uses a lower min_score (0.25) because deadline chunks contain structured
    tabular data that embeds at lower absolute similarity than FAQ prose.

    k is set to 8 by default to retrieve enough chunks for disambiguation
    (the deadlines page produces 7 chunks total: 1 intro + 6 programs).

    Args:
        query:     User question, e.g. "when is the fall deadline for nursing?"
        k:         Max results to return (default 8).
        min_score: Minimum cosine similarity (default 0.25).

    Returns:
        Standard tool dict augmented with deadline-specific fields; see module
        docstring for full schema.
    """
    _empty = {
        "found":               False,
        "tool":                "deadlines_tool",
        "sources":             [_DEADLINES_URL],
        "error":               None,
        "results":             [],
        "top_score":           0.0,
        "query":               query,
        "disclaimer":          _DISCLAIMER,
        "deadline_card":       None,
        "deadline_cards":      [],
        "needs_clarification": False,
        "clarification_hint":  "",
    }

    if not query or not query.strip():
        return {**_empty, "error": "Query is empty."}

    try:
        results = retrieve(query, k=k, min_score=min_score, page_type="deadlines")
    except Exception as exc:
        return {**_empty, "error": f"RAG retrieval failed: {exc}"}

    # ── Parse program cards ───────────────────────────────────────────────────
    # Walk all results in score order; collect successfully-parsed program cards.
    deadline_cards: list[dict] = []
    for r in results:
        card = _parse_chunk_to_card(r)
        if card:
            deadline_cards.append(card)

    # ── Determine primary deadline_card ──────────────────────────────────────
    deadline_card: Optional[dict] = None
    needs_clarification            = False
    clarification_hint             = ""

    if deadline_cards:
        top_card = deadline_cards[0]
        score    = top_card["score"]

        # A specific match is confirmed when EITHER:
        #   (a) score >= _CARD_THRESHOLD AND the query mentions program-specific
        #       tokens (e.g. "dnp", "nursing", "physical therapy") — this handles
        #       program aliases that embed at lower absolute similarity; OR
        #   (b) score >= _DOMINANT_SCORE — raw similarity is so high that the
        #       match is unambiguous even without a token overlap check.
        is_specific = (
            (score >= _CARD_THRESHOLD and _query_matches_program(query, top_card["program"]))
            or score >= _DOMINANT_SCORE
        )

        if is_specific:
            deadline_card = top_card
        else:
            # Score too low or no program token overlap — likely a vague query
            needs_clarification = True
            all_programs = [c["program"] for c in deadline_cards]
            clarification_hint = (
                "Which doctoral program are you asking about? "
                "Available: " + ", ".join(all_programs) + "."
            )
    else:
        # No program chunks found above threshold — entirely vague or no match
        if results:
            needs_clarification = True
            clarification_hint  = (
                "I found some deadline information but couldn't identify a specific "
                "program from your query. Please specify a program — for example: "
                "'deadlines for DNP', 'when is the fall deadline for Physical Therapy?'"
            )

    # ── Filter raw results (suppress unrelated chunks when dominant match) ────
    # When a confident card exists AND it leads the 2nd card by _DOMINANT_GAP,
    # the raw results list is filtered to only the matching chunk + any intro
    # chunks (non-program text).  This keeps the "Sources / Evidence" section
    # tidy without discarding evidence entirely.
    if deadline_card and len(deadline_cards) > 1:
        gap = deadline_card["score"] - deadline_cards[1]["score"]
        if gap >= _DOMINANT_GAP:
            primary_marker = deadline_card["program"] + " — Application Deadlines"
            results = [
                r for r in results
                if primary_marker in r.get("text", "")
                   or "— Application Deadlines" not in r.get("text", "")
            ]
    # If needs_clarification and no dominant card, keep all results for transparency.

    # ── Collect citation URLs ────────────────────────────────────────────────
    seen:    set[str]  = {_DEADLINES_URL}
    sources: list[str] = [_DEADLINES_URL]
    for r in results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            sources.append(url)

    top_score = results[0]["score"] if results else 0.0

    return {
        "found":               len(results) > 0,
        "tool":                "deadlines_tool",
        "sources":             sources,
        "error":               None,
        "results":             results,
        "top_score":           top_score,
        "query":               query,
        "disclaimer":          _DISCLAIMER,
        "deadline_card":       deadline_card,
        "deadline_cards":      deadline_cards,
        "needs_clarification": needs_clarification,
        "clarification_hint":  clarification_hint,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def run_cli_test() -> None:
    """
    Smoke-test get_deadlines() with common deadline queries.

    Run from the project root:
        python -m tools.deadlines_tool
    """
    import textwrap

    TEST_CASES = [
        "when is the fall admission deadline for doctoral programs?",
        "what are the spring application deadlines?",
        "deadlines for dnp",
        "physical therapy application deadline",
        "public health fall deadline",
        "doctoral program submission dates",
        "",
    ]

    print("=" * 65)
    print("deadlines_tool — CLI smoke test")
    print("=" * 65)

    for query in TEST_CASES:
        result = get_deadlines(query)
        status = "✓" if result["found"] else ("—" if not query else "✗")
        card   = result.get("deadline_card")
        clarify = result.get("needs_clarification")
        print(f"\n  {status}  found={result['found']}  top_score={result['top_score']:.4f}")
        print(f"     query:   {query!r}")

        if result["error"]:
            print(f"     error:   {result['error']}")
        elif card:
            print(f"     card:    {card['program']}")
            print(f"              App  Spring={card['application']['spring']!r}  "
                  f"Fall={card['application']['fall']!r}")
            print(f"              A/D  Spring={card['accept_decline']['spring']!r}  "
                  f"Fall={card['accept_decline']['fall']!r}")
            contact = card["advisor_contact"]
            if contact.get("email"):
                print(f"              Email={contact['email']}  Phone={contact.get('phone','')}")
        elif clarify:
            print(f"     clarify: {result['clarification_hint'][:80]}…")
            all_cards = result.get("deadline_cards", [])
            if all_cards:
                print(f"     options: {', '.join(c['program'][:30] for c in all_cards[:4])}")
        elif result["results"]:
            for i, r in enumerate(result["results"][:2], 1):
                snippet = textwrap.shorten(r["text"], width=90, placeholder="…")
                print(f"     [{i}] score={r['score']:.4f}  {snippet}")

        print(f"     disclaimer: {result['disclaimer'][:70]}…")

    print(f"\n{'=' * 65}")
    print("deadlines_tool smoke test complete.")


if __name__ == "__main__":
    run_cli_test()
