"""
frontend/components/sidebar.py
Sidebar: branding, session controls, and backend status indicator.
"""
from __future__ import annotations

import streamlit as st


def render_sidebar() -> None:
    """Render the application sidebar."""
    with st.sidebar:
        st.title("CSULB Grad Center")
        st.caption("AI Assistant")
        st.divider()
        st.markdown("**Session**")
        session_id = st.session_state.get("session_id", "—")
        st.caption(f"ID: `{session_id[:8]}…`")
        st.divider()
        st.markdown("**Backend**")
        status = st.session_state.get("backend_status", "unknown")
        _status_chip(status)


def _status_chip(status: str) -> None:
    colors = {
        "ok":          "🟢",
        "degraded":    "🟡",
        "unreachable": "🔴",
        "unknown":     "⚪",
    }
    label = colors.get(status, "⚪")
    st.caption(f"{label} {status}")
