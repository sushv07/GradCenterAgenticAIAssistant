"""
ingestion/masters/extraction.py
Stage 2a — pull raw candidate facts out of an official program page.

Calibrated (Phase P3) against real CSULB pages, which wrap the program content
in heavy shared chrome (header/nav/footer). Extraction therefore:
  1. isolates the MAIN CONTENT region (<main> / [role=main] / #main-content /
     article), falling back to a body stripped of nav/header/footer;
  2. prefers the paragraph after a "Program Overview"/"Overview" heading for the
     summary, rejecting boilerplate (campus address / phone banners);
  3. searches GPA/GRE sentences within main content only, with a length guard so
     an un-punctuated navigation blob can never be captured as a "sentence".

Extraction stays conservative: anything not confidently found is left absent so
normalization marks it source_missing (page consulted) or unknown (not consulted)
— it never fabricates a value.
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

_GPA_KW = re.compile(r"\bgpa\b", re.IGNORECASE)
_GRE_KW = re.compile(r"\bgre\b", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<!\d)[.](?!\d)\s+")
_MAX_SENTENCE = 320  # a real requirement sentence; longer = nav/boilerplate blob
_BOILERPLATE = re.compile(
    r"\d{3,}\s+[A-Z].*(BOULEVARD|STREET|AVENUE|DRIVE|BLVD|LONG BEACH|CALIFORNIA \d{5})",
    re.IGNORECASE)
# Non-program boilerplate observed on real pages: accessibility/carousel widgets,
# navigation, cookie banners, and repeated generic college-marketing banners
# (e.g. CLA department landing pages that carry no program-specific overview).
_BOILERPLATE_MARKERS = (
    "this is a carousel", "use next and previous", "go to slide",
    "skip to main content", "javascript is required", "javascript is disabled",
    "cookie", "largest college on campus", "educational focal point",
)
# Headings that reliably anchor a genuine program overview.
_OVERVIEW_HEADING = re.compile(
    r"program overview|degree overview|about the program|about the master|"
    r"graduate program overview|^\s*overview\s*$|^\s*about\s*$",
    re.IGNORECASE)
_MAIN_SELECTORS = ("main", "[role=main]", "#main-content", "#content", "article")


class ExtractedFacts(BaseModel):
    source_id: str
    page_fetched: bool = True
    overview_text: Optional[str] = None
    gpa_statement: Optional[str] = None
    gre_statement: Optional[str] = None
    prerequisites: list[str] = Field(default_factory=list)
    concentrations: list[str] = Field(default_factory=list)
    supplemental_materials: list[str] = Field(default_factory=list)
    college: Optional[str] = None
    department: Optional[str] = None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def _main_content(soup: BeautifulSoup):
    """The main content region, or a body stripped of shared chrome."""
    for sel in _MAIN_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 200:
            return el
    body = soup.body or soup
    for tag in body.find_all(["nav", "header", "footer", "script", "style", "aside", "form"]):
        tag.decompose()
    return body


def _looks_boilerplate(text: str) -> bool:
    low = (text or "").lower()
    if _BOILERPLATE.search(text or ""):
        return True
    return any(marker in low for marker in _BOILERPLATE_MARKERS)


def _overview(main) -> Optional[str]:
    """Heading-anchored first, then a conservative positional fallback. Any
    boilerplate/widget/marketing/address text is rejected. When nothing
    trustworthy is found, return None so normalization records source_missing —
    an overview is never fabricated from questionable text."""
    for h in main.find_all(re.compile(r"^h[1-6]$")):
        if _OVERVIEW_HEADING.search(h.get_text(" ", strip=True)):
            p = h.find_next("p")
            if p:
                t = _clean(p.get_text(" ", strip=True))
                if len(t) >= 40 and not _looks_boilerplate(t):
                    return t
    for p in main.find_all("p"):
        t = _clean(p.get_text(" ", strip=True))
        if len(t) >= 80 and not _looks_boilerplate(t):
            return t
    return None


def _keyword_sentence(text: str, pattern: re.Pattern) -> Optional[str]:
    """First bounded sentence containing the keyword (decimals preserved)."""
    for sentence in _SENTENCE_SPLIT.split(text):
        s = sentence.strip()
        if len(s) > _MAX_SENTENCE:
            continue
        if pattern.search(s):
            return s.rstrip(".").strip() or None
    return None


def _section_list(main, heading_keywords: tuple[str, ...]) -> list[str]:
    for heading in main.find_all(re.compile(r"^h[1-6]$")):
        htext = heading.get_text(" ", strip=True).lower()
        if any(k in htext for k in heading_keywords):
            ul = heading.find_next(["ul", "ol"])
            if ul:
                return [_clean(li.get_text(" ", strip=True))
                        for li in ul.find_all("li") if li.get_text(strip=True)]
    return []


def _page_title(soup: BeautifulSoup, fallback: str = "") -> str:
    """Primary page title from <title> (drops the trailing ' | CSULB' suffix)."""
    tag = soup.find("title")
    if tag:
        raw = tag.get_text(strip=True)
        if " | " in raw:
            raw = raw.split(" | ")[0].strip()
        if raw and len(raw) > 3:
            return raw
    return fallback


def extract_main_content_text(
    html: bytes | str, *, fallback_title: str = "",
) -> tuple[str, str]:
    """Full-text extractor for retrieval: returns (title, cleaned_main_text).

    Reuses the SAME calibrated main-content isolation as extract_program_page
    (nav/header/footer/script/aside removed) so there is one extraction path.
    Lines are whitespace-normalized, boilerplate/widget lines dropped, and
    consecutive duplicate lines collapsed. Reading order is preserved with
    newline separators (the production chunker splits on blank line / newline).
    Never fabricates content — an empty main region yields an empty string.
    """
    raw = html if isinstance(html, bytes) else html.encode("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    title = _page_title(soup, fallback_title)
    main = _main_content(soup)

    lines: list[str] = []
    for line in main.get_text("\n", strip=True).split("\n"):
        s = _clean(line)
        if not s or _looks_boilerplate(s):
            continue
        if lines and lines[-1] == s:      # drop consecutive duplicate lines
            continue
        lines.append(s)
    return title, "\n".join(lines)


def extract_program_page(html: bytes | str, *, source_id: str) -> ExtractedFacts:
    raw = html if isinstance(html, bytes) else html.encode("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    main = _main_content(soup)
    main_text = _clean(main.get_text(" ", strip=True))

    return ExtractedFacts(
        source_id=source_id,
        page_fetched=True,
        overview_text=_overview(main),
        gpa_statement=_keyword_sentence(main_text, _GPA_KW),
        gre_statement=_keyword_sentence(main_text, _GRE_KW),
        prerequisites=_section_list(main, ("prerequisite", "prerequisites")),
        concentrations=_section_list(main, ("concentration", "concentrations", "specialization")),
        supplemental_materials=_section_list(main, ("supplemental", "required materials")),
    )
