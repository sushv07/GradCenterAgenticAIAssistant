"""
frontend/state/session.py
Session state initialization for the Streamlit frontend.

Owns only the shape of session state — no HTTP, no backend logic.
All fields are placeholders; full chat history and backend integration
are implemented in later phases.
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
