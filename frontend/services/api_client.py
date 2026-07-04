"""
frontend/services/api_client.py
HTTP client skeleton for the CSULB Grad Center backend API.

Phase 10H.1: skeleton only — query() raises NotImplementedError.
Real requests are wired in Phase 10H.2.

The frontend communicates exclusively through this class.
No other module may make HTTP calls.
"""
from __future__ import annotations

import os

BACKEND_API_URL: str = os.environ.get(
    "BACKEND_API_URL",
    "https://gradcenter-ai.onrender.com",
)


class ApiClient:
    """
    Thin client for the Grad Center FastAPI backend.

    Attributes:
        base_url: Root URL of the deployed backend (no trailing slash).
    """

    def __init__(self, base_url: str = BACKEND_API_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def query(self, query: str, session_id: str) -> dict:
        """
        POST /query to the backend.

        Args:
            query:      The user's question text.
            session_id: The Streamlit session identifier (for multi-turn context).

        Returns:
            Parsed JSON response dict from the backend.

        Raises:
            NotImplementedError: Phase 10H.1 — implementation deferred to
                                 Phase 10H.2.
        """
        raise NotImplementedError(
            "ApiClient.query() is not yet implemented. "
            "Real HTTP calls are wired in Phase 10H.2."
        )

    def health(self) -> dict:
        """
        GET /health — liveness probe.

        Returns:
            Parsed JSON dict, e.g. {"status": "ok", "service": "..."}.

        Raises:
            NotImplementedError: Phase 10H.1 — implementation deferred.
        """
        raise NotImplementedError(
            "ApiClient.health() is not yet implemented. "
            "Real HTTP calls are wired in Phase 10H.2."
        )
