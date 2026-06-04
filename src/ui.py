"""
src/ui.py
---------
All Streamlit UI components and the chat interface.
Calls agent.py to process user messages.
"""

import os
import streamlit as st
from src.agent import run_agent


def render_sidebar() -> None:
    """Render sidebar with config options and status."""
    with st.sidebar:
        if os.path.exists("assets/architecture.png"):
            st.image("assets/architecture.png", use_column_width=True)
        else:
            st.info("Drop your architecture diagram in assets/")
        st.markdown("---")
        st.markdown("### ⚙️ Settings")
        st.selectbox("Model", ["claude-3-5-sonnet-20241022", "gpt-4o"], key="selected_model")
        st.slider("Max Tokens", 256, 4096, 1024, key="max_tokens")
        st.markdown("---")
        st.caption("Splunk Agentic Ops · Hackathon 2025")


def render_chat() -> None:
    """Render the main chat interface."""
    st.title("⚡ Splunk Agentic Ops")
    st.caption("AI-powered operations — ask anything about your Splunk environment.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about your Splunk alerts, searches, or incidents…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                response = run_agent(
                    user_message=prompt,
                    history=st.session_state.messages[:-1],
                    model=st.session_state.get("selected_model", "claude-3-5-sonnet-20241022"),
                    max_tokens=st.session_state.get("max_tokens", 1024),
                )
            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})


def render_ui() -> None:
    """Top-level render function called by main.py."""
    render_sidebar()
    render_chat()
