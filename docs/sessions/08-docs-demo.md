# Session 08 — README, demo, end-to-end (Phase 8)

**Needs:** phase 7 merged.

## Do
- Delete the legacy root scripts (`splunk_agent.py`, `ai_explainer.py`, `app.py`, `log_generator.py`). Check that nothing
  imports them first. Git history keeps them.
- `scripts/demo.ps1` and `scripts/demo.sh`: create the venv, install, run audits over three scenarios, show a history diff, and launch the dashboard.
- `tests/e2e/`: simulator over stdio, then `logops audit`, then the store, then a diff. It asserts the full acceptance table in ROADMAP.md.
- Rewrite `README.md` **from what is tested today**: the problem, how it works (diagram), quickstart offline,
  scenarios table with real CLI output, screenshots from `docs/img/`, configuration (`.env.example`), testing, the
  "Connecting to real Splunk" section (status: experimental / pending Phase 9), limitations and roadmap.
  Every feature claim must map to a test or a screenshot.
- `docs/development.md`: dev loop, adding a scenario, adding a check.

## Done when
A fresh clone, then `scripts/demo` works offline. All checks in CLAUDE.md pass. ROADMAP row 8 is `done`, and the work is committed.
