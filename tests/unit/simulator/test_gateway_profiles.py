"""Profile loading and McpGateway response handling (in-process MCP server, no subprocess)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import MCPError
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from logops.errors import (
    AuthError,
    BadResponse,
    ConfigError,
    ConnectError,
    IntegrationTimeout,
    SearchError,
    UnsupportedOperation,
)
from logops.gateway import SplunkGateway
from logops.gateway.mcp import McpGateway, map_exception
from logops.gateway.profiles import load_profile
from logops.models import DataSource
from simulator.engine import SimEngine
from simulator.scenario import load_scenario
from simulator.server import build_server

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_sim_profile_maps_every_op() -> None:
    from logops.gateway.base import GATEWAY_OPS

    profile = load_profile("sim")
    assert profile.source is DataSource.SIMULATOR
    assert set(profile.ops) == set(GATEWAY_OPS)
    assert all(b.tool.startswith("sim_") for b in profile.ops.values())


def test_splunk_profile_is_an_unfilled_template() -> None:
    with pytest.raises(ConfigError, match="Phase 9"):
        load_profile("splunk")


def test_profile_rejects_unknown_ops(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        '[profile]\nname="x"\nsource="simulator"\n[ops.delete_everything]\ntool="t"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown gateway ops"):
        load_profile(bad)


def _inproc(scenario: str = "legacy_demo") -> McpGateway:
    return McpGateway(build_server(SimEngine(load_scenario(scenario), now=NOW)), "sim")


def test_gateway_satisfies_protocol() -> None:
    gw = _inproc()
    assert isinstance(gw, SplunkGateway)
    assert gw.source is DataSource.SIMULATOR


async def test_one_shot_calls_without_context() -> None:
    gw = _inproc()
    rules = await gw.list_saved_searches()
    assert len(rules) == 3
    assert gw.tools == frozenset()  # session closed again


async def test_unknown_spl_command_is_unsupported_and_bad_spl_is_search_error() -> None:
    async with _inproc() as gw:
        with pytest.raises(UnsupportedOperation):
            await gw.run_search("index=main | eval x=1", "-1h")
        with pytest.raises(SearchError) as exc:
            await gw.run_search("index=main | where count >", "-1h")
        assert exc.value.spl == "index=main | where count >"


def _fake(result: CallToolResult) -> MCPServer:
    server = MCPServer("fake")
    for name in ("sim_list_saved_searches", "sim_describe_index"):

        async def tool() -> CallToolResult:
            return result

        server.add_tool(tool, name=name)
    return server


async def test_missing_simulated_flag_is_bad_response() -> None:
    res = CallToolResult(content=[], structured_content={"saved_searches": []})
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(BadResponse, match="simulated"):
            await gw.list_saved_searches()


async def test_shape_mismatch_is_bad_response() -> None:
    res = CallToolResult(content=[], structured_content={"simulated": True, "saved_searches": [{"nope": 1}]})
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(BadResponse, match="contract"):
            await gw.list_saved_searches()


async def test_missing_result_key_is_bad_response() -> None:
    res = CallToolResult(content=[], structured_content={"simulated": True})
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(BadResponse, match="saved_searches"):
            await gw.list_saved_searches()


async def test_non_json_text_result_is_bad_response() -> None:
    res = CallToolResult(content=[TextContent(type="text", text="hello")])
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(BadResponse):
            await gw.list_saved_searches()


async def test_unstructured_tool_error_uses_profile_default() -> None:
    res = CallToolResult(content=[TextContent(type="text", text="boom")], is_error=True)
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(BadResponse, match="boom"):
            await gw.list_saved_searches()


async def test_search_kind_outside_run_search_is_bad_response() -> None:
    payload = {"simulated": True, "error": {"kind": "search_error", "message": "x"}}
    res = CallToolResult(content=[], structured_content=payload, is_error=True)
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(BadResponse):
            await gw.list_saved_searches()


async def test_tool_missing_on_server_is_unsupported() -> None:
    res = CallToolResult(content=[], structured_content={"simulated": True, "runs": []})
    async with McpGateway(_fake(res), "sim") as gw:
        with pytest.raises(UnsupportedOperation, match="sim_scheduler_history"):
            await gw.scheduler_history("r", "-1h")


def test_map_exception_table() -> None:
    assert isinstance(map_exception(TimeoutError(), op="x"), IntegrationTimeout)
    assert isinstance(map_exception(FileNotFoundError("nope"), op="x"), ConnectError)
    assert isinstance(map_exception(MCPError(-32000, "closed"), op="x"), ConnectError)
    assert isinstance(map_exception(MCPError(-32001, "slow"), op="x"), IntegrationTimeout)
    assert isinstance(map_exception(MCPError(-32601, "no"), op="x"), UnsupportedOperation)
    assert isinstance(map_exception(MCPError(-32603, "internal"), op="x"), BadResponse)
    grouped = ExceptionGroup("tg", [ConnectionRefusedError("refused")])
    assert isinstance(map_exception(grouped, op="x"), ConnectError)

    class _Resp:
        status_code = 401

    class HTTPStatusError(Exception):
        response = _Resp()

    assert isinstance(map_exception(HTTPStatusError(), op="x"), AuthError)
