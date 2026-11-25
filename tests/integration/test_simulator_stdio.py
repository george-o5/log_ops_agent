"""Protocol-real integration: spawn ``python -m simulator`` over stdio and drive it through ``McpGateway``."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from logops.errors import (
    AuthError,
    ConnectError,
    IntegrationError,
    IntegrationTimeout,
    SearchError,
    UnsupportedOperation,
)
from logops.gateway.mcp import McpGateway, simulator_gateway
from logops.models import DataSource

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TOOLS = {
    "sim_info",
    "sim_list_saved_searches",
    "sim_describe_index",
    "sim_sourcetype_stats",
    "sim_field_summary",
    "sim_run_search",
    "sim_scheduler_history",
}


def gateway(scenario: str, **kw: float) -> McpGateway:
    return simulator_gateway(scenario, now=NOW, cwd=ROOT, **kw)


async def test_tools_list_and_every_op() -> None:
    async with gateway("legacy_demo") as gw:
        assert gw.server_name == "logops-simulator"
        assert gw.source is DataSource.SIMULATOR
        listing = {t["name"]: t for t in await gw.list_tools()}
        assert set(listing) == EXPECTED_TOOLS
        assert listing["sim_run_search"]["input_schema"]["required"] == ["spl", "earliest"]

        rules = await gw.list_saved_searches()
        assert [r.name for r in rules] == [
            "Failed Login Spike Detector",
            "Legacy Database Timeout Monitor",
            "Phantom Network Scan Detector",
        ]
        assert rules[0].cron_schedule == "*/15 * * * *"
        assert rules[0].actions == ("email",)

        main = await gw.describe_index("main")
        assert main.exists
        assert main.total_event_count == 1920
        assert main.latest_event == datetime(2026, 11, 20, 11, 59, tzinfo=UTC)
        assert (await gw.describe_index("ghost_network_logs")).exists is False

        stats = {s.sourcetype: s for s in await gw.sourcetype_stats("main", "-24h")}
        assert set(stats) == {"security_logs", "database_logs"}
        assert stats["security_logs"].event_count > 0

        fs = await gw.field_summary("main", "security_logs", "-24h")
        assert fs.coverage("src_ip") == 1.0
        assert (await gw.field_summary("main", None, "-24h")).event_count > fs.event_count

        result = await gw.run_search(rules[0].search, "-24h", max_rows=50)
        assert result.spl == rules[0].search
        assert result.scan_count

        runs = await gw.scheduler_history("Failed Login Spike Detector", "-1h")
        assert len(runs) == 5
        assert all(r.status == "success" for r in runs)


async def test_search_error_vs_unsupported_over_the_wire() -> None:
    async with gateway("invalid_spl") as gw:
        broken = next(r for r in await gw.list_saved_searches() if r.id == "ss-failed-login-broken")
        with pytest.raises(SearchError) as exc:
            await gw.run_search(broken.search, "-24h")
        assert not isinstance(exc.value, IntegrationError)
        with pytest.raises(UnsupportedOperation):
            await gw.run_search("index=main | eval x=1", "-24h")


async def test_auth_denied_scenario() -> None:
    async with gateway("auth_denied") as gw:
        assert len(await gw.list_saved_searches()) == 1  # listing is allowed
        for call in (
            gw.describe_index("main"),
            gw.sourcetype_stats("main", "-24h"),
            gw.field_summary("main", None, "-24h"),
            gw.run_search("index=main", "-24h"),
            gw.scheduler_history("x", "-24h"),
        ):
            with pytest.raises(AuthError):
                await call


async def test_mcp_unavailable_scenario() -> None:
    async with gateway("mcp_unavailable") as gw:
        with pytest.raises(ConnectError):
            await gw.list_saved_searches()
        with pytest.raises(ConnectError):
            await gw.run_search("index=main", "-24h")


async def test_slow_backend_times_out_and_session_survives() -> None:
    async with gateway("slow_backend", timeout_s=1.0) as gw:
        with pytest.raises(IntegrationTimeout):
            await gw.run_search("index=main", "-1h")
        assert len(await gw.list_saved_searches()) == 1


async def test_process_that_cannot_start_is_connect_error() -> None:
    params = StdioServerParameters(command="logops-no-such-binary-xyz", args=[])
    with pytest.raises(ConnectError):
        async with McpGateway(params, "sim", timeout_s=10):
            pass


async def test_server_that_exits_is_connect_error() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "simulator", "--scenario", "no_such_scenario"], cwd=str(ROOT)
    )
    with pytest.raises(IntegrationError):
        async with McpGateway(params, "sim", timeout_s=10):
            pass
