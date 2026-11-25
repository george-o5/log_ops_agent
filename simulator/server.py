"""``logops-simulator``: a real MCP server backed by a scenario.

One tool per gateway op (prefixed ``sim_``) plus ``sim_info``. Every result is JSON with ``"simulated": true``.
Success: ``{"simulated": true, "scenario": ..., "<result_key>": <model JSON>}``.
Failure: an MCP tool error (``isError``) whose structured content is
``{"simulated": true, "error": {"kind": <SimError kind>, "message": ...}}``.
The result keys and error kinds are the wire contract mapped by ``src/logops/gateway/profiles/sim.toml``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from simulator.engine import SimEngine, SimError

log = logging.getLogger(__name__)

SERVER_NAME = "logops-simulator"

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

TimeArg = Annotated[
    str, Field(description="Splunk-style time: -24h, -15m, now, 0, epoch or ISO 8601", max_length=64)
]
IndexArg = Annotated[str, Field(description="Index name", min_length=1, max_length=256)]


def _result(payload: dict[str, Any], *, error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, sort_keys=True))],
        structured_content=payload,
        is_error=error,
    )


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value


def build_server(engine: SimEngine) -> MCPServer:
    scenario = engine.scenario
    faults = scenario.faults
    server = MCPServer(
        SERVER_NAME,
        version="2.0.0.dev0",
        instructions=(
            "Simulated Splunk for LogOps. All data is synthetic (every result carries simulated=true). "
            f"Scenario: {scenario.name}."
        ),
        log_level="WARNING",
    )

    async def call(op: str, result_key: str, fn: Callable[[], Any]) -> CallToolResult:
        base: dict[str, Any] = {"simulated": True, "scenario": scenario.name}
        delay = faults.delay_for(op)
        if delay:
            await anyio.sleep(delay)
        fault = faults.fault_for(op)
        if fault == "malformed":
            return _result({**base, result_key: {"unexpected": "shape"}})
        try:
            if fault == "unavailable":
                raise SimError("unavailable", "simulated backend unavailable (scenario fault)")
            if fault == "auth":
                raise SimError("auth", "permission denied for this operation (scenario fault)")
            value = fn()
        except SimError as exc:
            log.info("%s -> %s", op, exc.kind)
            return _result({**base, "error": {"kind": exc.kind, "message": exc.message}}, error=True)
        return _result({**base, result_key: _dump(value)})

    @server.tool(
        name="sim_info", description="Scenario name, simulated clock and seed.", annotations=READ_ONLY
    )
    async def sim_info() -> CallToolResult:
        return _result(
            {
                "simulated": True,
                "scenario": scenario.name,
                "description": scenario.description,
                "now": engine.now.isoformat(),
                "seed": scenario.seed,
            }
        )

    @server.tool(
        name="sim_list_saved_searches",
        description="List saved searches (detection rules) with their full configuration.",
        annotations=READ_ONLY,
    )
    async def sim_list_saved_searches() -> CallToolResult:
        return await call("list_saved_searches", "saved_searches", engine.list_saved_searches)

    @server.tool(
        name="sim_describe_index",
        description="Describe an index. A missing index returns exists=false (not an error).",
        annotations=READ_ONLY,
    )
    async def sim_describe_index(name: IndexArg) -> CallToolResult:
        return await call("describe_index", "index", lambda: engine.describe_index(name))

    @server.tool(
        name="sim_sourcetype_stats",
        description="Per-sourcetype event counts in the window and newest event time for an index.",
        annotations=READ_ONLY,
    )
    async def sim_sourcetype_stats(index: IndexArg, earliest: TimeArg) -> CallToolResult:
        return await call("sourcetype_stats", "sourcetypes", lambda: engine.sourcetype_stats(index, earliest))

    @server.tool(
        name="sim_field_summary",
        description="Which fields appear in recent events of an index (optionally one sourcetype), and how often.",
        annotations=READ_ONLY,
    )
    async def sim_field_summary(
        index: IndexArg,
        earliest: TimeArg,
        sourcetype: Annotated[
            str | None, Field(description="Sourcetype, or null for all", max_length=256)
        ] = None,
    ) -> CallToolResult:
        return await call(
            "field_summary", "field_summary", lambda: engine.field_summary(index, sourcetype, earliest)
        )

    @server.tool(
        name="sim_run_search",
        description="Run SPL from the simulator's documented subset. Unsupported SPL returns kind=unsupported.",
        annotations=READ_ONLY,
    )
    async def sim_run_search(
        spl: Annotated[str, Field(description="SPL query", min_length=1, max_length=20_000)],
        earliest: TimeArg,
        latest: TimeArg = "now",
        max_rows: Annotated[int, Field(ge=1, le=10_000)] = 100,
    ) -> CallToolResult:
        return await call(
            "run_search", "search_result", lambda: engine.run_search(spl, earliest, latest, max_rows)
        )

    @server.tool(
        name="sim_scheduler_history",
        description="Scheduler runs of a saved search since 'earliest', newest first.",
        annotations=READ_ONLY,
    )
    async def sim_scheduler_history(
        rule_name: Annotated[str, Field(min_length=1, max_length=1024)], earliest: TimeArg
    ) -> CallToolResult:
        return await call("scheduler_history", "runs", lambda: engine.scheduler_history(rule_name, earliest))

    return server
