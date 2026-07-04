"""
frontend/components/status.py
Top-of-page backend status banner.
"""
from __future__ import annotations

import streamlit as st


def render_status_banner() -> None:
    """
    Render a banner when the backend is not fully ready.

    Shows nothing when status is "ok" so the happy path is uncluttered.
    """
    status = st.session_state.get("backend_status", "unknown")
    if status == "ok":
        return
    messages = {
        "degraded":    "Backend is degraded — some features may be unavailable.",
        "unreachable": "Cannot reach the backend. Check your connection.",
        "unknown":     "Connecting to backend…",
    }
    text = messages.get(status, f"Backend status: {status}")
    st.warning(text)
