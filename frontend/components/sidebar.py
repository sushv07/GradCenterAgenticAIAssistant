"""
frontend/components/sidebar.py
Sidebar: branding, session controls, and backend status indicator.
"""
from __future__ import annotations

import streamlit as st

from frontend.services.api_client import ApiClient, BackendError, BACKEND_API_URL
from frontend.state.session import clear_chat, update_backend_status


def render_sidebar(client: ApiClient) -> None:
    """Render the application sidebar."""
    with st.sidebar:
        st.title("CSULB Grad Center")
        st.caption("AI Assistant")
        st.divider()

        st.markdown("**Backend**")
        st.caption(f"URL: `{BACKEND_API_URL}`")

        # Only probe on first render (status "unknown"); cached afterwards.
        if st.session_state.get("backend_status", "unknown") == "unknown":
            _check_health(client)

        _status_chip(st.session_state.get("backend_status", "unknown"))

        if st.button("Refresh Status", key="refresh_status"):
            update_backend_status("unknown")
            _check_health(client)
            st.rerun()

        st.divider()

        st.markdown("**Session**")
        session_id = st.session_state.get("session_id", "—")
        st.caption(f"ID: `{session_id[:8]}…`")

        if st.button("Clear Chat", key="clear_chat_btn"):
            clear_chat()
            st.rerun()


def _check_health(client: ApiClient) -> None:
    try:
        data   = client.health()
        status = data.get("status", "unknown")
        update_backend_status("ok" if status == "ok" else "degraded")
    except BackendError:
        update_backend_status("unreachable")


def _status_chip(status: str) -> None:
    colors = {
        "ok":          "🟢",
        "degraded":    "🟡",
        "unreachable": "🔴",
        "unknown":     "⚪",
    }
    label = colors.get(status, "⚪")
    st.caption(f"{label} {status}")
