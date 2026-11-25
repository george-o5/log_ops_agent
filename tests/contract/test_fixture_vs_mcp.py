"""Contract: for every scenario, FixtureGateway (built from the YAML) and McpGateway (→ simulator over stdio)
return equal models, or raise the same error type, for the same inputs."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from logops.errors import LogOpsError
from logops.gateway import SplunkGateway
from logops.gateway.mcp import simulator_gateway
from simulator.fixtures import fixture_gateway_from_scenario
from simulator.scenario import available_scenarios, load_scenario

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
WINDOW = "-24h"
ROOT = Path(__file__).resolve().parents[2]


async def _outcome(fn: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await fn()
    except LogOpsError as exc:
        return ("raised", type(exc))


def _calls(gw: SplunkGateway, scenario: str) -> list[tuple[str, Callable[[], Awaitable[Any]]]]:
    scn = load_scenario(scenario)
    indexes = sorted({i.name for i in scn.indexes} | {"ghost_network_logs"})
    calls: list[tuple[str, Callable[[], Awaitable[Any]]]] = [("list_saved_searches", gw.list_saved_searches)]
    for idx in indexes:
        calls.append((f"describe_index {idx}", lambda i=idx: gw.describe_index(i)))
        calls.append((f"sourcetype_stats {idx}", lambda i=idx: gw.sourcetype_stats(i, WINDOW)))
        calls.append((f"field_summary {idx}", lambda i=idx: gw.field_summary(i, None, WINDOW)))
        for spec in next((x.sourcetypes for x in scn.indexes if x.name == idx), ()):
            calls.append(
                (
                    f"field_summary {idx}/{spec.name}",
                    lambda i=idx, s=spec.name: gw.field_summary(i, s, WINDOW),
                )
            )
    for rule in scn.saved_searches:
        calls.append((f"run_search {rule.id}", lambda q=rule.search: gw.run_search(q, WINDOW)))
        calls.append(
            (f"run_search {rule.id} max_rows=3", lambda q=rule.search: gw.run_search(q, WINDOW, max_rows=3))
        )
        calls.append((f"scheduler_history {rule.id}", lambda n=rule.name: gw.scheduler_history(n, WINDOW)))
    return calls


@pytest.mark.parametrize("scenario", available_scenarios())
async def test_fixture_and_mcp_agree(scenario: str) -> None:
    fixture = fixture_gateway_from_scenario(scenario, now=NOW, window=WINDOW)
    async with simulator_gateway(scenario, now=NOW, cwd=ROOT, timeout_s=1.5) as mcp:
        fixture_calls = _calls(fixture, scenario)
        mcp_calls = _calls(mcp, scenario)
        for (label, f_call), (_, m_call) in zip(fixture_calls, mcp_calls, strict=True):
            expected = await _outcome(f_call)
            actual = await _outcome(m_call)
            assert actual == expected, f"{scenario}: {label} differs"
