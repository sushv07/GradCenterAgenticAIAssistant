"""
gradcenter_logging.py
Structured logging foundation for the CSULB Grad Center AI Assistant.

Public API
----------
    set_request_id(rid: str)        — Set the request_id for the current context.
                                      Call once per request in _submit_query().
    new_request_id() -> str         — Generate a UUID4 request_id string.
    emit(event, level="INFO", **f)  — Emit one NDJSON log event.

All events include envelope fields: ts, level, event, request_id, logger.

Output
------
    logs/gradcenter.log  — NDJSON, one JSON object per line, UTF-8, appending.
    stderr               — Same format; useful during development.

Constraints
-----------
    Standard library only.  No project imports.  No external dependencies.
    Thread-safe.  Safe across Streamlit hot-reloads (handlers are not added twice).
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Request context  (ContextVar — thread-safe, async-safe, OTel-compatible)
# ---------------------------------------------------------------------------

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "gradcenter_request_id", default=""
)


def set_request_id(rid: str) -> None:
    """Set the request_id for the current context.  Call once in _submit_query()."""
    _REQUEST_ID.set(rid)


def new_request_id() -> str:
    """Return a fresh UUID4 string suitable for use as a request_id."""
    return str(uuid.uuid4())


def get_request_id() -> str:
    """
    Return the request_id currently set for this context, or "" if none has
    been set. Pure read — never mints a new id. Added in Phase 4G so the
    backend's TraceContext can capture whatever id is already active without
    duplicating the generation logic that set_request_id()/new_request_id()
    already own.
    """
    return _REQUEST_ID.get()


# ---------------------------------------------------------------------------
# Session context (Phase 8B) — same ContextVar pattern as request_id above.
#
# Deliberately NOT added to emit()'s automatic envelope (unlike request_id):
# doing so would change every existing event's shape across the whole
# system, far beyond this phase's stated scope ("internal observability
# only" — retrieval events specifically). Callers that want session_id in
# a given event pass it explicitly as a field, e.g.
# emit("retrieval.started", session_id=get_session_id(), ...) — exactly
# what obs/retrieval_events.py does.
# ---------------------------------------------------------------------------

_SESSION_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "gradcenter_session_id", default=""
)


def set_session_id(sid: str) -> None:
    """Set the session_id for the current context. Call once per request in
    backend.entrypoint.handle_user_query()."""
    _SESSION_ID.set(sid)


def get_session_id() -> str:
    """Return the session_id currently set for this context, or "" if none
    has been set. Pure read — mirrors get_request_id()."""
    return _SESSION_ID.get()


# ---------------------------------------------------------------------------
# Logger configuration
# ---------------------------------------------------------------------------

_LOGGER_NAME = "gradcenter"
_LOG_DIR     = Path(__file__).parent / "logs"
_LOG_FILE    = _LOG_DIR / "gradcenter.log"

_logger = logging.getLogger(_LOGGER_NAME)


def _setup_logger() -> None:
    """Configure handlers once.  No-op on subsequent calls (hot-reload guard)."""
    if _logger.handlers:
        return

    _logger.setLevel(logging.INFO)
    _logger.propagate = False   # don't double-log through the root logger

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    _fmt = logging.Formatter("%(message)s")   # the message IS the JSON string

    _fh = logging.FileHandler(str(_LOG_FILE), encoding="utf-8")
    _fh.setFormatter(_fmt)
    _logger.addHandler(_fh)

    _ch = logging.StreamHandler()             # stderr — readable during development
    _ch.setFormatter(_fmt)
    _logger.addHandler(_ch)


_setup_logger()


# ---------------------------------------------------------------------------
# Core emit function
# ---------------------------------------------------------------------------

def emit(event: str, level: str = "INFO", **fields) -> None:
    """
    Emit one structured log event as a single JSON line (NDJSON).

    Envelope fields (ts, level, event, request_id, logger) are added
    automatically.  Pass event-specific fields as keyword arguments.

    Omit optional fields entirely when they do not apply — do not pass None
    or False for optional fields.

    Args:
        event:    Event name from the logging contract (e.g. "route.decision").
        level:    "INFO", "WARNING", or "ERROR".
        **fields: Event-specific fields per the approved logging contract.
    """
    record: dict = {
        "ts":         (datetime.now(timezone.utc)
                       .isoformat(timespec="milliseconds")
                       .replace("+00:00", "Z")),
        "level":      level,
        "event":      event,
        "request_id": _REQUEST_ID.get(),
        "logger":     _LOGGER_NAME,
    }
    record.update(fields)

    # default=str handles frozensets, Paths, or any other non-serialisable type
    # that might be passed by a call site (safety net — prefer passing lists).
    line = json.dumps(record, default=str)

    level_int = getattr(logging, level, logging.INFO)
    _logger.log(level_int, line)
