"""
frontend/components/sources.py
Retrieval source citations panel.
"""
from __future__ import annotations

import streamlit as st

from frontend.utils.formatting import format_source_label


def render_sources() -> None:
    """Render retrieved source citations from the last response."""
    sources = st.session_state.get("latest_sources", [])
    with st.expander("Sources", expanded=bool(sources)):
        if not sources:
            st.caption("No sources for this response.")
            return
        for src in sources:
            label = format_source_label(src)
            url   = src.get("url", "")
            if url:
                st.markdown(f"- [{label}]({url})")
            else:
                st.caption(f"- {label}")
