# Running the build as separate Claude sessions

Each file here is a self-contained brief for one Claude Code session. The shared rules live in `/CLAUDE.md`,
which every session loads automatically.

## How to start one
1. In the Claude desktop app, open a **new Code session** on this project folder, with **worktree ON**
   so it gets its own branch and can't collide with other sessions.
2. Make sure its base branch is `v2` (or the merged wave branch, see below).
3. Paste:
   ```
   Read CLAUDE.md, docs/ARCHITECTURE.md, docs/METHODOLOGY.md and docs/sessions/<file>.md, then do that phase.
   ```
4. When it finishes, it commits on its branch and updates `docs/ROADMAP.md`.

## Order
```
01 foundation  (single session, already done on branch v2)
        │
        ├── wave A, in parallel ─ 02 simulator-mcp │ 03 audit-engine │ 04 storage-history │ 06a ai-explainer
        │        merge all four into v2 (ask Claude in the main session: "merge wave A branches into v2")
        │
        ├── wave B, in parallel ─ 05 detection-tests │ 06b investigator │ 07 dashboard
        │        merge into v2
        │
        ├── 08 docs-demo
        └── 09 splunk-live   (only once Splunk access exists)
```

### Why this split works
The wave A sessions touch disjoint folders:

| Session | Owns |
|---|---|
| 02 | `simulator/`, `src/logops/gateway/mcp.py`, `src/logops/gateway/profiles/`, `tests/integration/`, `tests/contract/` |
| 03 | `src/logops/audit/`, `src/logops/cli.py`, `tests/unit/audit/` |
| 04 | `src/logops/store.py`, `src/logops/diff.py`, `tests/unit/store/` |
| 06a | `src/logops/ai/` (except `investigate.py`), `tests/unit/ai/` |

Shared files (`pyproject.toml`, `models.py`, `ROADMAP.md`) get small **additive** edits only, which keeps merges trivial.
If two sessions both add a dependency to `pyproject.toml`, the merge conflict is a one-liner.

### Tips
- Use a strong model (Opus) for 02, 03 and 06b. Those are design-heavy. 04, 06a, 07 and 08 are fine on Sonnet.
- If a session asks to change `models.py` in a breaking way, decide in the main session, not inside the worker.
- Ask for verification after each merge: "run the full test suite on v2".
