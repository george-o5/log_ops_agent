"""SimEngine: deterministic generation and the documented SPL subset (in-process, no MCP)."""

from datetime import UTC, datetime, timedelta

import pytest

from simulator.engine import SimEngine, SimError, parse_time
from simulator.scenario import available_scenarios, load_scenario

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

ACCEPTANCE = {
    "healthy",
    "schema_drift",
    "ingestion_stopped",
    "invalid_spl",
    "quiet_but_healthy",
    "mcp_unavailable",
    "auth_denied",
    "detection_regression",
    "legacy_demo",
}


@pytest.fixture(scope="module")
def legacy() -> SimEngine:
    return SimEngine(load_scenario("legacy_demo"), now=NOW)


def test_acceptance_scenarios_exist_and_load() -> None:
    assert set(available_scenarios()) >= ACCEPTANCE
    for name in available_scenarios():
        scn = load_scenario(name)
        assert scn.name == name
        assert set(scn.expected) <= {r.name for r in scn.saved_searches}


def test_legacy_demo_has_the_three_v1_rules(legacy: SimEngine) -> None:
    searches = {r.name: r.search for r in legacy.list_saved_searches()}
    assert searches == {
        "Failed Login Spike Detector": "index=main sourcetype=security_logs action=failed_login "
        "| stats count by src_ip | where count > 3",
        "Legacy Database Timeout Monitor": "index=main sourcetype=db_logs error=timeout "
        "| stats count by host | where count > 0",
        "Phantom Network Scan Detector": "index=ghost_network_logs sourcetype=firewall_events "
        "| stats count by dest_port | where count > 10",
    }


def test_generation_is_deterministic() -> None:
    a = SimEngine(load_scenario("healthy"), now=NOW)
    b = SimEngine(load_scenario("healthy"), now=NOW)
    assert a.events == b.events
    other = SimEngine(load_scenario("healthy").model_copy(update={"seed": 7}), now=NOW)
    assert [e["_raw"] for e in other.events["main"]] != [e["_raw"] for e in a.events["main"]]


def test_clock_is_injectable() -> None:
    later = SimEngine(load_scenario("healthy"), now=NOW + timedelta(days=1))
    assert later.describe_index("main").latest_event == NOW + timedelta(days=1) - timedelta(minutes=1)


def test_v1_event_shapes(legacy: SimEngine) -> None:
    fields = {f.name for f in legacy.field_summary("main", "security_logs", "-24h").fields}
    assert {"action", "src_ip", "user", "log_type", "timestamp"} <= fields
    fields = {f.name for f in legacy.field_summary("main", "database_logs", "-24h").fields}
    assert {"action", "table", "user", "src_ip", "rows_affected", "duration_ms"} <= fields


def test_missing_index_is_data_not_error(legacy: SimEngine) -> None:
    info = legacy.describe_index("ghost_network_logs")
    assert info.exists is False
    assert legacy.sourcetype_stats("ghost_network_logs", "-24h") == []
    assert legacy.field_summary("ghost_network_logs", None, "-24h").event_count == 0


def test_schema_drift_renames_field() -> None:
    eng = SimEngine(load_scenario("schema_drift"), now=NOW)
    fs = eng.field_summary("main", "security_logs", "-24h")
    assert fs.coverage("src_ip") == 0.0
    assert fs.coverage("source_ip") == 1.0


def test_ingestion_stopped_keeps_last_seen_time() -> None:
    eng = SimEngine(load_scenario("ingestion_stopped"), now=NOW)
    stats = {s.sourcetype: s for s in eng.sourcetype_stats("main", "-24h")}
    assert stats["security_logs"].event_count == 0
    assert stats["security_logs"].latest_event == NOW - timedelta(days=3)
    assert stats["database_logs"].event_count > 0


def test_scheduler_history_window_and_order(legacy: SimEngine) -> None:
    runs = legacy.scheduler_history("Failed Login Spike Detector", "-1h")
    assert [r.scheduled_time for r in runs] == [NOW - timedelta(minutes=15 * k) for k in range(5)]
    assert legacy.scheduler_history("no such rule", "-24h") == []


# ---------------------------------------------------------------- SPL subset


def test_stats_by_and_where(legacy: SimEngine) -> None:
    res = legacy.run_search(
        "index=main sourcetype=database_logs | stats count by table | where count > 20", "-24h"
    )
    assert res.rows
    assert all(r["count"] > 20 for r in res.rows)
    assert [r["table"] for r in res.rows] == sorted(r["table"] for r in res.rows)


def test_boolean_search_terms_and_wildcards(legacy: SimEngine) -> None:
    rows = legacy.run_search(
        'index=main sourcetype=database_logs (action=SELECT OR action="DROP TABLE") NOT user=admin', "-24h"
    ).rows
    assert rows
    assert all(r["action"] in ("SELECT", "DROP TABLE") and r["user"] != "admin" for r in rows)
    wild = legacy.run_search("index=main sourcetype=security_logs action=failed_*", "-24h").rows
    assert wild
    assert all(r["action"] == "failed_login" for r in wild)


def test_default_index_is_main_and_case_insensitive_values(legacy: SimEngine) -> None:
    a = legacy.run_search("sourcetype=security_logs action=FAILED_LOGIN", "-24h")
    b = legacy.run_search("index=main sourcetype=security_logs action=failed_login", "-24h", max_rows=10_000)
    assert a.scan_count == b.scan_count
    assert a.scan_count


def test_max_rows_truncates(legacy: SimEngine) -> None:
    res = legacy.run_search("index=main", "-24h", max_rows=5)
    assert res.row_count == 5
    assert res.truncated
    assert res.scan_count is not None and res.scan_count > 5


def test_zero_results_is_a_result(legacy: SimEngine) -> None:
    res = legacy.run_search("index=ghost_network_logs | stats count", "-24h")
    assert res.rows == ({"count": 0},)


def test_table_head_sort_dedup_rename_fields(legacy: SimEngine) -> None:
    rows = legacy.run_search(
        "index=main sourcetype=database_logs | dedup table | sort -rows_affected | head 3 "
        "| rename rows_affected as n | table table n",
        "-24h",
    ).rows
    assert len(rows) == 3
    assert set(rows[0]) == {"table", "n"}
    assert rows[0]["n"] >= rows[1]["n"] >= rows[2]["n"]
    assert len({r["table"] for r in rows}) == 3


@pytest.mark.parametrize(
    "spl",
    [
        "index=main | stats count by src_ip | where count >",
        'index=main action="unterminated',
        "index=main (action=a",
        "index=main action=",
        "index=main | stats count by",
        "index=main | stats nosuchfunc(x)",
        "index=main | stats count |",
        "",
    ],
)
def test_malformed_spl_is_a_search_error(legacy: SimEngine, spl: str) -> None:
    with pytest.raises(SimError) as exc:
        legacy.run_search(spl, "-1h")
    assert exc.value.kind == "search_error"


@pytest.mark.parametrize(
    "spl",
    [
        "index=main | eval x=1",
        "| tstats count where index=main",
        "index=main [search index=other]",
        "index=main `macro`",
        "index=main | stats perc95(duration_ms)",
        'index=main | where like(user, "a%")',
        "index=main earliest=-1h",
        "index=main user IN (a, b)",
    ],
)
def test_outside_subset_is_unsupported_never_guessed(legacy: SimEngine, spl: str) -> None:
    with pytest.raises(SimError) as exc:
        legacy.run_search(spl, "-1h")
    assert exc.value.kind == "unsupported"


def test_time_parsing() -> None:
    assert parse_time("-15m", NOW) == NOW - timedelta(minutes=15)
    assert parse_time("now", NOW) == NOW
    assert parse_time("0", NOW) is None
    assert parse_time("2026-11-20T00:00:00Z", NOW) == datetime(2026, 11, 20, tzinfo=UTC)
    with pytest.raises(SimError) as exc:
        parse_time("-1d@d", NOW)
    assert exc.value.kind == "unsupported"
    with pytest.raises(SimError) as exc:
        parse_time("yesterday", NOW)
    assert exc.value.kind == "invalid_argument"


def test_bad_time_in_search_is_search_error(legacy: SimEngine) -> None:
    with pytest.raises(SimError) as exc:
        legacy.run_search("index=main", "yesterday")
    assert exc.value.kind == "search_error"
