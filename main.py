import streamlit as st
from dotenv import load_dotenv
from src.splunk_client import SplunkClient  # Smoothly imports thanks to __init__.py

# Ingest your keys from the hidden .env file
load_dotenv()

st.set_page_config(page_title="Splunk AI Assistant", page_icon="🤖")
st.title("🤖 Splunk Agentic Ops Console")

# Prevent the script from re-initializing the client connection on every click
if "splunk" not in st.session_state:
    st.session_state.splunk = SplunkClient()

client = st.session_state.splunk

st.sidebar.subheader("Infrastructure Logs")
if st.sidebar.button("Test Live Splunk Connection"):
    with st.spinner("Reaching out to prd-p-dzloy.splunkcloud.com..."):
        # Let's fire the search wrapper function Claude wrote
        raw_logs = client.get_alerts(limit=3)
        st.write("### Connection Status Response:")
        st.code(raw_logs, language="json")