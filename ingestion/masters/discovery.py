"""
ingestion/masters/discovery.py
Stage 1 — parse the Graduate Studies master's index into a DiscoveryManifest.

Calibrated (Phase P3) to the REAL index structure: the page is not one flat
table but ~60+ program "cards". Each card is an <a> whose visible text ends with
a degree in parentheses, e.g. "Accountancy (MS)", followed by advisor
office/email/phone and a small per-card "Deadlines*" table whose first data
column is the Application deadline and second is the Accept/Decline deadline
(one Spring row, one Fall row, values like "Spring: November 01").

Discovery records raw values verbatim (interpretation happens in Stage 2) and
emits discovery-time warnings for missing links, ambiguous names, and incomplete
deadline blocks. It produces a DiscoveryManifest, never a CanonicalProgram.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from ingestion.masters.hashing import content_hash
from ingestion.masters.manifest import DiscoveredProgram, DiscoveryManifest

# A program-card link: visible text ends with a degree label in parentheses.
_DEG_IN_PARENS = re.compile(r"\(([A-Za-z.][A-Za-z. ]{0,15})\)\s*$")
_SEASON_CELL = re.compile(r"^\s*(Spring|Fall|Summer|Winter)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_PHONE = re.compile(r"Phone:\s*([0-9()\-.  ]{7,})", re.IGNORECASE)
_NOT_ACCEPTING = re.compile(r"not\s+accept", re.IGNORECASE)


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def _none_if_blank(value: Optional[str]) -> Optional[str]:
    v = _norm_ws(value or "")
    return v or None


def _card_cell(anchor):
    """Nearest ancestor <td> that holds the whole card (or None)."""
    node = anchor
    while node is not None and getattr(node, "name", None) != "td":
        node = node.parent
    return node


def _parse_deadline_table(cell) -> dict[str, Optional[str]]:
    out = {"spring_app": None, "spring_ad": None, "fall_app": None, "fall_ad": None}
    if cell is None:
        return out
    table = cell.find("table")
    if table is None:
        return out
    for row in table.find_all("tr"):
        cells = [_norm_ws(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        for col, text in enumerate(cells):
            m = _SEASON_CELL.match(text)
            if not m:
                continue
            season = m.group(1).lower()
            value = m.group(2).strip()
            slot = "app" if col == 0 else "ad"
            key = f"{season}_{slot}"
            if key in out and out[key] is None:
                out[key] = value
    return out


def _parse_contact(cell) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(advisor_office, advisor_email, phone)."""
    if cell is None:
        return None, None, None
    office = email = phone = None
    mailto = cell.find("a", href=re.compile(r"^mailto:", re.IGNORECASE))
    if mailto is not None:
        email = _none_if_blank(mailto["href"].split(":", 1)[1])
        office = _none_if_blank(mailto.get_text(" ", strip=True))
    text = _norm_ws(cell.get_text(" ", strip=True))
    pm = _PHONE.search(text)
    if pm:
        phone = _none_if_blank(pm.group(1))
    return office, email, phone


def _parse_stem(cell) -> Optional[bool]:
    """True only when an explicit STEM marker is present in the card; otherwise
    None (unknown) — never fabricated."""
    if cell is None:
        return None
    if re.search(r"\bSTEM\b", cell.get_text(" ", strip=True)):
        return True
    for img in cell.find_all("img"):
        if "stem" in (str(img.get("alt", "")) + str(img.get("src", ""))).lower():
            return True
    return None


def _term_availability(spring_app: Optional[str], fall_app: Optional[str]) -> list[str]:
    avail = []
    if fall_app and not _NOT_ACCEPTING.search(fall_app):
        avail.append("fall")
    if spring_app and not _NOT_ACCEPTING.search(spring_app):
        avail.append("spring")
    return avail


def discover_from_html(
    html: bytes | str,
    *,
    source_url: str,
    discovered_at: Optional[datetime] = None,
) -> DiscoveryManifest:
    """Parse index HTML into a DiscoveryManifest (no fetching, no normalization)."""
    raw = html if isinstance(html, bytes) else html.encode("utf-8")
    discovered_at = discovered_at or datetime.now(timezone.utc)
    soup = BeautifulSoup(raw, "html.parser")

    manifest_warnings: list[str] = []
    programs: list[DiscoveredProgram] = []
    seen: set[tuple[str, str]] = set()
    name_counts: dict[str, int] = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        # A program card is identified by its link SHAPE (degree in parens), not
        # its host. Official-host enforcement belongs at fetch time (HttpFetcher),
        # which keeps discovery testable and host-agnostic.
        if not href.startswith("http"):
            continue
        text = _norm_ws(anchor.get_text(" ", strip=True))
        m = _DEG_IN_PARENS.search(text)
        if not m:
            continue
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)

        degree = m.group(1).strip()
        name = _norm_ws(text[:m.start()])
        if not name:
            continue

        cell = _card_cell(anchor)
        office, email, phone = _parse_contact(cell)
        dl = _parse_deadline_table(cell)
        stem = _parse_stem(cell)

        warnings: list[str] = []
        if cell is None:
            warnings.append("could not locate the program card container")
        if dl["fall_app"] and not _NOT_ACCEPTING.search(dl["fall_app"]) and not dl["fall_ad"]:
            warnings.append("incomplete deadline block: fall accept/decline missing")
        if dl["spring_app"] and not _NOT_ACCEPTING.search(dl["spring_app"]) and not dl["spring_ad"]:
            warnings.append("incomplete deadline block: spring accept/decline missing")

        name_counts[name] = name_counts.get(name, 0) + 1
        programs.append(DiscoveredProgram(
            raw_listing_name=text,
            normalized_program_name=name,
            degree_label=degree,
            official_program_url=href,
            advisor_office=office,
            advisor_email=email,
            phone=phone,
            spring_application_deadline=dl["spring_app"],
            spring_accept_decline_deadline=dl["spring_ad"],
            fall_application_deadline=dl["fall_app"],
            fall_accept_decline_deadline=dl["fall_ad"],
            term_availability=_term_availability(dl["spring_app"], dl["fall_app"]),
            stem_designated=stem,
            warnings=warnings,
        ))

    if not programs:
        manifest_warnings.append("no program cards found in the discovery index")

    for prog in programs:
        if name_counts.get(prog.normalized_program_name, 0) > 1:
            prog.warnings.append("ambiguous program name (duplicate listing)")

    return DiscoveryManifest(
        discovery_source_url=source_url,
        discovery_source_hash=content_hash(raw),
        discovered_at=discovered_at,
        programs=programs,
        warnings=manifest_warnings,
    )
