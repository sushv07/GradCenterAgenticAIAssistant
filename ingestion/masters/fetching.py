"""
ingestion/masters/fetching.py
Source acquisition behind an injectable Fetcher interface.

The pipeline depends only on the Fetcher protocol, so tests run fully offline
with StaticFetcher (fixture bytes) and production uses HttpFetcher (stdlib
urllib, restricted to official CSULB hosts per the source policy). No third-party
HTTP dependency is imported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol
from urllib.parse import urlparse

_OFFICIAL_HOST_SUFFIX = "csulb.edu"
_DEFAULT_USER_AGENT = "csulb-grad-center-ingestion/0.1 (+https://www.csulb.edu)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    content: bytes
    fetched_at: datetime


class FetchError(Exception):
    """Raised when a source cannot be acquired."""


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


def is_official_csulb_host(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    return host == _OFFICIAL_HOST_SUFFIX or host.endswith("." + _OFFICIAL_HOST_SUFFIX)


class StaticFetcher:
    """Offline fetcher backed by an in-memory {url: bytes} map (tests only)."""

    def __init__(self, pages: dict[str, bytes], *, clock: Optional[Callable[[], datetime]] = None):
        self._pages = dict(pages)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self, url: str) -> FetchResult:
        if url not in self._pages:
            raise FetchError(f"no static page registered for {url}")
        return FetchResult(url=url, content=self._pages[url], fetched_at=self._clock())


class HttpFetcher:
    """Production fetcher (stdlib urllib), restricted to official CSULB hosts.

    Not exercised by the offline test suite. The host restriction enforces the
    'only traverse official CSULB pages' policy at the network boundary.
    """

    def __init__(self, *, timeout: float = 20.0, user_agent: str = _DEFAULT_USER_AGENT,
                 allow_host_check: bool = True):
        self._timeout = timeout
        self._user_agent = user_agent
        self._allow_host_check = allow_host_check

    def fetch(self, url: str) -> FetchResult:
        if self._allow_host_check and not is_official_csulb_host(url):
            raise FetchError(f"refusing non-official host: {url}")
        # Imported lazily so importing this module never requires network stack.
        from urllib.request import Request, urlopen

        req = Request(url, headers={"User-Agent": self._user_agent})
        try:
            with urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (host-restricted)
                content = resp.read()
        except Exception as exc:  # pragma: no cover - network path not tested offline
            raise FetchError(f"fetch failed for {url}: {exc}") from exc
        return FetchResult(url=url, content=content, fetched_at=datetime.now(timezone.utc))
