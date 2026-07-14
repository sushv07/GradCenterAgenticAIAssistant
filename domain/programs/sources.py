"""
domain/programs/sources.py
Source snapshot + provenance model (Phase P1).

content_hash is the AUTHORITATIVE identity of fetched source content — change
detection and freshness must rely on it, not on the optional human-readable
revision_label. Construction validates the structural essentials (id shape,
http(s) URL, non-empty hash, parseable timestamps). Whether an "official"
source sits on an approved CSULB host is a WARNING raised later by
domain.programs.validation, not a construction error.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, model_validator

from domain.programs.enums import ExtractionMethod, SourceType

_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class Source(BaseModel):
    """One fetched (or manually recorded) source backing one or more facts."""

    source_id: str
    source_url: str
    source_type: SourceType
    official: bool
    fetched_at: datetime
    last_verified: Optional[date] = None
    content_hash: str
    extraction_method: ExtractionMethod
    revision_label: Optional[str] = None  # optional human label; NOT the identity

    @model_validator(mode="after")
    def _check(self) -> "Source":
        if not _SOURCE_ID_RE.match(self.source_id or ""):
            raise ValueError(
                "source_id must be a non-empty identifier of [A-Za-z0-9._-]"
            )
        if not (
            self.source_url.startswith("http://")
            or self.source_url.startswith("https://")
        ):
            raise ValueError("source_url must be an http:// or https:// URL")
        if not self.content_hash or self.content_hash.strip() == "":
            raise ValueError("content_hash must be non-empty (authoritative identity)")
        if self.revision_label is not None and self.revision_label.strip() == "":
            raise ValueError("revision_label must not be an empty string; use null")
        return self
