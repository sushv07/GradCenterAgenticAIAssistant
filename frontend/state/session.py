"""
frontend/state/session.py
Session state helpers for the Streamlit frontend.

Owns only the shape of session state — no HTTP, no backend logic.
"""
from __future__ import annotations

import uuid
import streamlit as st


def initialize_session_state() -> None:
    """
    Ensure all required session state keys exist with safe defaults.

    Call once at the top of app.py before rendering any component.
    Uses setdefault semantics: existing values are never overwritten,
    so re-runs (Streamlit's normal execution model) preserve state.
    """
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())

    if "messages" not in st.session_state:
        # Each entry: {"role": "user"|"assistant", "content": str}
        st.session_state.messages = []

    if "backend_status" not in st.session_state:
        # Possible values: "unknown" | "ok" | "degraded" | "unreachable"
        st.session_state.backend_status = "unknown"

    if "latest_sources" not in st.session_state:
        st.session_state.latest_sources = []

    if "latest_followups" not in st.session_state:
        st.session_state.latest_followups = []

    if "pending_query" not in st.session_state:
        st.session_state.pending_query = None


# ---------------------------------------------------------------------------
# Helpers used by components
# ---------------------------------------------------------------------------

def append_user_message(content: str) -> None:
    st.session_state.messages.append({"role": "user", "content": content})


def append_assistant_message(content: str) -> None:
    st.session_state.messages.append({"role": "assistant", "content": content})


def clear_chat() -> None:
    st.session_state.messages       = []
    st.session_state.latest_sources  = []
    st.session_state.latest_followups = []
    st.session_state.pending_query   = None


def get_messages() -> list:
    return st.session_state.get("messages", [])


def get_session_id() -> str:
    return st.session_state.get("session_id", "")


def update_backend_status(status: str) -> None:
    st.session_state.backend_status = status
