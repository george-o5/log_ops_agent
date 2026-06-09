# ⚡ log Agentic Ops

> AI-powered IT operations assistant that connects Claude to Splunk Cloud via the Model Context Protocol (MCP).



---

## 🏗️ Architecture

![Architecture Diagram](assets/architecture.png)

| Layer | File | Responsibility |
|-------|------|----------------|
| UI | `src/ui.py` | Streamlit chat interface |
| Agent | `src/agent.py` | Claude AI + MCP tool loop |
| Backend | `src/splunk_client.py` | Splunk Cloud REST API calls |
| Entry | `main.py` | App bootstrap |

---

## 🚀 Quickstart

### Prerequisites
- Python 3.11+
- A Splunk Cloud instance with API access
- An Anthropic API key

### Install

```bash
pip install streamlit anthropic requests python-dotenv
```

### Configure

Fill in your credentials in `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
SPLUNK_HOST=https://your-instance.splunkcloud.com:8089
SPLUNK_TOKEN=your-splunk-bearer-token-here
```

### Run

```bash
streamlit run main.py
```

---

## 🛠️ Features

- 💬 **Conversational SPL** — Ask questions in plain English; Claude writes and runs SPL searches
- 🚨 **Alert Monitoring** — Pull fired Splunk alerts on demand
- 🔄 **Agentic Loop** — Multi-step reasoning with real tool use via Anthropic's tool API
- 🔒 **Secure** — Credentials stay in `.env`, never in code

---

## 📁 Project Structure

```
splunk-agentic-ops/
├── assets/               # Architecture diagram
├── config/               # Optional config files
├── src/
│   ├── __init__.py
│   ├── ui.py             # Streamlit frontend
│   ├── agent.py          # AI brain (Claude + tools)
│   └── splunk_client.py  # Splunk REST API wrapper
├── main.py               # Entry point
├── .env                  # Secrets (not committed)
└── README.md
```

---


