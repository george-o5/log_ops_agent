"""``McpGateway``: the one MCP client LogOps uses, for the simulator and (Phase 9) the official Splunk MCP Server.

A ``Profile`` maps each gateway op to a tool, argument adapter and result key. This class adds:

* per-call timeouts (``IntegrationTimeout``);
* mapping of transport / protocol / tool failures to typed ``IntegrationError`` subclasses, and of rejected SPL
  to ``SearchError``;
* validation of every response into ``logops.models`` (anything malformed raises ``BadResponse``).

It never substitutes data on failure.

Use it as an async context manager to keep one session open for many calls. Outside a context, each op opens and
closes its own session (convenient, but a stdio server is spawned per call).
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar

import anyio
from mcp import Client, MCPError, StdioServerParameters
from mcp.client import Transport
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Implementation, TextContent
from mcp_types import CONNECTION_CLOSED, INVALID_PARAMS, METHOD_NOT_FOUND, REQUEST_TIMEOUT
from pydantic import TypeAdapter, ValidationError

from logops import __version__
from logops.errors import (
    AuthError,
    BadResponse,
    ConnectError,
    IntegrationError,
    IntegrationTimeout,
    LogOpsError,
    SearchError,
    UnsupportedOperation,
)
from logops.gateway.profiles import ErrorClass, Profile, load_profile
from logops.models import (
    DataSource,
    FieldSummary,
    IndexInfo,
    SavedSearch,
    SchedulerRun,
    SearchResult,
    SourcetypeStats,
)

log = logging.getLogger(__name__)

McpTransport = StdioServerParameters | str | Transport | MCPServer
"""What ``mcp.Client`` accepts: stdio parameters, a streamable-HTTP URL, a ``Transport``, or an in-process server."""

T = TypeVar("T")

_MAX_MESSAGE = 500

_ERROR_CLASSES: dict[str, type[IntegrationError]] = {
    "connect": ConnectError,
    "auth": AuthError,
    "timeout": IntegrationTimeout,
    "unsupported": UnsupportedOperation,
    "bad_response": BadResponse,
}


def _clip(text: str) -> str:
    """Server text is untrusted: keep it on one line and bounded."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= _MAX_MESSAGE else flat[:_MAX_MESSAGE] + "…"


def _dig(data: Any, path: str | None) -> Any:
    if path is None:
        return data
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for sub in exc.exceptions:
            out.extend(_leaves(sub))
        return out
    return [exc]


def map_exception(exc: BaseException, *, op: str) -> LogOpsError:
    """Map a transport / protocol exception to a typed LogOps error."""
    # Prefer real errors over cancellations that a task group raised alongside them.
    leaves: list[BaseException] = [e for e in _leaves(exc) if isinstance(e, Exception)] or [exc]
    e = leaves[0]
    if isinstance(e, LogOpsError):
        return e
    where = f"{op}: "
    if isinstance(e, TimeoutError):
        return IntegrationTimeout(f"{where}timed out")
    if isinstance(e, MCPError):
        msg = _clip(e.message)
        if e.code == REQUEST_TIMEOUT:
            return IntegrationTimeout(f"{where}{msg}")
        if e.code == CONNECTION_CLOSED:
            return ConnectError(f"{where}connection closed: {msg}")
        if e.code in (METHOD_NOT_FOUND, INVALID_PARAMS):
            return UnsupportedOperation(f"{where}{msg}")
        return BadResponse(f"{where}protocol error {e.code}: {msg}")
    status = getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(status, int):
        if status in (401, 403):
            return AuthError(f"{where}HTTP {status}")
        return ConnectError(f"{where}HTTP {status}")
    if isinstance(e, ValidationError):
        return BadResponse(f"{where}response failed protocol validation")
    if isinstance(e, OSError | anyio.ClosedResourceError | anyio.BrokenResourceError | anyio.EndOfStream):
        return ConnectError(f"{where}{type(e).__name__}: {_clip(str(e))}")
    if type(e).__module__.split(".")[0] in ("httpx", "httpx2", "httpcore"):
        if "Timeout" in type(e).__name__:
            return IntegrationTimeout(f"{where}{type(e).__name__}")
        return ConnectError(f"{where}{type(e).__name__}: {_clip(str(e))}")
    return IntegrationError(f"{where}{type(e).__name__}: {_clip(str(e))}")


class McpGateway:
    """``SplunkGateway`` over MCP. ``source`` comes from the profile (``simulator`` or ``splunk``)."""

    def __init__(
        self,
        transport: McpTransport,
        profile: Profile | str,
        *,
        timeout_s: float | None = None,
    ) -> None:
        self._transport = transport
        self._profile = load_profile(profile) if isinstance(profile, str) else profile
        self._timeout = timeout_s if timeout_s is not None else self._profile.profile.timeout_s
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._tools: frozenset[str] | None = None
        self.server_name: str | None = None
        self.server_version: str | None = None
        self.protocol_version: str | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def source(self) -> DataSource:
        return self._profile.source

    @property
    def profile(self) -> Profile:
        return self._profile

    @property
    def tools(self) -> frozenset[str]:
        """Tool names discovered on connect (empty before connecting)."""
        return self._tools or frozenset()

    async def __aenter__(self) -> McpGateway:
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._client is not None:
            return
        stack = AsyncExitStack()
        try:
            client = Client(
                self._transport,
                read_timeout_seconds=self._timeout,
                client_info=Implementation(name="logops", version=__version__),
            )
            await stack.enter_async_context(client)
            names: set[str] = set()
            cursor: str | None = None
            for _ in range(100):
                with anyio.fail_after(self._timeout):
                    listing = await client.list_tools(cursor=cursor)
                names.update(t.name for t in listing.tools)
                cursor = listing.next_cursor
                if not cursor:
                    break
        except Exception as exc:
            await self._safe_close(stack)
            raise map_exception(exc, op="connect") from exc
        self._stack, self._client, self._tools = stack, client, frozenset(names)
        info = client.server_info
        self.server_name = info.name if info else None
        self.server_version = info.version if info else None
        self.protocol_version = client.protocol_version
        log.debug("connected to %s (%d tools)", self.server_name, len(names))

    async def close(self) -> None:
        stack, self._stack, self._client, self._tools = self._stack, None, None, None
        if stack is not None:
            await self._safe_close(stack)

    @staticmethod
    async def _safe_close(stack: AsyncExitStack) -> None:
        try:
            await stack.aclose()
        except Exception:  # closing a broken transport must not mask the real error
            log.debug("error while closing MCP session", exc_info=True)

    async def list_tools(self) -> list[dict[str, Any]]:
        """Raw ``tools/list`` (name, description, input schema) for discovery and ``logops sim tools``."""
        async with self._session() as client:
            try:
                with anyio.fail_after(self._timeout):
                    listing = await client.list_tools()
            except Exception as exc:
                raise map_exception(exc, op="tools/list") from exc
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in listing.tools
        ]

    # ------------------------------------------------------------------ calls

    def _session(self) -> _SessionScope:
        return _SessionScope(self)

    async def _call(self, op: str, params: dict[str, Any]) -> Any:
        binding = self._profile.ops.get(op)
        if binding is None:
            raise UnsupportedOperation(f"{op}: not mapped in gateway profile {self._profile.name!r}")
        async with self._session() as client:
            if self._tools is not None and binding.tool not in self._tools:
                raise UnsupportedOperation(f"{op}: server does not offer tool {binding.tool!r}")
            args = binding.render_args(params)
            try:
                with anyio.fail_after(self._timeout):
                    result = await client.call_tool(binding.tool, args)
            except Exception as exc:
                raise map_exception(exc, op=op) from exc
        payload = self._payload(op, result, spl=params.get("spl"))
        if self._profile.profile.require_simulated_flag and payload.get("simulated") is not True:
            raise BadResponse(f"{op}: response is missing simulated=true")
        if binding.result_key is None:
            return payload
        if not _has_path(payload, binding.result_key):
            raise BadResponse(f"{op}: response has no {binding.result_key!r}")
        return _dig(payload, binding.result_key)

    def _payload(self, op: str, result: CallToolResult, *, spl: str | None) -> dict[str, Any]:
        data: Any = result.structured_content
        if data is None:
            text = "".join(c.text for c in result.content if isinstance(c, TextContent))
            try:
                data = json.loads(text) if text.strip() else None
            except json.JSONDecodeError:
                data = None
            if data is None and result.is_error:
                raise self._error(op, None, text, spl=spl)
        if result.is_error:
            text = "".join(c.text for c in result.content if isinstance(c, TextContent))
            raise self._error(op, data, text, spl=spl)
        if not isinstance(data, dict):
            raise BadResponse(f"{op}: expected a JSON object result")
        return data

    def _error(self, op: str, data: Any, text: str, *, spl: str | None) -> LogOpsError:
        mapping = self._profile.errors
        kind = _dig(data, mapping.kind_path) if mapping.kind_path else None
        message = _dig(data, mapping.message_path) if mapping.message_path else None
        msg = _clip(str(message) if message is not None else text or "tool error")
        cls: ErrorClass = (
            mapping.kinds.get(str(kind), mapping.default) if kind is not None else mapping.default
        )
        if cls == "search":
            if op != "run_search":
                return BadResponse(f"{op}: unexpected search error: {msg}")
            return SearchError(msg, spl=spl)
        return _ERROR_CLASSES[cls](f"{op}: {msg}")

    def _validate(self, op: str, adapter: TypeAdapter[T], value: Any) -> T:
        try:
            return adapter.validate_python(value)
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})[:10]
            raise BadResponse(f"{op}: response does not match the {op} contract (fields: {fields})") from None

    # ------------------------------------------------------------------ SplunkGateway

    async def list_saved_searches(self) -> list[SavedSearch]:
        raw = await self._call("list_saved_searches", {})
        return self._validate("list_saved_searches", _SAVED, raw)

    async def describe_index(self, name: str) -> IndexInfo:
        raw = await self._call("describe_index", {"name": name})
        return self._validate("describe_index", _INDEX, raw)

    async def sourcetype_stats(self, index: str, earliest: str) -> list[SourcetypeStats]:
        raw = await self._call("sourcetype_stats", {"index": index, "earliest": earliest})
        return self._validate("sourcetype_stats", _STATS, raw)

    async def field_summary(self, index: str, sourcetype: str | None, earliest: str) -> FieldSummary:
        raw = await self._call(
            "field_summary", {"index": index, "sourcetype": sourcetype, "earliest": earliest}
        )
        return self._validate("field_summary", _FIELDS, raw)

    async def run_search(
        self, spl: str, earliest: str, latest: str = "now", max_rows: int = 100
    ) -> SearchResult:
        raw = await self._call(
            "run_search", {"spl": spl, "earliest": earliest, "latest": latest, "max_rows": max_rows}
        )
        return self._validate("run_search", _SEARCH, raw)

    async def scheduler_history(self, rule_name: str, earliest: str) -> list[SchedulerRun]:
        raw = await self._call("scheduler_history", {"rule_name": rule_name, "earliest": earliest})
        return self._validate("scheduler_history", _RUNS, raw)


def _has_path(data: Any, path: str) -> bool:
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


_SAVED: TypeAdapter[list[SavedSearch]] = TypeAdapter(list[SavedSearch])
_INDEX: TypeAdapter[IndexInfo] = TypeAdapter(IndexInfo)
_STATS: TypeAdapter[list[SourcetypeStats]] = TypeAdapter(list[SourcetypeStats])
_FIELDS: TypeAdapter[FieldSummary] = TypeAdapter(FieldSummary)
_SEARCH: TypeAdapter[SearchResult] = TypeAdapter(SearchResult)
_RUNS: TypeAdapter[list[SchedulerRun]] = TypeAdapter(list[SchedulerRun])


class _SessionScope:
    """Yields the open client, or opens a one-shot session when the gateway is not entered."""

    def __init__(self, gw: McpGateway) -> None:
        self._gw = gw
        self._owned = False

    async def __aenter__(self) -> Client:
        if self._gw._client is None:
            await self._gw.connect()
            self._owned = True
        assert self._gw._client is not None
        return self._gw._client

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._owned:
            await self._gw.close()


def sim_stdio_transport(
    scenario: str,
    *,
    now: datetime | None = None,
    python: str | None = None,
    cwd: str | Path | None = None,
    extra_args: Sequence[str] = (),
) -> StdioServerParameters:
    """Stdio parameters that launch ``python -m simulator --scenario <scenario>``.

    Only the MCP SDK's default environment is passed to the child, so LogOps secrets never reach it.
    """
    args = ["-m", "simulator", "--scenario", scenario]
    if now is not None:
        args += ["--now", now.isoformat()]
    args += list(extra_args)
    return StdioServerParameters(command=python or sys.executable, args=args, cwd=cwd)


def simulator_gateway(
    scenario: str,
    *,
    now: datetime | None = None,
    timeout_s: float | None = None,
    cwd: str | Path | None = None,
) -> McpGateway:
    """``McpGateway`` over stdio to a fresh simulator process with the ``sim`` profile."""
    return McpGateway(sim_stdio_transport(scenario, now=now, cwd=cwd), "sim", timeout_s=timeout_s)


__all__ = ["McpGateway", "McpTransport", "map_exception", "sim_stdio_transport", "simulator_gateway"]
