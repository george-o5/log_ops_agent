# Session 04 — Storage and history (Phase 4)

**Goal:** keep every audit, and answer "what changed between run A and run B, and which evidence proves it?"

## Build
- `src/logops/store.py`: stdlib `sqlite3`, DB path from `Settings`. A `schema_version` table, and migrations applied on open.
  Tables: `runs`, `rule_snapshots` (rule id, name, query, sha256 of query, sha256 of config JSON), `checks`, `findings`,
  `evidence`, `detection_results`, `diagnoses`. Payloads are stored as model JSON. Columns exist only where they're queried or joined.
  API: `save_report(report)`, `get_report(id)`, `list_runs(limit, environment=None)`, `latest(environment)`.
  It's an idempotent save (same report id = no duplicate) and a transaction per report.
- `src/logops/diff.py`: `diff_reports(a, b) -> ReportDiff` (a new model in models.py, additive): rules added or removed,
  status changes, per-check outcome flips with both sides' evidence IDs, new and resolved findings (matched by rule +
  check + category), and query or config hash changes. Plus a `is_regression` helper (any status that got worse).
- CLI: `logops history list`, `logops history show RUN`, `logops history diff RUN_A RUN_B`. Add these as a typer sub-app in
  `src/logops/history_cli.py`, so you don't collide with session 03's `cli.py`. The main CLI mounts it at merge.

## Tests
A fresh DB auto-creates. Round-trip equality. Duplicate save. A diff of two hand-built reports (healthy vs schema drift)
shows exactly the `fields_present` flip, plus the new finding. Migrations run on an old-version DB.

## Don't touch
`audit/`, `simulator/`, `gateway/mcp.py`, `ai/`.

## Done when
All checks in CLAUDE.md pass, ROADMAP row 4 is `done`, and the work is committed on your branch.
