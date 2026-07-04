"""
frontend/components/sources.py
Retrieval source citations panel.
"""
from __future__ import annotations

import streamlit as st


def render_sources_placeholder() -> None:
    """Render a placeholder for the retrieved source citations."""
    with st.expander("Sources", expanded=False):
        st.caption("Retrieved sources will be listed here.")
