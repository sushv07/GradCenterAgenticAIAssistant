"""
frontend/components/followups.py
Suggested follow-up question buttons.
"""
from __future__ import annotations

import streamlit as st


def render_followups_placeholder() -> None:
    """Render placeholder buttons for suggested follow-up questions."""
    st.markdown("**Suggested follow-ups**")
    st.button("What are the application deadlines?", disabled=True)
    st.button("What GPA do I need?", disabled=True)
    st.button("Who is my advisor?", disabled=True)
