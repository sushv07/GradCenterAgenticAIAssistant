"""
frontend/app.py
Streamlit entry point for the CSULB Grad Center AI Assistant frontend.

Run:
    streamlit run frontend/app.py

This file owns only layout wiring:
    - page config
    - CSS injection
    - session state initialization
    - component orchestration

No HTTP calls, no retrieval logic, no backend imports live here.
All of those belong in frontend/services/ and frontend/components/.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from frontend.X import Y` works
# regardless of how Streamlit sets up its own path.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from frontend.state.session import initialize_session_state
from frontend.components.sidebar import render_sidebar
from frontend.components.status import render_status_banner
from frontend.components.chat import render_chat_placeholder
from frontend.components.message import render_message_placeholder
from frontend.components.sources import render_sources_placeholder
from frontend.components.followups import render_followups_placeholder


# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="CSULB Grad Center Assistant",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _load_css() -> None:
    css_path = Path(__file__).parent / "styles" / "theme.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


_load_css()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

initialize_session_state()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

render_sidebar()

st.title("CSULB Graduate Center AI Assistant")
st.caption("Ask me about admissions, programs, deadlines, and more.")

render_status_banner()

st.divider()

# Main area — two columns: chat (wide) | side panel (narrow)
col_chat, col_panel = st.columns([3, 1])

with col_chat:
    render_chat_placeholder()
    render_message_placeholder()

with col_panel:
    render_sources_placeholder()
    st.divider()
    render_followups_placeholder()
