# Phase 0 — Assessment of the v1 prototype

*Assessed 2026-11-26 against `main` @ `b96f1d7` plus one uncommitted change to `splunk_agent.py`.*

## Repository state
- 11 commits on `main`, last on 2026-06-13. A stray local `master` branch holds only the initial commit.
- Uncommitted WIP in `splunk_agent.py` (hardcoded Splunk Cloud host, attempts to call `/services/mcp/tools/call`)
  was saved to `archive/wip-splunk-agent.patch` (git-ignored) and to `git stash` ("pre-v2 WIP"), then removed from the working tree.
- `.env` exists and is git-ignored. It was not read.
- `requirements.txt` is empty. There are no tests, no CI and no packaging.

## What v1 actually does
| File | Intended | Actual |
|---|---|---|
| `splunk_agent.py` | Pull alerts over MCP, run them, classify | Direct REST `GET saved/searches` (committed) or non-MCP `POST …/tools/call` (WIP). Any failure, **or an empty response**, silently returns 3 hardcoded mock alerts. Health is hardcoded: `index=="main"` → has data, `ghost_network_logs` → no data. |
| `ai_explainer.py` | One-sentence infrastructure diagnosis via Groq/Gemini | The prompt is good. Bugs are listed below. |
| `app.py` | Streamlit dashboard | Runs the full pipeline, LLM calls included, on every rerun. |
| `log_generator.py` | Seed Splunk via HEC | Infinite loop at import time, TLS verification off. |

## Confirmed bugs
1. No MCP client exists. The WIP sends `{"tool":…, "parameters":…}`, but MCP is JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`), so that request could never work against an MCP server.
2. Silent mock fallback: fake alerts are shown as if they were real.
3. Health status is hardcoded by index name. `result_count` is never really measured.
4. Classification can never produce GREEN in practice (`result_count` is always 0), and it treats zero results as a defect.
5. `dispatch.earliest_time` (a search window such as `-24h`) is shown as "last fired".
6. The explainer reads `spl_query`, but the agent emits `query`, so the LLM always sees "Unknown".
7. `if groq: … elif gemini:` means a Groq failure never falls through to Gemini.
8. No timeouts on LLM calls. The Gemini API key is passed in the URL query string. Responses are not validated. The model `gemini-1.5-flash` is outdated.
9. The `__main__` "prompt tests" in `ai_explainer.py` assert against hardcoded strings, so they test nothing.
10. The log generator runs at import, loops forever, uses `verify=False` and suppresses the warning, sets no timeout, and counts failed pushes as sent.
11. Token validation uses fixed lengths (HEC = 36, MCP ≥ 100) and **prints token length and the last 6 characters**.
12. The dashboard merges AMBER and GREEN into "operational", keeps no history, and uses a blanket `except:`.
13. The README describes tools, classification rules and generator output that don't exist.

## Worth keeping
- The explainer's prompt stance: infrastructure-only, never invent incidents, don't interpret the rule's name. → `logops/ai/prompts.py`
- The three demo rules (failed login, DB timeout, phantom index). → simulator scenarios
- The generator's event shapes (security and database events). → simulator data generators
- The GREEN / AMBER / RED vocabulary (plus UNKNOWN) and Streamlit.

## What can be finished without Splunk access
Everything except Phase 9: the simulator MCP server, the audit engine, history, detection tests, AI, the dashboard and docs.
Phase 9 (official Splunk MCP Server) needs a reachable instance to discover the real tool names and schemas.
Public docs show the server at `https://<host>:8089/services/mcp` with a Bearer token, and tool names vary by version
(e.g. `splunk_run_query`). LogOps therefore keeps the real tool mapping in a profile file filled from discovery.
