"""In-memory gateway for **unit tests only**.

It does not speak MCP and does not simulate a platform. It returns exactly what a test put in it.
Protocol-level testing uses the simulator MCP server through ``McpGateway`` instead.
Reports produced through it are stamped ``DataSource.FIXTURE``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from logops.errors import UnsupportedOperation
from logops.models import (
    DataSource,
    FieldSummary,
    IndexInfo,
    SavedSearch,
    SchedulerRun,
    SearchResult,
    SourcetypeStats,
)


@dataclass
class FixtureGateway:
    saved_searches: Sequence[SavedSearch] = ()
    indexes: Mapping[str, IndexInfo] = field(default_factory=dict)
    sourcetypes: Mapping[str, Sequence[SourcetypeStats]] = field(default_factory=dict)
    fields: Mapping[tuple[str, str | None], FieldSummary] = field(default_factory=dict)
    searches: Mapping[str, SearchResult | Exception] = field(default_factory=dict)
    scheduler: Mapping[str, Sequence[SchedulerRun]] = field(default_factory=dict)
    failures: Mapping[str, Exception] = field(default_factory=dict)
    """Op name to the exception it should raise (e.g. ``{"describe_index": ConnectError("down")}``)."""
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    @property
    def source(self) -> DataSource:
        return DataSource.FIXTURE

    def _enter(self, op: str, *args: object) -> None:
        self.calls.append((op, args))
        if op in self.failures:
            raise self.failures[op]

    async def list_saved_searches(self) -> list[SavedSearch]:
        self._enter("list_saved_searches")
        return list(self.saved_searches)

    async def describe_index(self, name: str) -> IndexInfo:
        self._enter("describe_index", name)
        return self.indexes.get(name, IndexInfo(name=name, exists=False))

    async def sourcetype_stats(self, index: str, earliest: str) -> list[SourcetypeStats]:
        self._enter("sourcetype_stats", index, earliest)
        return list(self.sourcetypes.get(index, ()))

    async def field_summary(self, index: str, sourcetype: str | None, earliest: str) -> FieldSummary:
        self._enter("field_summary", index, sourcetype, earliest)
        found = self.fields.get((index, sourcetype))
        if found is None:
            return FieldSummary(index=index, sourcetype=sourcetype, window_earliest=earliest, event_count=0)
        return found

    async def run_search(
        self, spl: str, earliest: str, latest: str = "now", max_rows: int = 100
    ) -> SearchResult:
        self._enter("run_search", spl, earliest, latest, max_rows)
        outcome = self.searches.get(spl)
        if outcome is None:
            raise UnsupportedOperation(f"no fixture registered for SPL: {spl!r}")
        if isinstance(outcome, Exception):
            raise outcome
        rows = outcome.rows[:max_rows]
        return outcome.model_copy(update={"rows": rows, "truncated": len(outcome.rows) > max_rows})

    async def scheduler_history(self, rule_name: str, earliest: str) -> list[SchedulerRun]:
        self._enter("scheduler_history", rule_name, earliest)
        return list(self.scheduler.get(rule_name, ()))
