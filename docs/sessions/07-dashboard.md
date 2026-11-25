# Session 07 — Dashboard (Phase 7)

**Needs:** phases 3 and 4 merged (5, 6a and 6b are used if present, and hidden gracefully if not).

**Goal:** a dense, calm, engineer-facing Streamlit app over stored reports.

## Build (`dashboard/`)
- `app.py`: Overview. Counts per status (GREEN / AMBER / RED / UNKNOWN as **separate** numbers), total findings,
  last audit time, environment and source. A permanent, unmissable **SIMULATED** banner whenever the source isn't `splunk`.
- `pages/1_Rules.py`: a filterable table (status, index, sourcetype, text search) with columns for name, index, status, latest event seen,
  last scheduler run, and number of findings. Selecting a rule opens the detail view: config, SPL (code block), parsed dependencies,
  the checks table with outcome and evidence expanders, findings, diagnosis (or "AI not configured"), and an "Investigate" button when 6b exists.
- `pages/2_Findings.py`: all findings, grouped and filterable by category and severity, with affected rules and evidence.
- `pages/3_History.py`: a list of runs, and pick two to see the `ReportDiff` (status changes, check flips, new and resolved findings).
- `pages/4_Simulator.py`: pick a scenario, then click "Run audit". It runs the audit via `McpGateway` against the simulator, saves it, and shows it.
  Audits **never** run on page load.
- `ui.py`: shared status chip, empty/error states and number formatting. Use restrained styling: a small custom CSS block,
  monospaced SPL, no emoji headers and no decorative cards. Streamlit's `@st.cache_resource` only for the store connection.

## Tests
Streamlit `AppTest` smoke tests per page with a temp DB seeded from saved reports. The empty-DB state renders.
The SIMULATED banner is present for simulator reports.

## Finish
Take screenshots of each page with the `legacy_demo` and `schema_drift` scenarios into `docs/img/`.

## Done when
All checks in CLAUDE.md pass, ROADMAP row 7 is `done`, and the work is committed on your branch.
