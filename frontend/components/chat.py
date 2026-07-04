"""
frontend/components/chat.py
Main chat column: message history replay, input, and response rendering.
"""
from __future__ import annotations

import streamlit as st

from frontend.services.api_client import ApiClient, BackendError
from frontend.services.response_mapper import map_response
from frontend.state.session import (
    append_user_message,
    append_assistant_message,
    get_messages,
    get_session_id,
)


def render_chat(client: ApiClient) -> None:
    """
    Render the full chat interface.

    Order:
      1. Replay message history from session state.
      2. Check pending_query (set by follow-up buttons); otherwise read st.chat_input.
      3. Show the user's message immediately.
      4. Call the backend with a spinner.
      5. Display the assistant response or a graceful error.
      6. Update latest_sources and latest_followups for the panel components.
    """
    for msg in get_messages():
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Follow-up buttons set pending_query + rerun; chat_input is ignored that rerun.
    prompt: str | None = None

    if st.session_state.get("pending_query"):
        prompt = st.session_state.pending_query
        st.session_state.pending_query = None

    user_input = st.chat_input("Ask about programs, deadlines, admissions…")
    if user_input and not prompt:
        prompt = user_input

    if not prompt:
        return

    with st.chat_message("user"):
        st.markdown(prompt)
    append_user_message(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                raw    = client.query(prompt, get_session_id())
                mapped = map_response(raw)
            except BackendError as exc:
                st.error(f"Could not reach the backend: {exc.message}")
                append_assistant_message(f"_(Error: {exc.message})_")
                return

        answer = mapped["answer"]
        st.markdown(answer)

    append_assistant_message(answer)

    st.session_state.latest_sources   = mapped["sources"]
    st.session_state.latest_followups = mapped["followups"]
