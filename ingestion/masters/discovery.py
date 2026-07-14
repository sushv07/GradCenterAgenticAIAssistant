"""
ingestion/masters/discovery.py
Stage 1 — parse the Graduate Studies master's index into a DiscoveryManifest.

The parser reads an HTML <table> and maps columns by their HEADER TEXT (robust
to column reordering), so it does not hardcode program names or positions. It
records raw deadline strings verbatim (interpretation happens in Stage 2) and
emits discovery-time warnings for missing links, ambiguous names, and incomplete
deadline blocks.

NOTE: the concrete header labels below model the documented structure of the
index; they must be calibrated against the live page before full-inventory
ingestion (see Phase P3 blockers). The architecture is calibration-agnostic —
only the header-alias lists change.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from ingestion.masters.hashing import content_hash
from ingestion.masters.manifest import DiscoveredProgram, DiscoveryManifest

# Header aliases → logical column. Lowercased substring match.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "program": ("program", "major", "degree program"),
    "degree": ("degree", "degree type", "objective"),
    "advisor": ("advisor", "adviser", "program office", "coordinator"),
    "phone": ("phone", "telephone"),
    "spring_app": ("spring application", "spring app", "spring deadline"),
    "spring_ad": ("spring accept", "spring accept/decline", "spring decision"),
    "fall_app": ("fall application", "fall app", "fall deadline"),
    "fall_ad": ("fall accept", "fall accept/decline", "fall decision"),
    "stem": ("stem",),
}

_NOT_ACCEPTING = re.compile(r"not\s+accept", re.IGNORECASE)


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _match_column(header: str) -> Optional[str]:
    """Map a header to a logical column by the LONGEST matching alias, so that
    specific labels win over incidental substrings (e.g. 'Advisor / Program
    Office' maps to advisor via 'program office', not to program via 'program')."""
    h = header.lower()
    best_logical: Optional[str] = None
    best_len = 0
    for logical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in h and len(alias) > best_len:
                best_logical, best_len = logical, len(alias)
    return best_logical


def _cell_text(cell) -> str:
    return _norm_ws(cell.get_text(" ", strip=True))


def _cell_link(cell) -> Optional[str]:
    a = cell.find("a", href=True)
    return a["href"] if a else None


def _none_if_blank(value: str) -> Optional[str]:
    v = _norm_ws(value)
    return v or None


def _parse_stem(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("yes", "y", "true", "stem", "stem-designated"):
        return True
    if v in ("no", "n", "false"):
        return False
    return None


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
    table = soup.find("table")
    if table is None:
        return DiscoveryManifest(
            discovery_source_url=source_url,
            discovery_source_hash=content_hash(raw),
            discovered_at=discovered_at,
            programs=[],
            warnings=["no <table> found in discovery index"],
        )

    # Build the column map from the header row.
    header_cells = []
    thead = table.find("thead")
    header_row = thead.find("tr") if thead else table.find("tr")
    if header_row is not None:
        header_cells = header_row.find_all(["th", "td"])
    col_map: dict[int, str] = {}
    for idx, cell in enumerate(header_cells):
        logical = _match_column(_cell_text(cell))
        if logical:
            col_map[idx] = logical
    if "program" not in col_map.values():
        manifest_warnings.append("could not identify a 'program' column in the index header")

    # Data rows (skip the header row).
    body = table.find("tbody") or table
    rows = [r for r in body.find_all("tr") if r is not header_row]

    programs: list[DiscoveredProgram] = []
    seen_names: dict[str, int] = {}
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        values: dict[str, str] = {}
        links: dict[str, Optional[str]] = {}
        for idx, cell in enumerate(cells):
            logical = col_map.get(idx)
            if not logical:
                continue
            values[logical] = _cell_text(cell)
            if logical == "program":
                links["program"] = _cell_link(cell)
            if logical == "advisor":
                links["advisor"] = _cell_link(cell)

        raw_name = values.get("program", "")
        if not _norm_ws(raw_name):
            continue  # skip structurally empty rows
        normalized = _norm_ws(raw_name)

        warnings: list[str] = []
        url = links.get("program")
        if not url:
            warnings.append("missing official program link")
        seen_names[normalized] = seen_names.get(normalized, 0) + 1

        spring_app = _none_if_blank(values.get("spring_app", ""))
        spring_ad = _none_if_blank(values.get("spring_ad", ""))
        fall_app = _none_if_blank(values.get("fall_app", ""))
        fall_ad = _none_if_blank(values.get("fall_ad", ""))

        term_availability: list[str] = []
        if fall_app and not _NOT_ACCEPTING.search(fall_app):
            term_availability.append("fall")
        if spring_app and not _NOT_ACCEPTING.search(spring_app):
            term_availability.append("spring")

        # Incomplete deadline block: an accepting term missing its accept/decline.
        if fall_app and not _NOT_ACCEPTING.search(fall_app) and not fall_ad:
            warnings.append("incomplete deadline block: fall accept/decline missing")
        if spring_app and not _NOT_ACCEPTING.search(spring_app) and not spring_ad:
            warnings.append("incomplete deadline block: spring accept/decline missing")

        programs.append(DiscoveredProgram(
            raw_listing_name=raw_name,
            normalized_program_name=normalized,
            degree_label=_none_if_blank(values.get("degree", "")),
            official_program_url=url,
            advisor_office=_none_if_blank(values.get("advisor", "")),
            advisor_url=links.get("advisor"),
            phone=_none_if_blank(values.get("phone", "")),
            spring_application_deadline=spring_app,
            spring_accept_decline_deadline=spring_ad,
            fall_application_deadline=fall_app,
            fall_accept_decline_deadline=fall_ad,
            term_availability=term_availability,
            stem_designated=_parse_stem(values.get("stem")),
            warnings=warnings,
        ))

    # Ambiguous names → flag every program that shares a normalized name.
    for prog in programs:
        if seen_names.get(prog.normalized_program_name, 0) > 1:
            prog.warnings.append("ambiguous program name (duplicate listing)")

    return DiscoveryManifest(
        discovery_source_url=source_url,
        discovery_source_hash=content_hash(raw),
        discovered_at=discovered_at,
        programs=programs,
        warnings=manifest_warnings,
    )
