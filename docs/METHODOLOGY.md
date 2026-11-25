# Audit methodology

## Outcomes and statuses
Each **check** produces one `CheckOutcome`:

| Outcome | Meaning |
|---|---|
| `PASS` | Evidence supports a healthy state |
| `WARN` | Degradation or concern, not a confirmed failure |
| `FAIL` | Confirmed failure, backed by evidence |
| `ERROR` | Couldn't evaluate (connectivity, permission, unsupported query) |
| `SKIPPED` | Not applicable or not configured (e.g. no detection test defined) |

Each **rule** gets one `HealthStatus`, from `logops.audit.classify` (pure function, no I/O):

1. Any `FAIL` → **RED**
2. Otherwise, any `ERROR` on a check → **UNKNOWN**
3. Otherwise, any `WARN` → **AMBER**
4. Otherwise, a *required* check `SKIPPED` → **AMBER** (incomplete validation)
5. Otherwise → **GREEN**

The reason string names the decisive checks, e.g. `RED: index_exists=FAIL (index 'ghost_network_logs' not found)`.

### Invariants (each has a test)
- Zero search results never changes status on its own.
- An alert not firing recently never changes status on its own.
- `IntegrationError` → `ERROR` → UNKNOWN. Never RED.
- A missing index (`index_exists`) and invalid SPL (`query_valid`) are separate checks with separate findings.
- Ingestion health and detection effectiveness are separate checks.
- A rule is never called "effective" just because its SPL returned *some* events. Only `detection_test` speaks to effectiveness.

## Checks
| id | Required | FAIL | WARN |
|---|---|---|---|
| `config` | yes | rule disabled, or scheduled alert with no cron | very wide or tiny dispatch window, no alert action |
| `query_valid` | yes | server rejects the SPL (`SearchError`) | — |
| `index_exists` | yes | referenced index absent | no index in the SPL (searches default indexes) |
| `ingestion_fresh` | yes | newest event for a required sourcetype older than `fail_lag` | older than `warn_lag` |
| `volume` | no | — | recent volume below `drop_pct` of the baseline (previous run or the trailing window) |
| `sourcetype_present` | yes | referenced sourcetype has no events in the window | — |
| `fields_present` | yes | a field the SPL filters or groups on is absent from recent events of that sourcetype | field present in < `min_coverage` of events |
| `detection_test` | no | known synthetic case not detected | — (SKIPPED when no test is defined) |
| `exec_history` | no | scheduler recorded errors for this search | runs skipped / no history found |

Thresholds live in `logops.config.AuditThresholds` and are recorded on each report.

## Detection tests (Phase 5)
A test case says: "inject these events (tagged with a run id) into an isolated test index, run the rule's SPL
retargeted at that index, and expect ≥ N rows, or this group key." Threshold rules (`where count > 3`) must be fed
enough events to cross the threshold, and the test case states that explicitly.
`recall = detected_cases / total_cases`. Tests run only in the simulator until a safe real-Splunk test index is configured.

## Evidence
Every check result references `Evidence` records: the gateway op, its arguments, the observed values,
the timestamp and the source (`simulator` / `splunk` / `fixture`). Findings and AI diagnoses may cite only these IDs.
