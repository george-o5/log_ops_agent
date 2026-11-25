# Roadmap & status

Update your row when you finish a phase. Status: `todo` · `in progress` · `done` · `blocked`.

| # | Phase | Session prompt | Depends on | Status | Branch / notes |
|---|---|---|---|---|---|
| 0 | Assessment | — | — | done | `docs/ASSESSMENT.md` |
| 1 | Foundation (package, contracts, gateway Protocol, SPL analyzer, CI) | `sessions/01-foundation.md` | — | done | `v2`: 32 tests, ruff + mypy strict clean |
| 2 | Simulator MCP server + McpGateway | `sessions/02-simulator-mcp.md` | 1 | todo | wave A |
| 3 | Audit engine + classification + CLI | `sessions/03-audit-engine.md` | 1 | todo | wave A |
| 4 | Storage + history diff | `sessions/04-storage-history.md` | 1 | todo | wave A |
| 6a | AI explainer | `sessions/06a-ai-explainer.md` | 1 | todo | wave A |
| 5 | Detection effectiveness tests | `sessions/05-detection-tests.md` | 2, 3 | todo | wave B |
| 6b | Investigator agent | `sessions/06b-investigator.md` | 2, 6a | todo | wave B |
| 7 | Dashboard | `sessions/07-dashboard.md` | 3, 4 | todo | wave B |
| 8 | README, demo, e2e | `sessions/08-docs-demo.md` | 7 | todo | |
| 9 | Official Splunk MCP integration | `sessions/09-splunk-live.md` | Splunk access | blocked | waiting on sandbox |

## Acceptance scenarios (phases 2–5)
| Scenario | Expected rule status |
|---|---|
| `healthy` | GREEN |
| `schema_drift` (field renamed, e.g. `src_ip` → `source_ip`) | RED (`fields_present` FAIL) |
| `ingestion_stopped` | RED (`ingestion_fresh` FAIL) |
| `invalid_spl` | RED (`query_valid` FAIL) |
| `quiet_but_healthy` (valid, fresh, zero matches) | GREEN, never RED |
| `mcp_unavailable` / permission denied | UNKNOWN |
| `detection_regression` (synthetic case missed) | RED (`detection_test` FAIL) |
| `legacy_demo` (the 3 v1 rules) | mixed; the phantom-index rule is RED |

## Contract change requests
*(Sessions add requests here instead of breaking `models.py`.)*

## Legacy cleanup
The root files `splunk_agent.py`, `ai_explainer.py`, `app.py` and `log_generator.py` are deleted in phase 8, once their
replacements are tested. Git history keeps them.
