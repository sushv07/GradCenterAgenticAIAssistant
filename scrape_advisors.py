"""
scrape_advisors.py
Reads programs.json, visits each program_url, and extracts advisor/contact info.

Requires: pip install beautifulsoup4

Usage:
    python scrape_advisors.py                   # all programs
    python scrape_advisors.py --limit 10        # first N programs
    python scrape_advisors.py --resume          # skip already-done entries

Output: advisors_extracted.json
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INPUT_FILE  = Path(__file__).parent / "programs.json"
OUTPUT_FILE = Path(__file__).parent / "advisors_extracted.json"

# Doctoral advisors page — single authoritative source for all doctoral programs
DOCTORAL_PAGE_URL = (
    "https://www.csulb.edu/graduate-studies-csulb/article/"
    "programs-advisors-and-deadlines-doctoral"
)

DELAY_SECONDS   = 1.5
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CSULB-GradAdvisorScraper/1.0; "
        "+https://www.csulb.edu/graduate-center)"
    )
}

ADVISOR_KEYWORDS = [
    "graduate advisor", "graduate coordinator", "program advisor",
    "program coordinator", "academic advisor", "department advisor",
    "faculty advisor", "advisor", "coordinator",
]

GENERIC_ANCHOR_TEXT = {
    "email", "click here", "here", "contact", "contact us", "send email",
    "email us", "send", "more info", "learn more", "apply", "apply now",
    "website", "link", "send a message", "info", "information",
}

NAME_BLOCKLIST = {
    "University", "California", "Long", "Beach", "College", "Department",
    "Graduate", "Program", "Contact", "Email", "Office", "Phone", "School",
    "Center", "Studies", "Hours", "Faculty", "Student", "Campus",
    "Services", "Administration", "Committee", "Staff", "Division", "Section",
    "Engineering", "Science", "Technology", "Health", "Education", "Affairs",
    "Management", "Institute", "Academy", "Foundation", "Association",
    "Advising", "Enrollment", "Service", "Registration", "Development",
    "Information", "Safety", "Library", "Statistics", "Emergency",
    "Organization", "Organizations", "Resources", "Support",
    # Navigation / UI words commonly found on university pages
    "Give", "Partner", "Partners", "Giving", "Classes", "Scholarship",
    "Scholarships", "Opportunities", "Opportunity", "Events", "News",
    "About", "Home", "Menu", "Search", "Apply", "Visit", "Connect",
    "Explore", "Learn", "Discover", "Current", "Future", "Alumni",
}

# Lower-cased set for fast case-insensitive word-level checks
NAME_BLOCKLIST_LOWER = {w.lower() for w in NAME_BLOCKLIST}

# Words that, if found ANYWHERE in a candidate name, disqualify it immediately
NAME_REJECT_WORDS = {
    "department", "program", "office", "student", "services",
    "engineering", "studies", "center", "school", "development",
    "information", "safety", "registration", "college", "graduate",
    "advising", "administration", "enrollment", "service",
    "scholarship", "opportunities", "classes", "giving", "partner",
}

# Words that are never valid as the FIRST word of a person's name
COMMON_NON_NAME_WORDS = {
    "Organizations", "Organization", "Library", "Statistics",
    "Emergency", "Services", "Resources", "Information",
    "Crime", "Deadline", "Application", "Requirements",
    "The", "And", "Or", "For", "Of", "In", "To", "A", "An",
    # Navigation words that can appear capitalized at start of phrase
    "Give", "Classes", "Scholarship", "Opportunities", "Events",
    "About", "Apply", "Visit", "Connect", "Explore", "Current",
}

# Email local-part substrings that flag a departmental address
DEPT_EMAIL_SUBSTRINGS = {
    "dept", "department", "info", "grad", "office", "chhs", "coe",
    "ced", "cob", "cla", "cota", "cnsm", "cpace", "help", "support",
    "advising", "admin", "noreply", "donotreply", "webmaster",
}

EMAIL_RE  = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE  = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")
OFFICE_RE = re.compile(
    r"\b([A-Z]{2,6}[-\s]?\d{2,4}[A-Z]?)\b"
    r"|\b([A-Z][a-z]+ Hall[,\s]+\d+)\b",
)
TITLE_PREFIX_RE = re.compile(r"^(?:Dr\.?|Prof\.?|Professor|Ms\.?|Mr\.?|Mrs\.?)\s+", re.I)

# Matches "Dr. First Last", "Prof. First Last", or plain "First Last" (2–3 cap words)
NAME_RE = re.compile(
    r"\b(?:(?:Dr\.?|Prof\.?|Professor|Ms\.?|Mr\.?|Mrs\.?)\s+)?"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"
)

# Primary human-name pattern: 2–3 words, each Uppercase, letters/hyphen/apostrophe only
_HUMAN_NAME_RE = re.compile(
    r"^[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,2}$"
)

# How many levels up the DOM tree to search for a name near a mailto link
DOM_WALK_DEPTH = 5


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch_soup(url: str) -> BeautifulSoup:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"fetch failed: {exc}") from exc

    soup = BeautifulSoup(raw, "html.parser")
    for noise in soup(["script", "style", "noscript"]):
        noise.decompose()
    return soup


# ---------------------------------------------------------------------------
# Anchor-tag contact extraction
# ---------------------------------------------------------------------------

def _clean_email(raw: str) -> str:
    if not raw:
        return ""
    email = raw.strip()
    if email.lower().startswith("mailto:"):
        email = email[7:]
    email = email.split("?", 1)[0]
    email = email.replace("%20", "").replace(" ", "").strip()
    return email


def _clean_phone(raw: str) -> str:
    if not raw:
        return ""
    phone = raw.strip()
    if phone.lower().startswith("tel:"):
        phone = phone[4:]
    return phone.strip()


def _looks_like_name(text: str, email: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    if t.lower() == email.lower():
        return False
    if email and email.lower() in t.lower() and len(t) < len(email) + 4:
        return False
    if t.lower() in GENERIC_ANCHOR_TEXT:
        return False
    if not re.search(r"[A-Za-z]", t):
        return False
    if len(t) > 60:
        return False
    candidate = TITLE_PREFIX_RE.sub("", t).strip()
    if not candidate:
        return False
    parts = [p for p in re.split(r"\s+", candidate) if p]
    if len(parts) < 2:
        return False
    cap_parts = [p for p in parts if p[0].isupper()]
    if len(cap_parts) < 2:
        return False
    if all(p.strip(",.") in NAME_BLOCKLIST for p in parts):
        return False
    # Final gate: run through strict validator
    if not _is_valid_name_candidate(TITLE_PREFIX_RE.sub("", t).strip()):
        return False
    return True


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,.")


def _is_valid_name_candidate(name: str) -> bool:
    """
    Return True only if `name` is a plausible human person name.

    Rules (applied in order):
    1. Must match _HUMAN_NAME_RE: 2–3 Capitalized words, letters/hyphen/apostrophe only
    2. Must contain at least one letter; must not contain digits
    3. First word must not be in COMMON_NON_NAME_WORDS
    4. No word from NAME_REJECT_WORDS anywhere in the full string
    5. No individual word is a known institutional term (NAME_BLOCKLIST_LOWER)
    6. No ALL-CAPS word tokens (e.g. "PT", "CHHS")
    """
    if not name or not name.strip():
        return False

    cleaned = name.strip()

    # Rule 1: must match the clean human-name pattern
    if not _HUMAN_NAME_RE.match(cleaned):
        return False

    # Rule 2: no digits
    if re.search(r"\d", cleaned):
        return False

    parts = cleaned.split()

    # Rule 3: first word guard
    if parts[0] in COMMON_NON_NAME_WORDS:
        return False

    name_lower = cleaned.lower()

    # Rule 4: reject if any institutional word appears anywhere in the string
    if any(word in name_lower for word in NAME_REJECT_WORDS):
        return False

    # Rule 5: reject if any individual word is a known institutional term
    if any(p.lower() in NAME_BLOCKLIST_LOWER for p in parts):
        return False

    # Rule 6: reject ALL-CAPS tokens (abbreviations, not names)
    if any(p.isupper() and len(p) > 1 for p in parts):
        return False

    # Rule 7: reject known page-noise words (navigation/header text)
    _BAD_PHRASES = {
        "guidelines", "schedule", "giving", "home",
        "deadlines", "application", "requirements", "admission",
    }
    if any(word in name_lower for word in _BAD_PHRASES):
        return False

    return True


def _is_dept_email(email: str) -> bool:
    """Return True if the email looks like a departmental/generic inbox."""
    if not email or "@" not in email:
        return False
    prefix = email.split("@")[0].lower()
    return any(sub in prefix for sub in DEPT_EMAIL_SUBSTRINGS)


def _extract_name_from_text(text: str) -> str | None:
    """
    Extract a person's name from a chunk of text.
    Prefers names preceded by a title prefix (Dr., Prof., etc.).
    Falls back to any capitalized First Last pattern near advisor keywords.
    """
    # First pass: require title prefix for stronger confidence
    titled = re.compile(
        r"\b(?:Dr\.?|Prof\.?|Professor|Ms\.?|Mr\.?|Mrs\.?)\s+"
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"
    )
    for m in titled.finditer(text):
        name = m.group(1).strip()
        if _is_valid_name_candidate(name):
            return name

    # Second pass: look for "First Last" near advisor keyword context
    lower = text.lower()
    for kw in ADVISOR_KEYWORDS:
        idx = lower.find(kw)
        if idx == -1:
            continue
        window = text[max(0, idx - 60): min(len(text), idx + 200)]
        for m in NAME_RE.finditer(window):
            name = m.group(1).strip()
            if _is_valid_name_candidate(name):
                return name

    return None


# ---------------------------------------------------------------------------
# DOM proximity search for advisor name near a mailto anchor
# ---------------------------------------------------------------------------

def _section_text_around_anchor(a_tag: Tag) -> str:
    """
    Collect text from the DOM context surrounding a mailto <a> tag.

    Strategy (ordered by proximity):
    1. Siblings of the anchor's direct parent (same row/list item/paragraph)
    2. Walk up DOM_WALK_DEPTH levels; at each level collect:
       - The element's own direct text (non-recursive)
       - All preceding siblings' text
       - All following siblings' text
    3. Stop early if an advisor keyword is found in collected text
    """
    chunks: list[str] = []

    def _elem_text(el) -> str:
        if not isinstance(el, Tag):
            return str(el).strip() if el else ""
        return el.get_text(" ", strip=True)

    node = a_tag
    for _ in range(DOM_WALK_DEPTH):
        parent = node.parent
        if parent is None or not isinstance(parent, Tag):
            break

        # Gather text from siblings of `node` within this parent
        for sibling in parent.children:
            if sibling is node:
                continue
            if isinstance(sibling, Tag):
                t = sibling.get_text(" ", strip=True)
            else:
                t = str(sibling).strip()
            if t:
                chunks.append(t)

        # Also include direct (non-recursive) text of the parent itself
        parent_direct = " ".join(
            str(c).strip() for c in parent.children
            if not isinstance(c, Tag) and str(c).strip()
        )
        if parent_direct:
            chunks.append(parent_direct)

        combined = " ".join(chunks)
        # Early exit if we've already captured advisor context
        if any(kw in combined.lower() for kw in ADVISOR_KEYWORDS):
            break

        node = parent

    return " ".join(chunks)


def _extract_name_near_anchor(a_tag: Tag) -> str | None:
    """
    Given a mailto <a> tag, search the surrounding DOM for an advisor name.
    Returns the best candidate name string, or None.
    """
    context_text = _section_text_around_anchor(a_tag)
    if not context_text.strip():
        return None
    return _extract_name_from_text(context_text)


# ---------------------------------------------------------------------------
# Full anchor extraction (email + phone + DOM-proximity name)
# ---------------------------------------------------------------------------

def _extract_from_anchors(soup: BeautifulSoup) -> dict:
    """
    Walk every <a> tag and collect emails (with names) and phones.

    Name resolution order for each mailto link:
      1. Anchor text itself (if it looks like a name)
      2. DOM proximity search in parent/siblings
      3. Left as None (plain-text fallback happens later)

    Returns:
        {
          "pairs":  [(email, name_or_None), ...]   in document order
          "phones": [phone_str, ...]               in document order
        }
    """
    pairs: list[tuple[str, str | None]] = []
    phones: list[str] = []
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()

    for a in soup.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        href = a["href"].strip()
        href_lower = href.lower()

        if href_lower.startswith("mailto:"):
            email = _clean_email(href)
            if not email or email in seen_emails:
                continue
            seen_emails.add(email)

            # 1. Try anchor text first
            anchor_text = a.get_text(" ", strip=True)
            if _looks_like_name(anchor_text, email):
                name: str | None = _normalize_name(anchor_text)
            else:
                # 2. Search DOM context around this anchor
                name = _extract_name_near_anchor(a)
                if name:
                    name = _normalize_name(name)

            # Discard name if it fails strict validation
            if name and not _is_valid_name_candidate(name):
                name = None

            pairs.append((email, name))

        elif href_lower.startswith("tel:"):
            phone = _clean_phone(href)
            digits = re.sub(r"\D", "", phone)
            if digits in ("5629854111", "15629854111"):
                continue  # skip CSULB main switchboard
            if len(digits) >= 10 and digits not in seen_phones:
                seen_phones.add(digits)
                phones.append(phone)

    return {"pairs": pairs, "phones": phones}


# ---------------------------------------------------------------------------
# Plain-text fallbacks (for pages with no mailto/tel links at all)
# ---------------------------------------------------------------------------

def _find_advisor_context(text: str) -> str:
    lower = text.lower()
    for kw in ADVISOR_KEYWORDS:
        idx = lower.find(kw)
        if idx != -1:
            start = max(0, idx - 80)
            end   = min(len(text), idx + 320)
            return text[start:end]
    return ""


def _extract_text_emails(text: str) -> list[str]:
    found = list(dict.fromkeys(EMAIL_RE.findall(text)))
    noise = {"noreply", "webmaster", "no-reply", "donotreply"}
    return [_clean_email(e) for e in found if not any(n in e.lower() for n in noise)]


def _extract_text_phones(text: str) -> list[str]:
    return list(dict.fromkeys(PHONE_RE.findall(text)))


def _extract_office(text: str) -> str | None:
    m = OFFICE_RE.search(text)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip() or None


# ---------------------------------------------------------------------------
# Doctoral page DOM-based parser + per-run cache
# ---------------------------------------------------------------------------

# Module-level cache: populated on first call to _doctoral_records(), shared
# across all extract_advisor() calls in a single run.
_doctoral_cache: list[dict] | None = None

# Regex helpers for program-name normalisation used in matching
_NORM_DASH_RE  = re.compile(r"[–—]")          # en/em dash → plain hyphen
_NORM_NOISE_RE = re.compile(r"[^\w\s\-]")     # remove everything except word chars, spaces, hyphens


def _norm_prog_name(s: str) -> str:
    """Lowercase + normalise dashes + strip noise chars for fuzzy matching."""
    s = _NORM_DASH_RE.sub("-", s.lower())
    s = _NORM_NOISE_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _prog_names_match(a: str, b: str) -> bool:
    """
    Return True when program names `a` (from programs.json) and `b` (from the
    doctoral page) refer to the same programme.

    The doctoral page appends degree suffixes like "(Ed.D.)" or "(Ph.D.)" that
    are absent in programs.json, so we test substring containment after
    normalisation rather than exact equality.
    """
    na, nb = _norm_prog_name(a), _norm_prog_name(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def extract_from_doctoral_page(soup: BeautifulSoup) -> list[dict]:
    """
    DOM-based parser for the CSULB doctoral advisors page.

    Page structure (per program card):
      <table>                             ← outer card table (no parent <table>)
        <tbody><tr><td><div>
          <p><img alt="…"/></p>
          <p><a class="button …">PROGRAM NAME</a></p>
          <p>Advisor Email: <a href="mailto:…">ADVISOR NAME</a></p>
          <p>Phone: XXX-XXX-XXXX</p>
          <table>…</table>               ← nested deadlines table (excluded)
        </div></td></tr></tbody>
      </table>
    """
    results: list[dict] = []

    for card in soup.find_all("table"):
        # Skip nested tables (the deadlines table sits inside the card table)
        if card.find_parent("table"):
            continue
        if "advisor email" not in card.get_text(" ", strip=True).lower():
            continue

        # (A) Program name — from the <a class="button …"> link inside the card
        prog_link = card.find(
            "a",
            class_=lambda c: bool(c and ("button" in c if isinstance(c, str)
                                         else any("button" in x for x in c))),
        )
        program_name: str | None = (
            prog_link.get_text(" ", strip=True) if prog_link else None
        )

        # Inner deadlines table — anchors inside it must be excluded
        inner_table = card.find("table")

        # (B) Advisor email anchor — the mailto: link whose parent <p> contains
        #     "Advisor Email:", excluding any anchors inside the deadlines table.
        advisor_a: Tag | None = None
        for a in card.find_all("a", href=True):
            if not a["href"].lower().startswith("mailto:"):
                continue
            if inner_table and inner_table in a.parents:
                continue
            p_parent = a.find_parent("p")
            if p_parent and "advisor email" in p_parent.get_text(" ", strip=True).lower():
                advisor_a = a
                break

        if advisor_a is None:
            continue

        email: str | None = _clean_email(advisor_a["href"]).strip() or None

        # Name: join without separator so split spans like
        # "Dr. J<span>eff Rodrigues</span>" recombine cleanly, then strip noise.
        raw = re.sub(r"\s+", " ",
                     advisor_a.get_text("", strip=False)).strip()
        raw = re.sub(r"\(opens in new tab\)", "", raw, flags=re.I).strip()
        raw = re.sub(r"\s+", " ", raw).strip()
        stripped = TITLE_PREFIX_RE.sub("", raw).strip()
        name: str | None = stripped if _is_valid_name_candidate(stripped) else None

        # (C) Phone — first <p> sibling after the advisor-email <p> that
        #     contains a phone-like pattern; skip the university switchboard.
        phone: str | None = None
        advisor_p = advisor_a.find_parent("p")
        if advisor_p:
            for sib in advisor_p.find_next_siblings("p"):
                sib_text = sib.get_text(" ", strip=True)
                if "phone" not in sib_text.lower():
                    continue
                m = PHONE_RE.search(sib_text)
                if m:
                    digits = re.sub(r"\D", "", m.group())
                    if digits not in ("5629854111", "15629854111"):
                        phone = m.group()
                break

        results.append({
            "program":      program_name,
            "advisor_name": name,
            "email":        email,
            "phone":        phone,
            "office":       None,
            "source":       DOCTORAL_PAGE_URL,
        })

    return results


def _doctoral_records() -> list[dict]:
    """
    Return the parsed doctoral-page records, fetching and caching them on the
    first call.  Returns an empty list if the page cannot be reached.
    """
    global _doctoral_cache
    if _doctoral_cache is None:
        try:
            soup = _fetch_soup(DOCTORAL_PAGE_URL)
            _doctoral_cache = extract_from_doctoral_page(soup)
        except Exception:
            _doctoral_cache = []
    return _doctoral_cache


# ---------------------------------------------------------------------------
# Per-program extraction
# ---------------------------------------------------------------------------

def extract_advisor(program: dict) -> dict:
    url  = program.get("program_url", "")
    name = program.get("program", "")

    base: dict = {
        "program":      name,
        "advisor_name": None,
        "email":        None,
        "phone":        None,
        "office":       None,
        "source":       url,
    }
    if not url:
        return base

    # 1. Check doctoral page first (fetched once per run, then cached).
    #    If this program appears there, its data is authoritative — return immediately.
    for r in _doctoral_records():
        if _prog_names_match(name, r.get("program") or ""):
            result = dict(r)
            result["source"] = url or DOCTORAL_PAGE_URL
            return result

    try:
        soup = _fetch_soup(url)
    except RuntimeError as exc:
        base["error"] = str(exc)
        return base

    # 2. Pull contacts from anchors (with DOM-proximity name search)
    anchors = _extract_from_anchors(soup)

    advisor_name: str | None = None
    email: str | None        = None

    # Walk pairs: collect name and email independently so a valid name found
    # near a generic dept email is never discarded.
    for e, n in anchors["pairs"]:
        if n and advisor_name is None:
            advisor_name = n        # first valid name wins
        if email is None:
            email = e               # first email wins as initial candidate

    # Email selection: prefer email paired with a valid name over generic inboxes
    if advisor_name is not None:
        # Find the email that was paired with the advisor name
        for e, n in anchors["pairs"]:
            if n == advisor_name:
                email = e
                break
    elif anchors["pairs"]:
        # No name found — prefer a non-dept email if available
        personal = [e for e, _ in anchors["pairs"] if not _is_dept_email(e)]
        email = personal[0] if personal else anchors["pairs"][0][0]

    phone = anchors["phones"][0] if anchors["phones"] else None

    # 3. Plain-text fallbacks
    page_text = soup.get_text(" ", strip=True)
    ctx = _find_advisor_context(page_text)

    if email is None:
        text_emails = _extract_text_emails(page_text)
        email = text_emails[0] if text_emails else None

    if phone is None:
        text_phones = _extract_text_phones(ctx or page_text[:3000])
        phone = text_phones[0] if text_phones else None

    # 4. Name fallback: plain-text search within advisor keyword context only
    if advisor_name is None and ctx:
        advisor_name = _extract_name_from_text(ctx)

    # Final guard: discard any name that fails strict validation
    if advisor_name is not None and not _is_valid_name_candidate(advisor_name):
        advisor_name = None

    base["advisor_name"] = advisor_name
    base["email"]        = email
    base["phone"]        = phone
    base["office"]       = _extract_office(ctx or page_text[:3000])
    return base


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",  type=int, default=None, help="Process only first N programs")
    parser.add_argument("--resume", action="store_true",    help="Skip programs already in output file")
    args = parser.parse_args()

    programs: list[dict] = json.loads(INPUT_FILE.read_text())
    if args.limit:
        programs = programs[: args.limit]

    existing: dict[str, dict] = {}
    if args.resume and OUTPUT_FILE.exists():
        for entry in json.loads(OUTPUT_FILE.read_text()):
            existing[entry["program"]] = entry
        print(f"Resuming — {len(existing)} already done, {len(programs) - len(existing)} remaining.")

    results: list[dict] = []
    total = len(programs)

    for i, prog in enumerate(programs, 1):
        prog_name = prog.get("program", "")

        if args.resume and prog_name in existing:
            results.append(existing[prog_name])
            continue

        print(f"[{i}/{total}] {prog_name}")
        try:
            entry = extract_advisor(prog)
        except Exception as exc:
            entry = {
                "program":      prog_name,
                "advisor_name": None,
                "email":        None,
                "phone":        None,
                "office":       None,
                "source":       prog.get("program_url", ""),
                "error":        str(exc),
            }
            print(f"         ⚠  {exc}")
        else:
            print(
                f"         ✓  email={entry['email'] or '—'}  "
                f"name={entry['advisor_name'] or '—'}  "
                f"phone={entry['phone'] or '—'}"
            )

        results.append(entry)
        OUTPUT_FILE.write_text(json.dumps(results, indent=2))
        time.sleep(DELAY_SECONDS)

    print(f"\nDone — {len(results)} records saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()