# Session 03 — Deterministic audit engine (Phase 3)

**Goal:** turn gateway data into evidence, check results, findings and a classified `AuditReport`, exactly per `docs/METHODOLOGY.md`.

## Build
- `src/logops/audit/checks.py`: one function per check in the METHODOLOGY table. Signature roughly
  `(rule, analysis, gateway, ctx) -> CheckResult`. Each one records `Evidence` for every gateway call it makes.
  An `IntegrationError` makes that check `ERROR`, with the error as evidence. A `SearchError` makes `query_valid` `FAIL`.
- Cache gateway calls per audit run, so ten rules on one index don't re-query it ten times.
- `src/logops/audit/classify.py`: a pure function `(checks) -> (HealthStatus, reason)` implementing the 5 ordered rules.
- `src/logops/audit/findings.py` (or inside checks): every FAIL or WARN yields a `Finding` with category, severity,
  affected dependency, recommendation and evidence IDs. The text is deterministic templates, no LLM.
- `src/logops/audit/service.py`: `AuditService(gateway, thresholds, clock).run(environment) -> AuditReport`.
  If `list_saved_searches` itself fails, return a report with zero rules and a top-level integration error recorded,
  not an exception and not fake rules.
- `src/logops/cli.py` (typer): `logops audit --scenario NAME [--json] [--via fixture|mcp]`. It prints a compact table and
  always shows the source (SIMULATED / FIXTURE / SPLUNK).

## Tests
- Classification unit tests, one per invariant in METHODOLOGY.md (zero results ≠ RED, ERROR → UNKNOWN, …).
- One test per check (pass, warn, fail and error paths).
- Scenario tests: each acceptance scenario gives the expected rule status, using FixtureGateway.
  If session 02 is already merged, use its scenario-to-FixtureGateway helper. Otherwise build minimal fixtures in
  `tests/fixtures/` and leave a TODO to switch.

## Don't touch
`simulator/`, `gateway/mcp.py`, `store.py`, `ai/`.

## Done when
All checks in CLAUDE.md pass, ROADMAP row 3 is `done`, and the work is committed on your branch.
