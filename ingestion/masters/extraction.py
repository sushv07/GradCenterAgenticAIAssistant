"""
ingestion/masters/extraction.py
Stage 2a — pull raw candidate facts out of an official program page.

Extraction is deliberately conservative: it captures raw text snippets (overview,
GPA statement, test-requirement statement, prerequisites) tagged with the
snapshot they came from. It does NOT interpret them — that is normalization's
job. Anything not found stays absent so normalization can mark it source_missing.
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

_GPA_KW = re.compile(r"\bgpa\b", re.IGNORECASE)
_GRE_KW = re.compile(r"\bgre\b", re.IGNORECASE)
# Split on sentence-ending periods but NOT on decimals like "3.0".
_SENTENCE_SPLIT = re.compile(r"(?<!\d)[.](?!\d)\s+")


def _keyword_sentence(text: str, pattern: re.Pattern) -> Optional[str]:
    """Return the first sentence containing the keyword, splitting on sentence
    periods while preserving decimals (so '3.0' stays intact)."""
    for sentence in _SENTENCE_SPLIT.split(text):
        if pattern.search(sentence):
            return sentence.strip().rstrip(".").strip() or None
    return None


class ExtractedFacts(BaseModel):
    source_id: str
    page_fetched: bool = True
    overview_text: Optional[str] = None
    gpa_statement: Optional[str] = None
    gre_statement: Optional[str] = None
    prerequisites: list[str] = Field(default_factory=list)
    concentrations: list[str] = Field(default_factory=list)
    supplemental_materials: list[str] = Field(default_factory=list)
    # Provenance-sensitive identity fields. Left None in P2 (no heuristic
    # extractor yet); when a program/catalog source provides them, normalization
    # turns a non-None value into a source-backed Fact.
    college: Optional[str] = None
    department: Optional[str] = None


def _text(soup: BeautifulSoup) -> str:
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _section_list(soup: BeautifulSoup, heading_keywords: tuple[str, ...]) -> list[str]:
    """Return <li> items under a heading whose text matches any keyword."""
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        htext = heading.get_text(" ", strip=True).lower()
        if any(k in htext for k in heading_keywords):
            ul = heading.find_next(["ul", "ol"])
            if ul:
                return [re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
                        for li in ul.find_all("li") if li.get_text(strip=True)]
    return []


def extract_program_page(html: bytes | str, *, source_id: str) -> ExtractedFacts:
    raw = html if isinstance(html, bytes) else html.encode("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    full = _text(soup)

    overview = None
    p = soup.find("p")
    if p and p.get_text(strip=True):
        overview = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()

    return ExtractedFacts(
        source_id=source_id,
        page_fetched=True,
        overview_text=overview,
        gpa_statement=_keyword_sentence(full, _GPA_KW),
        gre_statement=_keyword_sentence(full, _GRE_KW),
        prerequisites=_section_list(soup, ("prerequisite", "prerequisites")),
        concentrations=_section_list(soup, ("concentration", "concentrations", "specialization")),
        supplemental_materials=_section_list(soup, ("supplemental", "required materials")),
    )
