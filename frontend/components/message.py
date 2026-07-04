"""
frontend/components/message.py
Individual chat message rendering.
"""
from __future__ import annotations

import streamlit as st


def render_message_placeholder() -> None:
    """Render a placeholder representing a single chat message bubble."""
    with st.chat_message("assistant"):
        st.markdown("_Assistant response will appear here._")
