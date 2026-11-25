# Architecture

> This is the target design. `docs/ROADMAP.md` records which parts are implemented.

```
 dashboard (Streamlit) ─┐
 CLI  (logops …)       ─┼─> AuditService ─> checks ─> classify ─> AuditReport ─> Store (SQLite)
 investigator (LLM)    ─┘         │                                     │
                                  ▼                                     ▼
                          SplunkGateway (Protocol)               explainer (LLM, optional)
               ┌──────────────────┼───────────────────┐
        FixtureGateway       McpGateway(profile)
        unit tests only           │  MCP JSON-RPC (stdio / streamable HTTP)
                        ┌─────────┴──────────┐
               logops-simulator        official Splunk MCP Server
               profile: sim.toml       profile: splunk.toml (from discovery)
```

## Layers
| Layer | Module | Knows about |
|---|---|---|
| Contracts | `logops.models`, `logops.errors` | nothing else |
| SPL analysis | `logops.spl` | models |
| Data access | `logops.gateway.*` | models, errors, MCP SDK |
| Audit | `logops.audit.*` | the gateway **Protocol** only, models |
| Persistence | `logops.store`, `logops.diff` | models |
| AI | `logops.ai.*` | models, gateway Protocol (investigator only) |
| Apps | `logops.cli`, `dashboard/` | everything above |
| Simulator | `simulator/` | its own scenarios; shares `logops.models` for output shapes |

The audit layer never imports `mcp`. Swapping simulator and Splunk changes only the gateway's profile.

## The gateway
`SplunkGateway` (`src/logops/gateway/base.py`) has six read-only **async** operations (async because MCP is; CLI and Streamlit call them via `asyncio.run`):

| Op | Returns | Purpose |
|---|---|---|
| `list_saved_searches()` | `list[SavedSearch]` | rule inventory and config |
| `describe_index(name)` | `IndexInfo` | exists? event count, earliest/latest event |
| `sourcetype_stats(index, earliest)` | `list[SourcetypeStats]` | per-sourcetype counts and freshness |
| `field_summary(index, sourcetype, earliest)` | `FieldSummary` | which fields appear, and how often |
| `run_search(spl, earliest, latest, max_rows)` | `SearchResult` | execute SPL (detection query, probes) |
| `scheduler_history(rule_name, earliest)` | `list[SchedulerRun]` | did the saved search run, and did it error? |

Each op returns a typed model or raises an `IntegrationError` subclass
(`ConnectError`, `AuthError`, `IntegrationTimeout`, `UnsupportedOperation`, `BadResponse`).
`SearchError` is different: the server ran fine and rejected the SPL. That is evidence about the rule, not about connectivity.

### Profiles (planned, Phase 2)
A profile maps each op to an MCP tool and two small adapters (args in, result out).
- `sim.toml`: one simulator tool per op.
- `splunk.toml`: written in Phase 9 from the real server's `tools/list`. Several ops can be served by a single search tool
  running templated SPL (`| tstats`, `| fieldsummary`, `index=_internal sourcetype=scheduler`), which keeps
  the dependency on unknown tool names small.

## Simulator (planned, Phase 2)
A real MCP server (`mcp.server.mcpserver.MCPServer`) named `logops-simulator`. It is backed by YAML scenarios
(indexes, sourcetypes, seeded event generators, saved searches, scheduler history, faults). It evaluates a documented
SPL subset. Unsupported commands return a structured "unsupported" error, so checks become UNKNOWN rather than guessed.
Every response includes `"simulated": true`.

## Key decisions
- **Pydantic v2 frozen models** are both the API contract and the stored JSON payload.
- **stdlib `sqlite3`**: the schema is small and an ORM adds nothing.
- **`httpx`** for LLM HTTP calls (explicit timeouts, `MockTransport` for tests).
- **No LangChain or agent frameworks.** The investigator is one bounded loop that's easy to audit.
- **Streamlit** stays as the UI. The dashboard reads stored reports, and audits run only on explicit request.
- **AI providers:** Groq, then Gemini (the user's choice). Optional, never required.
