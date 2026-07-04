"""
frontend/components/followups.py
Suggested follow-up question buttons.
"""
from __future__ import annotations

import streamlit as st


def render_followups() -> None:
    """
    Render clickable follow-up suggestion buttons.

    Clicking a button sets pending_query in session state and triggers a
    rerun; render_chat picks up pending_query as the next user prompt.
    """
    followups = st.session_state.get("latest_followups", [])
    if not followups:
        return

    st.markdown("**Suggested follow-ups**")
    for i, text in enumerate(followups[:4]):
        if st.button(text, key=f"followup_{i}_{text[:20]}"):
            st.session_state.pending_query = text
            st.rerun()
