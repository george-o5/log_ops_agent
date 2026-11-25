"""``python -m simulator --scenario NAME [--http PORT] [--now ISO]``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import datetime

from simulator.engine import SimEngine
from simulator.scenario import available_scenarios, load_scenario
from simulator.server import build_server


def _parse_now(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError("--now must include a timezone, e.g. 2026-01-01T12:00:00+00:00")
    return dt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulator", description="LogOps simulator MCP server")
    parser.add_argument("--scenario", default="legacy_demo", help="scenario name or path to a YAML file")
    parser.add_argument(
        "--http", type=int, metavar="PORT", help="serve streamable HTTP on this port (default: stdio)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    parser.add_argument("--now", type=_parse_now, help="pin the simulated clock (ISO 8601 with timezone)")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = parser.parse_args(argv)

    # stdout carries the MCP protocol in stdio mode, so logs go to stderr only.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    if args.list:
        print("\n".join(available_scenarios()))
        return 0
    try:
        scenario = load_scenario(args.scenario)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    server = build_server(SimEngine(scenario, now=args.now))
    if args.http is not None:
        server.run("streamable-http", host=args.host, port=args.http)
    else:
        server.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
