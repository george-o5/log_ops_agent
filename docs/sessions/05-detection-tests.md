# Session 05 — Detection effectiveness tests (Phase 5)

**Needs:** phases 2 and 3 merged.

**Goal:** prove a rule *catches* a known case, instead of inferring health from zero results.

## Build
- A test-case schema (additive models: `DetectionTestCase`, `DetectionTestResult`) in YAML under
  `simulator/scenarios/tests/` or inside each scenario: `rule_id`, `events[]` (templated, with count),
  `expect: {min_rows: N}` or `{group: {src_ip: "10.0.0.5"}}`, and a `notes` field that explains threshold choices.
- Simulator tool `sim_inject_test_events(run_tag, index="logops_test", events)`. Injected events live only in an
  isolated test index and are tagged. A `sim_clear_test_events(run_tag)` tool removes them.
- `src/logops/audit/detection.py`: rewrite the rule's `index=` clause(s) to the test index (using `logops.spl`),
  add the run-tag filter, run it, and compare to expectations. Rules with unrewritable SPL give SKIPPED
  with a reason. `run_detection_tests(...)` returns results plus `recall = detected / total`.
- Wire it in as the `detection_test` check (FAIL on a miss, PASS on a hit, SKIPPED with no case), with evidence for both the injected
  events and the search result.
- Real-Splunk injection: add a `DetectionTestTarget` interface and an HEC implementation that is **disabled by default**
  and requires an explicit `LOGOPS_TEST_INDEX` setting. Unit-test the request it would build with `httpx.MockTransport`. No live calls.
- Port `log_generator.py` into `simulator/generate.py`: bounded `--count`, `--seed`, `--scenario`, output to JSONL,
  optional `--hec` (TLS verified, 10s timeout, success counted only on HTTP 200, token never printed).

## Tests
The `detection_regression` scenario FAILs with evidence. `healthy` PASSes. A threshold rule (`where count > 3`) fails with
3 events and passes with 4. Unrewritable SPL is SKIPPED. Recall math. The generator is bounded and reproducible for a given seed.

## Done when
All checks in CLAUDE.md pass, ROADMAP row 5 is `done`, and the work is committed on your branch.
