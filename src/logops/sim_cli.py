"""``logops sim ...``: run and inspect the LogOps simulator MCP server. Everything here is SIMULATED data."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated, Any

import typer

from logops.errors import LogOpsError

sim_app = typer.Typer(no_args_is_help=True, help="Simulator MCP server (synthetic data, labelled SIMULATED).")

BANNER = "SIMULATED: logops-simulator (synthetic data, not Splunk)"


def _now_args(now: str | None) -> list[str]:
    if now is None:
        return []
    try:
        dt = datetime.fromisoformat(now)
    except ValueError:
        raise typer.BadParameter("--now must be ISO 8601 with a timezone") from None
    if dt.tzinfo is None:
        raise typer.BadParameter("--now must include a timezone")
    return ["--now", dt.isoformat()]


@sim_app.command("serve")
def serve(
    scenario: Annotated[str, typer.Option(help="Scenario name or YAML path")] = "legacy_demo",
    http: Annotated[
        int | None, typer.Option(help="Serve streamable HTTP on this port (default: stdio)")
    ] = None,
    host: Annotated[str, typer.Option(help="HTTP bind address")] = "127.0.0.1",
    now: Annotated[str | None, typer.Option(help="Pin the simulated clock (ISO 8601 with timezone)")] = None,
) -> None:
    """Run the simulator MCP server (stdio by default)."""
    from simulator.__main__ import main

    args = ["--scenario", scenario, "--host", host, *_now_args(now)]
    if http is not None:
        args += ["--http", str(http)]
    raise typer.Exit(main(args))


@sim_app.command("scenarios")
def scenarios() -> None:
    """List available scenarios."""
    from simulator.scenario import available_scenarios, load_scenario

    typer.echo(BANNER)
    for name in available_scenarios():
        typer.echo(f"  {name:<22} {' '.join(load_scenario(name).description.split())[:90]}")


@sim_app.command("tools")
def tools(
    scenario: Annotated[str, typer.Option(help="Scenario name")] = "legacy_demo",
    as_json: Annotated[bool, typer.Option("--json", help="Print the raw tools/list as JSON")] = False,
) -> None:
    """Spawn the simulator over stdio and print its tools/list (a real MCP round trip)."""
    from logops.gateway.mcp import simulator_gateway

    async def run() -> tuple[str | None, list[dict[str, Any]]]:
        async with simulator_gateway(scenario) as gw:
            return gw.server_name, await gw.list_tools()

    try:
        server, listing = asyncio.run(run())
    except LogOpsError as exc:
        typer.echo(f"error: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    if as_json:
        typer.echo(json.dumps({"simulated": True, "server": server, "tools": listing}, indent=2))
        return
    typer.echo(BANNER)
    typer.echo(f"server: {server}  scenario: {scenario}")
    for t in listing:
        params = ", ".join(t["input_schema"].get("properties", {}))
        typer.echo(f"  {t['name']}({params})")
        if t["description"]:
            typer.echo(f"      {t['description']}")
