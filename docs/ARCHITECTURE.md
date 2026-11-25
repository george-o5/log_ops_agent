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

### Profiles (Phase 2)
A profile (`src/logops/gateway/profiles/<name>.toml`, loaded by `logops.gateway.profiles.load_profile`) maps each op
to an MCP tool and two small adapters: `args` (tool argument → `"{param}"` passthrough or a literal) and
`result_key` (dotted path to the payload). An `[errors]` table maps the server's structured error kinds to
`connect` / `auth` / `timeout` / `unsupported` / `bad_response` / `search`.
- `sim.toml`: one simulator tool per op. Requires `"simulated": true` on every result.
- `splunk.toml`: a commented template until Phase 9 writes it from the real server's `tools/list`. Several ops can be
  served by a single search tool running templated SPL (`| tstats`, `| fieldsummary`, `index=_internal sourcetype=scheduler`),
  which keeps the dependency on unknown tool names small. Loading the unfilled template raises `ConfigError`.

### McpGateway (Phase 2)
`McpGateway(transport, profile)` in `src/logops/gateway/mcp.py`. The transport is anything `mcp.Client` accepts
(stdio parameters, a streamable-HTTP URL, a `Transport`, or an in-process `MCPServer` in tests).
Use it as an async context manager to keep one session open; outside a context each op opens a one-shot session.
On connect it lists tools; an op whose tool is not offered raises `UnsupportedOperation` without calling.

| Failure | Raised |
|---|---|
| process can't start, connection refused/closed, HTTP 5xx | `ConnectError` |
| HTTP 401/403, tool error kind mapped to `auth` | `AuthError` |
| per-call timeout (`anyio.fail_after`), JSON-RPC request timeout | `IntegrationTimeout` |
| op not in profile, tool not offered, method not found / invalid params, SPL outside the simulator subset | `UnsupportedOperation` |
| result not JSON, missing `result_key`, missing `simulated` flag (sim), fails model validation | `BadResponse` |
| tool error kind mapped to `search` on `run_search` | `SearchError` (not an `IntegrationError`) |

Server-supplied messages are clipped to one bounded line before they reach an exception.

## Simulator (Phase 2)
A real MCP server (`mcp.server.mcpserver.MCPServer`) named `logops-simulator` in `simulator/`. Run it with
`python -m simulator --scenario NAME [--http PORT] [--now ISO]` or `logops sim serve`. `logops sim tools` spawns it
over stdio and prints `tools/list`.

- `simulator/scenarios/*.yaml`: one file per scenario: indexes and sourcetypes with seeded event generators
  (`security` and `database` reproduce the v1 `log_generator.py` shapes, `custom` takes field specs), schema drift via
  `rename_fields` / `drop_fields`, saved searches with full config, scheduler history, `faults`
  (`unavailable`, `auth_denied`, `timeout_ms` + `timeout_ops`, `malformed`), and `expected` statuses per rule.
- `simulator/engine.py`: `SimEngine(scenario, now)` generates events deterministically from the seed and an injectable
  "now" (the server defaults to the wall clock at startup; `--now` pins it) and answers the six ops.
- `simulator/server.py`: tools `sim_list_saved_searches`, `sim_describe_index`, `sim_sourcetype_stats`,
  `sim_field_summary`, `sim_run_search`, `sim_scheduler_history`, plus `sim_info`. Every result includes
  `"simulated": true`. Errors are tool errors with `{"error": {"kind", "message"}}`.
- `simulator/fixtures.py`: `fixture_gateway_from_scenario(...)` builds a `FixtureGateway` from the same engine for one
  data window. Contract tests check it agrees with `McpGateway` → simulator.

Simulator semantics worth knowing: `sourcetype_stats` counts events inside the window but reports the newest event
ever seen (so a stopped feed shows its age, with `event_count=0`). `scan_count` is the number of events matching the
base search. Data is anchored at startup, so a long-running server's data slowly ages.

### Simulator SPL subset
`run_search` evaluates only this subset. Pipelines are split with `logops.spl.split_pipeline`.

| Part | Supported |
|---|---|
| Base search | `field=value`, `field!=value`, `<` `>` `<=` `>=` (numeric when both sides are numbers), `*` wildcards, free-text terms (match `_raw`), implicit AND, `AND`, `OR`, `NOT`, parentheses, quoted values. Values match case-insensitively. No `index` term means `index=main`. |
| `search` | same as the base search |
| `where` | comparisons between fields, numbers and `"strings"` (`=` `==` `!=` `<` `>` `<=` `>=`), `AND`/`OR`/`NOT`, parentheses, `isnull(f)`, `isnotnull(f)` |
| `stats` | `count`, `count(f)`, `dc(f)`/`distinct_count(f)`, `sum`, `avg`/`mean`, `min`, `max`, `values`, `as alias`, `by f1, f2` (rows sorted by group key; events missing a by-field are dropped) |
| other | `table`, `fields [+\|-]`, `head [N]`, `sort [N] [-]f ...`, `dedup f ...`, `rename a AS b` |
| time | `earliest`/`latest` arguments: `now`, `0`, `-<n><s\|m\|h\|d\|w>`, epoch seconds, ISO 8601 |

Outcomes for anything else:
- **Unsupported** (`kind=unsupported` → `UnsupportedOperation`, so checks become UNKNOWN): any other command (`eval`,
  `rex`, `lookup`, `tstats`, ...), generating commands (`| tstats ...`), subsearches, macros, `IN`, `earliest=`/`latest=`
  inside the query, time snapping (`@d`), real Splunk stats functions not implemented here (`perc95`, `stdev`, ...),
  `where` functions other than `isnull`/`isnotnull`, stats options.
- **Search error** (`kind=search_error` → `SearchError`, evidence about the rule): only what the simulator can prove
  malformed: unbalanced quotes or parentheses, a comparison with no value or operand, an empty pipe segment, `stats`
  with no aggregation or an empty `by`, a stats function that is not a Splunk function, an invalid time argument.

## Key decisions
- **Pydantic v2 frozen models** are both the API contract and the stored JSON payload.
- **stdlib `sqlite3`**: the schema is small and an ORM adds nothing.
- **`httpx`** for LLM HTTP calls (explicit timeouts, `MockTransport` for tests).
- **Simulator scenarios are YAML** (`pyyaml`, already a dependency) and profiles are TOML (stdlib `tomllib`). No new frameworks.
- **No LangChain or agent frameworks.** The investigator is one bounded loop that's easy to audit.
- **Streamlit** stays as the UI. The dashboard reads stored reports, and audits run only on explicit request.
- **AI providers:** Groq, then Gemini (the user's choice). Optional, never required.
