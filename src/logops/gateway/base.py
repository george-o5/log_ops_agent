"""The single interface between the audit engine and any data platform.

The audit layer depends only on this Protocol. Implementations:

* ``logops.gateway.fixture.FixtureGateway``: in-memory, for unit tests only (``DataSource.FIXTURE``).
* ``logops.gateway.mcp.McpGateway`` (Phase 2): real MCP protocol, talking to either the LogOps simulator
  or the official Splunk MCP Server, selected by profile.

Contract for every method:

* return a validated model, or
* raise an ``IntegrationError`` subclass when the platform cannot be reached or used, or
* (``run_search`` only) raise ``SearchError`` when the platform rejects the SPL.

Never return placeholder or mock data on failure.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from logops.models import (
    DataSource,
    FieldSummary,
    IndexInfo,
    SavedSearch,
    SchedulerRun,
    SearchResult,
    SourcetypeStats,
)

GATEWAY_OPS: tuple[str, ...] = (
    "list_saved_searches",
    "describe_index",
    "sourcetype_stats",
    "field_summary",
    "run_search",
    "scheduler_history",
)


@runtime_checkable
class SplunkGateway(Protocol):
    """Read-only access to the platform. All methods are async because MCP is."""

    @property
    def source(self) -> DataSource: ...

    async def list_saved_searches(self) -> list[SavedSearch]: ...

    async def describe_index(self, name: str) -> IndexInfo:
        """A non-existent index returns ``IndexInfo(exists=False)``. It is not an error."""
        ...

    async def sourcetype_stats(self, index: str, earliest: str) -> list[SourcetypeStats]: ...

    async def field_summary(self, index: str, sourcetype: str | None, earliest: str) -> FieldSummary: ...

    async def run_search(
        self, spl: str, earliest: str, latest: str = "now", max_rows: int = 100
    ) -> SearchResult: ...

    async def scheduler_history(self, rule_name: str, earliest: str) -> list[SchedulerRun]: ...
