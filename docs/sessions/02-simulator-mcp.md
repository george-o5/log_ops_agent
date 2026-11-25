# Session 02 — Simulator MCP server + McpGateway (Phase 2)

**Goal:** a protocol-real MCP environment that needs no Splunk access, and the one MCP client LogOps will also use against real Splunk.

## First
Read the installed MCP SDK v2 API (`mcp.server.mcpserver.MCPServer`, `mcp.Client`, stdio and `streamable_http_client`)
or https://py.sdk.modelcontextprotocol.io/. Most online examples are v1, so don't copy `FastMCP` / `ClientSession` code.

## Build
- `simulator/scenarios/*.yaml`: one file per scenario: indexes, sourcetypes, seeded event generators
  (reuse the v1 `log_generator.py` event shapes: security logins, database ops), saved searches with full config,
  scheduler history, and a `faults:` block (e.g. `auth_denied`, `timeout_ms`, `unavailable`).
  Write the acceptance scenarios from `docs/ROADMAP.md`, including `legacy_demo` with the three v1 rules.
- `simulator/engine.py`: generates events deterministically from a seed and a fixed "now" (an injectable clock), and evaluates the
  SPL subset in ARCHITECTURE.md using `logops.spl` for tokenising. Unsupported commands raise a structured error. Never guess.
- `simulator/server.py`: an `MCPServer("logops-simulator")` with one tool per gateway op (your naming, prefixed `sim_`),
  typed input schemas, JSON results that include `"simulated": true`. Run with `python -m simulator --scenario X [--http PORT]`.
  The scenario is selectable at startup.
- `src/logops/gateway/mcp.py`: `McpGateway(transport, profile)` implementing `SplunkGateway`. It maps MCP/transport
  failures to the typed `IntegrationError`s, applies per-call timeouts, and validates every response into models.
  A malformed response raises `BadResponse`.
- `src/logops/gateway/profiles/sim.toml` plus a loader. Leave `splunk.toml` as a commented template that says
  "fill from discovery in Phase 9". **Don't guess real tool names.**
- `logops sim serve` / `logops sim tools` CLI hooks (add them to `cli.py` minimally if it doesn't exist yet).

## Tests
- `tests/integration/`: spawn the simulator over **stdio**, `tools/list`, call every op through `McpGateway`.
- `tests/contract/`: for each scenario, `FixtureGateway` and `McpGateway` return equal models for the same inputs.
  (Add a helper that builds a FixtureGateway from the scenario YAML, so 03 can reuse it.)
- Fault scenarios produce the right `IntegrationError` subclass. Invalid SPL produces `SearchError`, not an IntegrationError.

## Don't touch
`src/logops/audit/`, `store.py`, `ai/`.

## Done when
All checks in CLAUDE.md pass, ROADMAP row 2 is `done`, and the work is committed on your branch.
