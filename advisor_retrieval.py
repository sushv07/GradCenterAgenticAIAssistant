"""
advisor_retrieval.py
Simple retrieval layer for the CSULB Graduate Advisor AI Assistant.

Usage:
    python advisor_retrieval.py
"""

import json
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

from gradcenter_logging import emit

DATA_FILE = Path(__file__).parent / "advisors_extracted.json"


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_advisors(path: Path = DATA_FILE) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Error: data file not found at {path}", file=sys.stderr)
        return []
    except json.JSONDecodeError as exc:
        print(f"Error: could not parse JSON — {exc}", file=sys.stderr)
        return []


advisors: list[dict] = load_advisors()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD      = 90   # minimum score to return a confirmed match
SUGGESTION_THRESHOLD = 70   # minimum score to return "did you mean?" suggestions
AMBIGUITY_THRESHOLD  = 89   # if 2+ programs score this, treat query as ambiguous → suggestions
NEAR_EXACT_THRESHOLD = 95   # if top full-ratio ≥ this, an exact alias matched → skip ambiguity

STOP_WORDS = {
    # question/conversational words
    "who", "do", "i", "should", "contact", "for", "the",
    "a", "an", "are", "to", "is", "me", "my", "about", "with",
    "how", "what", "where", "can", "get", "find", "want",
    "talk", "speak", "tell", "reach", "email", "call",
    # domain filler that carries no program signal
    "apply", "advisor", "advisors", "program", "programs",
    "graduate", "grad", "doctoral", "doctorate",
    "csulb", "university",
}


def normalize_query(query: str) -> str:
    """
    Lowercase, strip punctuation, remove stop words.

    Example:
        "who do I contact for nursing?" -> "nursing"
    """
    # Lowercase and remove punctuation
    cleaned = query.lower()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)

    # Remove stop words and rebuild
    words = [w for w in cleaned.split() if w not in STOP_WORDS]
    return " ".join(words)


def _best_score_for(query: str, advisor: dict) -> tuple[int, int]:
    """
    Return (partial_score, full_score) for the best-matching candidate
    across program name + aliases.
    partial_score = fuzz.partial_ratio  (primary — catches abbreviations)
    full_score    = fuzz.ratio          (tiebreaker — rewards complete matches)
    """
    candidates = [advisor.get("program") or ""]
    candidates += [a for a in (advisor.get("aliases") or []) if a]

    best_partial, best_full = 0, 0
    for candidate in candidates:
        c = candidate.lower()
        partial = fuzz.partial_ratio(query, c)
        full    = fuzz.ratio(query, c)
        if partial > best_partial or (partial == best_partial and full > best_full):
            best_partial, best_full = partial, full

    return best_partial, best_full


def _emit_advisor_match(
    outcome: str,
    best_partial: int,
    best_full: int,
    matched_program: str,
    normalized_query: str = "",
    **kwargs: object,
) -> None:
    """Emit advisor.match event.  Called at every return path in find_advisor()."""
    level = "WARNING" if outcome in ("ambiguous", "empty_normalized") else "INFO"
    _kw: dict = {}
    if normalized_query:
        _kw["normalized_query"] = normalized_query
    _kw.update(kwargs)
    emit("advisor.match", level=level,
         outcome=outcome,
         best_partial=best_partial,
         best_full=best_full,
         matched_program=matched_program,
         **_kw)


def find_advisor(query: str) -> dict:
    """
    Fuzzy match query against each program's name and aliases list.
    Primary sort: partial_ratio (catches abbreviations / substrings).
    Tiebreaker:   ratio        (prefers the candidate that is a fuller match).

    Always returns a dict with keys:
      match       – advisor record (dict) or None
      confidence  – best partial_ratio score (int)
      suggestions – [] when match found; top-3 program names when no match
    """
    if not query or not query.strip():
        _emit_advisor_match("empty_normalized", 0, 0, "")
        return {"match": None, "confidence": 0, "suggestions": []}

    q = normalize_query(query)
    if not q:                          # query was all stop words
        _emit_advisor_match("empty_normalized", 0, 0, "", normalized_query=q)
        return {"match": None, "confidence": 0, "suggestions": []}

    # Score every advisor record
    scored = []
    for advisor in advisors:
        partial, full = _best_score_for(q, advisor)
        scored.append((partial, full, advisor))

    # Sort descending: primary = partial_ratio, tiebreaker = full ratio
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    best_partial, best_full, best_record = scored[0]

    if best_partial >= FUZZY_THRESHOLD:
        # Ambiguity check — if 2+ programs score near the top AND the top program
        # lacks a near-exact alias match, surface all qualifying programs as
        # suggestions rather than silently picking one.
        #
        # Example:  "education leadership" → partial 100 for P-12, 90 for CC,
        #           best full-ratio 90.9 (< 95) → show both as suggestions.
        #
        # Counter-example: "anthro" → Anthropology has alias "anthro" (full=100 ≥ 95)
        #           → exact alias hit, return it as a single strong match.
        ambiguous = [(p, f, adv) for p, f, adv in scored if p >= AMBIGUITY_THRESHOLD]
        if len(ambiguous) >= 2 and best_full < NEAR_EXACT_THRESHOLD:
            # Unique-token disambiguation: if the query contains tokens that belong
            # exclusively to ONE program's name (e.g. "community" / "college" for the
            # CC Ed.D., "p" / "12" for the P-12 Ed.D.), return that program directly.
            # This handles the case where the user types (or clicks) the full program
            # name — the presence of discriminating words resolves the ambiguity.
            q_tokens = set(q.split())
            for cand_partial, cand_full, cand_adv in ambiguous:
                cand_name = (cand_adv.get("program") or "").lower()
                cand_name = re.sub(r"[^\w\s]", " ", cand_name)
                cand_tokens = set(cand_name.split()) - STOP_WORDS

                # tokens in this program's name that are absent from every other
                # ambiguous program's name
                others_tokens: set[str] = set()
                for _p, _f, other_adv in ambiguous:
                    if other_adv is cand_adv:
                        continue
                    other_name = (other_adv.get("program") or "").lower()
                    other_name = re.sub(r"[^\w\s]", " ", other_name)
                    others_tokens |= set(other_name.split()) - STOP_WORDS

                unique_to_cand = cand_tokens - others_tokens
                if unique_to_cand & q_tokens:
                    # Query contains a token unique to this program → unambiguous
                    _emit_advisor_match(
                        "unambiguous_by_token", cand_partial, cand_full,
                        cand_adv.get("program", ""),
                        normalized_query=q, num_ambiguous=len(ambiguous),
                    )
                    return {
                        "match": cand_adv,
                        "confidence": cand_partial,
                        "suggestions": [],
                    }

            # No unique tokens found → genuinely ambiguous, show all qualifying programs
            _emit_advisor_match(
                "ambiguous", best_partial, best_full,
                best_record.get("program", ""),
                normalized_query=q, num_ambiguous=len(ambiguous),
            )
            return {
                "match": None,
                "confidence": best_partial,
                "suggestions": [
                    adv.get("program", "") for _p, _f, adv in ambiguous[:3]
                    if adv.get("program")
                ],
            }
        _emit_advisor_match(
            "strong_match", best_partial, best_full,
            best_record.get("program", ""), normalized_query=q,
        )
        return {
            "match": best_record,
            "confidence": best_partial,
            "suggestions": [],
        }

    # No strong match — only surface suggestions when query is program-adjacent
    suggestions = []
    if best_partial >= SUGGESTION_THRESHOLD:
        seen = set()
        for partial, full, advisor in scored:
            name = advisor.get("program", "")
            if name and name not in seen:
                suggestions.append(name)
                seen.add(name)
            if len(suggestions) == 3:
                break

    _emit_advisor_match(
        "suggestions" if suggestions else "no_match",
        best_partial, best_full,
        best_record.get("program", ""),
        normalized_query=q, num_suggestions=len(suggestions),
    )
    return {
        "match": None,
        "confidence": best_partial,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _val(record: dict, key: str) -> str:
    v = record.get(key)
    return str(v).strip() if v else "Not available"


def format_result(record: dict) -> str:
    lines = [
        f"  Program:  {_val(record, 'program')}",
        f"  Advisor:  {_val(record, 'advisor_name')}",
        f"  Email:    {_val(record, 'email')}",
        f"  Phone:    {_val(record, 'phone')}",
    ]
    if record.get("office"):
        lines.append(f"  Office:   {record['office']}")
    return "\n".join(lines)


def format_advisor_result(result_dict: dict) -> str:
    """
    Format a find_advisor() result dict into a human-readable string.

    Match path  (result_dict["match"] is not None):
        Converts numeric confidence to a label and prints advisor details.
    No-match path (result_dict["match"] is None):
        Lists top suggestions with numbered entries.
    """
    match      = result_dict.get("match")
    confidence = result_dict.get("confidence", 0)
    suggestions = result_dict.get("suggestions", [])

    if match:
        if confidence >= 90:
            label = "Strong match"
        else:
            label = "Good match"

        lines = [
            f"I found a {label} for your query:",
            "",
            f"  Program: {_val(match, 'program')}",
            f"  Advisor: {_val(match, 'advisor_name')}",
            f"  Email:   {_val(match, 'email')}",
            f"  Office:  {_val(match, 'office')}",
            "",
            "You can reach out to the advisor for guidance.",
            "You can also ask me for application steps.",
        ]
        return "\n".join(lines)

    # No strong match
    lines = [
        "I couldn't find an exact match.",
    ]

    if suggestions:
        lines += ["", "Did you mean:"]
        for i, name in enumerate(suggestions, start=1):
            lines.append(f"  {i}. {name}")

    lines += [
        "",
        "You can also ask me for application steps or explore other programs.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Query handler
# ---------------------------------------------------------------------------

def fallback_response(query: str) -> str:
    """
    Friendly catch-all when no advisor match, suggestions, or next-steps
    guidance could be found for the query.
    """
    return (
        "I'm here to help with doctoral admissions.\n"
        "\n"
        "You can:\n"
        "1. Ask about your program advisor\n"
        "2. Ask for application steps\n"
        "3. Get help choosing a program\n"
        "\n"
        "What would you like to do next?"
    )


def handle_query(query: str) -> str:
    """
    Primary entry point for all user queries.

    Routing order — fully deterministic, no intent classification, no LLM:
      1. find_advisor()      → advisor card / suggestions (non-process queries only)
      2. get_next_steps()    → next-steps list for apply / start / process queries
      3. faq_rag_lookup()    → semantic FAQ match (catches anything next_steps missed)
      4. fallback_response() → catch-all

    Process queries (apply, steps, start …) skip the advisor card so users
    asking "how do I apply?" always land on next-steps, not a program card.
    """
    # Lazy imports to avoid circular dependency.
    from next_steps import get_next_steps, format_next_steps
    from faq_rag_module import faq_rag_lookup

    # 1. Detect strong process intent — these queries bypass the advisor card
    q = query.lower()
    process_keywords = [
        "apply", "application", "steps", "process", "start",
        "begin", "beginning", "confused", "stuck", "where to start",
        "where to begin", "don't know",
    ]
    is_process_query = any(k in q for k in process_keywords)

    # 2. Advisor lookup — always runs, but only shown for non-process queries
    result = find_advisor(query)
    if not is_process_query and (result["match"] is not None or result["suggestions"]):
        return format_advisor_result(result)

    # 3. Next-steps guidance
    steps = get_next_steps(query)
    if steps is not None:
        return format_next_steps(steps)

    # 4. Semantic FAQ lookup — catches questions not matched by intent keywords
    faq = faq_rag_lookup(query)
    if faq:
        return faq["guidance"]

    # 5. Fallback
    return fallback_response(query)


# ---------------------------------------------------------------------------
# CLI loop
# ---------------------------------------------------------------------------

def main() -> None:
    if not advisors:
        print("No advisor data loaded. Run scrape_advisors.py first.")
        sys.exit(1)

    print(f"CSULB Graduate Advisor Lookup  ({len(advisors)} programs loaded)")
    print("Type a program name (or 'quit' to exit).\n")

    while True:
        try:
            query = input("Enter program name: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            break

        print(handle_query(query))
        print()


if __name__ == "__main__":
    main()
