# 🔍 LogOps Agentic — Splunk Alert Health Portal


> An autonomous AI agent that audits your Splunk alert rules for structural rot —
> finding the rules that are silent, blind, and broken before your next real incident does.

---

## 🚀 Project Overview

In enterprise SOC and DevOps environments, security teams accumulate hundreds of Splunk alert rules over months and years. As infrastructure evolves — indexes get renamed, sourcetypes change, data inputs break — alert rules silently go blind. They keep appearing on dashboards as "active" while actually monitoring empty or non-existent index partitions. Nobody notices until an incident goes undetected.

**LogOps Agentic** solves this with a fully autonomous auditing pipeline. It connects to your live Splunk Cloud environment via the Splunk MCP Server, systematically evaluates every saved alert rule against real index health data, and uses a fine-tuned LLM prompt to produce plain-English infrastructure diagnoses — not generic cybersecurity noise.

### What It Detects

| Status | Meaning | Real-World Cause |
|--------|---------|-----------------|
| 🔴 **RED** | Alert is completely blind | Target index does not exist or has zero data |
| 🟡 **AMBER** | Alert is passive — alive but silent | Index has data but query returns zero matches |
| 🟢 **GREEN** | Alert is healthy and active | Query is matching events and firing on schedule |

### Why It Stands Out

This is not a chatbot. It is not a generic log viewer. It is a **deterministic health classification engine with an AI interpretation layer** — a pattern used in real production observability tooling. The AI's role is deliberately narrow: translate cold pipeline metrics into human-readable risk language, without inventing fictional threat scenarios.

---

## 🏗️ Pipeline Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        YOUR LAPTOP / CI RUNNER                       │
│                                                                       │
│  1. log_generator.py                                                  │
│     Generates 150 realistic security + database log events           │
│     Pushes to Splunk Cloud via HEC (Port 8088)                       │
│              │                                                        │
│              ▼                                                        │
│  ┌─────────────────────┐                                             │
│  │   SPLUNK CLOUD       │  ← Your live indexes + saved alert rules   │
│  │   index=main         │                                             │
│  └─────────┬───────────┘                                             │
│             │                                                         │
│  2. splunk_agent.py  ◄── Splunk MCP Server (get_knowledge_objects)   │
│     Fetches all saved alerts                                          │
│     Runs each alert's SPL query  ◄── MCP (run_splunk_query)          │
│     Checks target index health   ◄── MCP (run_splunk_query)          │
│     Classifies: RED / AMBER / GREEN                                   │
│              │                                                        │
│              ▼  List of AlertHealthResult dicts                       │
│                                                                       │
│  3. ai_explainer.py                                                   │
│     Sends each result to Groq/Gemini free LLM API                    │
│     Enforces strict system prompt: infrastructure auditor role        │
│     Returns one punchy plain-English diagnosis sentence per alert     │
│              │                                                        │
│              ▼  diagnosis string injected into each dict              │
│                                                                       │
│  4. app.py  (Streamlit)                                               │
│     Renders live SOC-style dashboard                                  │
│     Metric cards → Status columns → SPL code blocks → AI diagnosis   │
└─────────────────────────────────────────────────────────────────────┘
```

### The Central Data Contract

Every file in this pipeline produces or consumes one shared data shape — the `AlertHealthResult` dictionary. This is the backbone of the architecture:

```python
AlertHealthResult = {
    "name":           str,   # Alert rule name from Splunk
    "query":          str,   # Raw SPL query string
    "last_fired":     str,   # "2 days ago" | "Never" | "47 days ago"
    "result_count":   int,   # Events returned by query right now
    "index_has_data": bool,  # Does the target index contain ANY recent data?
    "status":         str,   # "GREEN" | "AMBER" | "RED"
    "diagnosis":      str    # AI-generated plain-English explanation
}
```

---

## 🛠️ Tech Stack & Prerequisites

### Core Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Data Platform | Splunk Cloud (free trial) | Alert storage, log indexing, SPL execution |
| Agent Protocol | Splunk MCP Server | Natural language → Splunk query bridge |
| Log Ingestion | Splunk HEC (HTTP Event Collector) | Pushing synthetic logs into Splunk Cloud |
| AI Layer | Groq or Gemini free tier API | LLM diagnosis generation |
| Frontend | Streamlit | Live SOC dashboard UI |
| Language | Python 3.9+ | Entire backend pipeline |

### Prerequisites

```bash
# Python dependencies
pip install requests python-dotenv streamlit

# No heavy SDKs. No LangChain. No enterprise frameworks.
# Every external call is a plain synchronous HTTP POST request.
```

### Environment Variables

Create a `.env` file in your project root:

```env
# Splunk Cloud
SPLUNK_HOST=https://your-instance.splunkcloud.com
SPLUNK_USERNAME=your_username
SPLUNK_PASSWORD=your_password
SPLUNK_HEC_URL=https://your-instance.splunkcloud.com:8088/services/collector/event
SPLUNK_HEC_TOKEN=your-hec-token

# Splunk MCP Server
MCP_SERVER_URL=https://your-instance.splunkcloud.com/services/mcp/v1

# LLM API (Groq or Gemini free tier)
LLM_API_KEY=your-api-key-here
LLM_API_URL=https://api.groq.com/openai/v1/chat/completions
```

> ⚠️ Never commit your `.env` file. Add it to `.gitignore` immediately.

---

## 💻 File Breakdown & How to Run

### Run Order — Execute These In Sequence

---

#### `log_generator.py` — Synthetic Infrastructure Log Engine

**What it does:**
Generates 150 realistic log events split across two sourcetypes and pushes them to Splunk Cloud via HTTP Event Collector. This seeds your Splunk environment with searchable data so your alert rules have something to evaluate against.

- **80 events** — `sourcetype=security_logs` (failed/success logins, source IPs, usernames)
- **70 events** — `sourcetype=app_metrics` (CPU %, memory %, host names)
- All events land in `index=main`

**Run it:**
```bash
python log_generator.py
```

**Expected output:**
```
Pushed 150 events to Splunk Cloud.
  - 80 security_logs events
  - 70 app_metrics events
Done. Verify in Splunk: index=main | stats count by sourcetype
```

**Verify in Splunk UI:** Run `index=main | stats count by sourcetype` — you should see both sourcetypes with event counts.

---

#### `splunk_agent.py` — The Core Auditor

**What it does:**
The heart of the pipeline. Connects to the Splunk MCP Server, fetches all saved alert rules using `get_knowledge_objects`, then for each alert:

1. Runs the alert's SPL query via `run_splunk_query` to get a live `result_count`
2. Parses the target index name from the SPL using regex (`index=(\w+)`)
3. Runs a health probe query (`index=<name> | head 1`) to check if that index has any data at all
4. Applies the deterministic classification tree to assign RED / AMBER / GREEN
5. Returns the full list of `AlertHealthResult` dicts

**Classification logic:**
```python
if query_threw_exception:          → RED   (syntax error or network failure)
elif result_count == 0
     and index_has_data == False:  → RED   (index is empty or doesn't exist)
elif result_count == 0
     and index_has_data == True:   → AMBER (data exists, query matches nothing)
elif last_fired > 30 days ago:     → AMBER (suspiciously quiet)
else:                              → GREEN (healthy and active)
```

**Run it standalone (for testing):**
```bash
python splunk_agent.py
```

**Expected output:**
```
Checking: Failed Login Spike Detector...
  result_count=14, index_has_data=True → GREEN
Checking: Legacy Database Timeout Monitor...
  result_count=0, index_has_data=True → AMBER
Checking: Phantom Network Scan Detector...
  result_count=0, index_has_data=False → RED
```

---

#### `ai_explainer.py` — Infrastructure Diagnosis Engine

**What it does:**
Takes each `AlertHealthResult` dict and sends it to a free LLM API (Groq/Gemini) with a tightly engineered two-part prompt. The system prompt locks the model into the role of a **pipeline health auditor**, explicitly forbidding security threat hallucination. The user prompt injects the raw technical metrics and demands a maximum 30-word structural diagnosis.

**The prompt contract enforces:**
- No mention of attackers, threats, or incidents
- No interpretation of what the alert is *named after*
- Output describes only the structural state of the rule itself
- Ends with a concrete recommended action

**Run it standalone (for testing):**
```bash
python ai_explainer.py
```

**Expected output (example):**
```
Testing GREEN scenario:
→ "Query is actively matching events in the index and firing correctly — no action needed."

Testing AMBER scenario:
→ "Index has data but query returns no matches, suggesting the sourcetype in the SPL no longer reflects current log schema — review the query fields."

Testing RED scenario:
→ "Target index does not exist in this environment, making this rule completely blind — create the index or point the alert at the correct data source."
```

---

#### `app.py` — Live SOC Dashboard

**What it does:**
A single-page Streamlit dashboard styled as a Security Operations Center portal. One button triggers the full pipeline and renders results in real time.

**Dashboard sections:**
- **Header metric cards** — total alerts audited, GREEN count, AMBER count, RED count
- **Three-column status view** — alerts sorted into GREEN / AMBER / RED columns
- **Alert cards** — each showing alert name, last fired timestamp, live result count, raw SPL query in a code block, and the AI-generated diagnosis in italics
- **Footer** — stack attribution

**Run it:**
```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser. Click **▶ Run Audit Now**.

---

## 🌋 Engineering Challenges & Solutions

### Challenge 1 — Splunk Cloud Port Firewall Restrictions

**The problem:** Splunk Cloud's management API runs on Port 8089. Most ISP and corporate networks silently drop connections to non-standard ports, causing indefinite hangs rather than clean connection errors. This made the standard `urllib` timeout behaviour unreliable — the socket would open and never close.

**The solution:** Implemented programmatic Bearer Token authorization over Port 443 (standard HTTPS), which passes through all standard network configurations without modification. Added layered defensive exception handling with explicit `requests.exceptions.ConnectionError`, `Timeout`, and `HTTPError` catch blocks, each returning a safe fallback `AlertHealthResult` rather than crashing the audit loop.

```python
# Each MCP call is wrapped independently
try:
    response = requests.post(url, headers=headers, json=body, timeout=15)
    response.raise_for_status()
except requests.exceptions.Timeout:
    return {"status": "RED", "diagnosis": "MCP call timed out — network or firewall issue."}
except requests.exceptions.ConnectionError:
    return {"status": "RED", "diagnosis": "Could not reach Splunk endpoint."}
```

---

### Challenge 2 — LLM Role Confusion and Security Theatre Hallucination

**The problem:** When given alert names like "Failed Login Spike Detector" alongside a status colour, the LLM defaulted to its most statistically common interpretation: generating fictional cybersecurity incident reports. It would invent attacker behaviour, mention "unauthorized access attempts," and completely ignore the structural pipeline metrics we actually passed it.

**The solution:** A two-part prompt architecture with hard role separation. The `system` message establishes an explicit identity ("You are a pipeline health auditor, not a security analyst") with a categorical prohibition list. The `user` message defines each status code's meaning from scratch — GREEN/AMBER/RED are explained as structural pipeline states, not security severity levels. Concrete examples of both correct and forbidden output patterns are included directly in the prompt.

This reduced hallucination to zero across all tested alert name patterns.

---

### Challenge 3 — Zero-Cost AI Without SDK Dependency Bloat

**The problem:** Most LLM integration tutorials assume LangChain, the Anthropic SDK, or OpenAI's official library — each pulling in dozens of transitive dependencies and abstracting away what the actual API calls look like. For a learning-focused project, this creates black boxes that are impossible to debug.

**The solution:** Every LLM API call in `ai_explainer.py` is a plain synchronous `requests.post()` with a manually constructed JSON body. No SDKs. The free developer tiers of Groq and Gemini provide sub-second inference at zero cost, with standard OpenAI-compatible REST endpoints. The entire AI integration is 25 lines of readable Python.

---

## 📁 Project Structure

```
dead_alert_detector/
│
├── .env                   # Secrets — never commit
├── .gitignore             # Must include .env
├── requirements.txt       # requests, python-dotenv, streamlit
│
├── log_generator.py       # Synthetic log data → Splunk Cloud HEC
├── splunk_agent.py        # MCP audit engine → AlertHealthResult list
├── ai_explainer.py        # LLM diagnosis → plain-English strings
└── app.py                 # Streamlit SOC dashboard
```

---



*Built as a project-based learning exercise in agentic pipeline architecture,
prompt engineering, and Splunk MCP Server integration.*
