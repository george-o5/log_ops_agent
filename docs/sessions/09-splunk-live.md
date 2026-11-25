# Session 09 — Official Splunk MCP Server (Phase 9)

**Needs:** a reachable Splunk instance with the Splunk MCP Server app installed, and a token **with read-only roles**.
The user sets `LOGOPS_SPLUNK_MCP_URL` and `LOGOPS_SPLUNK_TOKEN` in `.env`. Never read or print them.

## Do
1. Connect with `McpGateway` over streamable HTTP. Record the server name and version, and the protocol version.
2. Dump `tools/list` (names, descriptions, input schemas, no secrets) to `docs/splunk-discovery.json`.
   The 2026 docs suggest names like `splunk_run_query` and `splunk_get_indexes` at `https://<host>:8089/services/mcp`,
   but **use only what discovery returns.**
3. Write `src/logops/gateway/profiles/splunk.toml`, mapping each of the 6 ops to a real tool or to templated SPL via the
   search tool (`| tstats`, `| fieldsummary`, `index=_internal sourcetype=scheduler savedsearch_name=…`).
   Ops that can't be supported raise `UnsupportedOperation`, so the checks become UNKNOWN.
4. Add `tests/live/` behind `pytest -m live` (skipped by default and in CI): saved-search listing, a search, index info,
   field summary, scheduler history, and response-shape contract tests.
5. Run a full audit against the real instance and save it (source = `splunk`).
6. Write `docs/splunk-compatibility.md`: the verified server version, op → tool mapping, auth method and known gaps.
   Update the README's "real Splunk" section with **only** what was verified.

## Don't
Call any tool that writes, modify saved searches, or inject test events into production indexes.

## Done when
Live tests pass against the instance, the compatibility doc exists, ROADMAP row 9 is `done`, and the work is committed.
