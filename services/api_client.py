"""
services/api_client.py
HTTP client for the deployed CSULB Grad Center FastAPI backend.

Single point of network contact for the Streamlit UI.
No other module in app.py needs to import `requests`.
"""
from __future__ import annotations

import os

import requests

BACKEND_API_URL: str = os.environ.get(
    "BACKEND_API_URL",
    "https://gradcenter-ai.onrender.com",
)

_HEALTH_TIMEOUT: int = 10
_QUERY_TIMEOUT:  int = 90


class BackendError(Exception):
    """
    Raised when the backend is unreachable, times out, returns a non-2xx
    status, or returns malformed JSON.

    Wraps the underlying requests exception so callers never need to
    import requests.
    """
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.message     = message
        self.status_code = status_code


class ApiClient:
    """
    Thin HTTP wrapper around the Grad Center FastAPI backend.

    Raises BackendError for every failure.
    """

    def __init__(self, base_url: str = BACKEND_API_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        """GET /health — liveness probe."""
        return self._get("/health", timeout=_HEALTH_TIMEOUT)

    def query(self, query: str, session_id: str) -> dict:
        """POST /query — submit a user question and return the route-specific response dict."""
        return self._post(
            "/query",
            json={"query": query, "session_id": session_id},
            timeout=_QUERY_TIMEOUT,
        )

    # ------------------------------------------------------------------

    def _get(self, path: str, timeout: int) -> dict:
        try:
            r = requests.get(f"{self.base_url}{path}", timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError:
            raise BackendError("Cannot connect to the backend.")
        except requests.Timeout:
            raise BackendError(f"Request timed out after {timeout}s.")
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
            raise BackendError("Cannot connect to the backend.")
        except requests.Timeout:
            raise BackendError(
                "Request timed out. The backend may be cold-starting — "
                "please wait a moment and try again."
            )
        except requests.HTTPError as exc:
            raise BackendError(
                f"Backend returned {exc.response.status_code}.",
                exc.response.status_code,
            )
        except ValueError:
            raise BackendError("Backend returned invalid JSON.")
