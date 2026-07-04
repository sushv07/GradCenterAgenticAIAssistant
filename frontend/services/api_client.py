"""
frontend/services/api_client.py
HTTP client for the CSULB Grad Center FastAPI backend.

Single point of network contact for the entire frontend.
No other module may make HTTP calls.
"""
from __future__ import annotations

import os

import requests

BACKEND_API_URL: str = os.environ.get(
    "BACKEND_API_URL",
    "https://gradcenter-ai.onrender.com",
)

# Health probe is lightweight; query may trigger a store rebuild (~30-60 s).
_HEALTH_TIMEOUT: int = 10
_QUERY_TIMEOUT:  int = 90


class BackendError(Exception):
    """
    Raised when the backend is unreachable, times out, returns a non-2xx
    status, or returns malformed JSON.

    Always catches the underlying requests exception so callers never need to
    import requests themselves.
    """
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.message     = message
        self.status_code = status_code


class ApiClient:
    """
    Thin HTTP wrapper around the Grad Center FastAPI backend.

    Raises BackendError for every failure — callers receive one exception type.
    """

    def __init__(self, base_url: str = BACKEND_API_URL) -> None:
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """
        GET /health — liveness probe.

        Returns:
            Parsed JSON, e.g. {"status": "ok", "service": "...", "timestamp": "..."}.

        Raises:
            BackendError: on any network or HTTP error.
        """
        return self._get("/health", timeout=_HEALTH_TIMEOUT)

    def query(self, query: str, session_id: str) -> dict:
        """
        POST /query — submit a user question.

        Args:
            query:      The user's question text (may be empty string).
            session_id: Frontend session UUID for multi-turn context.

        Returns:
            Parsed backend JSON (route-specific shape — see contracts/response_types.py).

        Raises:
            BackendError: on any network or HTTP error.
        """
        return self._post(
            "/query",
            json={"query": query, "session_id": session_id},
            timeout=_QUERY_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, timeout: int) -> dict:
        try:
            r = requests.get(f"{self.base_url}{path}", timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError:
            raise BackendError("Cannot connect to backend.")
        except requests.Timeout:
            raise BackendError(f"Request timed out ({timeout}s).")
        except requests.HTTPError as exc:
            raise BackendError(
                f"Backend returned {exc.response.status_code}.",
                exc.response.status_code,
            )
        except ValueError:
            raise BackendError("Backend returned invalid JSON.")

    def _post(self, path: str, json: dict, timeout: int) -> dict:
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                json=json,
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError:
            raise BackendError("Cannot connect to backend.")
        except requests.Timeout:
            raise BackendError(
                "Request timed out. The backend may be building the knowledge base "
                "for the first time — please try again in a moment."
            )
        except requests.HTTPError as exc:
            raise BackendError(
                f"Backend returned {exc.response.status_code}.",
                exc.response.status_code,
            )
        except ValueError:
            raise BackendError("Backend returned invalid JSON.")
