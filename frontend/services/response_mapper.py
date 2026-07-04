"""
frontend/services/response_mapper.py
Translate raw backend JSON into a flat, UI-friendly dict.

The backend returns richly structured responses (route-specific shapes,
nested sources, follow-up arrays). This module normalizes them into a
single shape the UI components can consume without needing to know about
routing or backend schema details.

Phase 10H.1: placeholder only — map_response() returns the raw dict unchanged.
Full mapping is implemented in Phase 10H.2 alongside real API calls.
"""
from __future__ import annotations


def map_response(raw: dict) -> dict:
    """
    Normalize a backend /query response into a UI-ready dict.

    Phase 10H.1 returns the raw dict unchanged. Phase 10H.2 will
    extract and standardize: answer text, sources list, follow-up
    questions, route name, and any structured checklist/steps.

    Args:
        raw: Parsed JSON from ApiClient.query().

    Returns:
        A dict with at minimum the key ``answer`` (str).
    """
    return raw
