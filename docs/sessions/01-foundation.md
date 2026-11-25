# Session 01 — Foundation (Phase 1)

**Goal:** a reproducible, offline Python package with the shared contracts every later phase builds on.

## Do
- `pyproject.toml` (hatchling, src layout, package `logops`, console script `logops`), with `requirements.txt` generated from it.
  Runtime: `mcp>=2.3,<3`, `pydantic>=2.7`, `pydantic-settings`, `httpx`, `pyyaml`, `typer`, `streamlit`.
  Dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`, `types-PyYAML`.
- `src/logops/models.py`: enums (`HealthStatus`, `CheckOutcome`, `Severity`, `DataSource`) plus frozen Pydantic models:
  `SavedSearch`, `IndexInfo`, `SourcetypeStats`, `FieldSummary`, `SearchResult`, `SchedulerRun`, `Evidence`,
  `CheckResult`, `Finding`, `Diagnosis`, `RuleAudit`, `AuditReport` (counts computed from rules, never passed in).
- `src/logops/errors.py`: `IntegrationError` hierarchy plus `SearchError` (see ARCHITECTURE.md).
- `src/logops/config.py`: `pydantic-settings` `Settings` (env prefix `LOGOPS_`, secrets as `SecretStr`, repr-safe)
  and `AuditThresholds`.
- `src/logops/gateway/base.py`: the `SplunkGateway` Protocol (6 ops). `gateway/fixture.py`: an in-memory gateway built
  from plain dicts, for unit tests. **Named and documented as test-only.**
- `src/logops/spl.py`: a tokenizer/analyzer that extracts indexes, sourcetypes, referenced fields (search terms,
  `by` clauses, `where`), the command pipeline and threshold comparisons. Quoted strings, `OR`/`NOT` and wildcards are
  handled. It doesn't pretend to be a full parser, and anything unrecognised is listed under `unparsed`.
- `src/logops/ai/prompts.py`: port the v1 explainer's infrastructure-only stance (no invented incidents) as constants.
- `.env.example` (placeholders only), `.gitignore` additions (`archive/`, `.venv`, `*.db`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`).
- `.github/workflows/ci.yml`: ruff, ruff format check, mypy, and pytest on Python 3.11 and 3.12.
- Unit tests: model validation and serialisation round-trip, counts derived from rules, settings never leak secrets in repr,
  and SPL analyzer cases (the three v1 demo queries plus edge cases).

## Don't
- Delete or run the legacy root scripts.
- Build the simulator, the audit checks or storage. Those are later phases.

## Done when
`pytest -q`, `ruff check .`, `ruff format --check .` and `mypy src` are clean. ROADMAP row 1 is `done`, and the work is committed on `v2`.
