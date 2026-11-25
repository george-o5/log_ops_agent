"""Build a ``FixtureGateway`` from a scenario, for fast unit tests (session 03 and later).

The fixture is precomputed from the same ``SimEngine`` the MCP server uses, for one data window. Contract tests
check that this fixture and ``McpGateway`` → simulator return equal models for the same inputs.

``FixtureGateway`` keys its answers by index / sourcetype / SPL / rule only, so the window is fixed at build time:
call the gateway with ``earliest == window`` to get matching answers.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

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
from logops.gateway.base import GATEWAY_OPS
from logops.gateway.fixture import FixtureGateway
from logops.models import FieldSummary, IndexInfo, SearchResult, SourcetypeStats
from logops.spl import analyze
from simulator.engine import SimEngine, SimError
from simulator.scenario import FaultSpec, Scenario, load_scenario

FIXTURE_MAX_ROWS = 10_000


def sim_error_to_exception(exc: SimError, *, spl: str | None = None) -> LogOpsError:
    """The same mapping ``sim.toml`` declares for ``McpGateway``."""
    if exc.kind == "search_error":
        return SearchError(exc.message, spl=spl)
    if exc.kind in ("unsupported", "invalid_argument"):
        return UnsupportedOperation(exc.message)
    if exc.kind == "auth":
        return AuthError(exc.message)
    if exc.kind == "unavailable":
        return ConnectError(exc.message)
    return IntegrationError(exc.message)  # pragma: no cover - SimError validates kinds


def _fault_failures(faults: FaultSpec) -> dict[str, Exception]:
    failures: dict[str, Exception] = {}
    for op in GATEWAY_OPS:
        kind = faults.fault_for(op)
        if kind == "unavailable":
            failures[op] = ConnectError("simulated backend unavailable (scenario fault)")
        elif kind == "auth":
            failures[op] = AuthError("permission denied for this operation (scenario fault)")
        elif kind == "malformed":
            failures[op] = BadResponse("malformed response (scenario fault)")
        elif faults.delay_for(op):
            failures[op] = IntegrationTimeout(f"{op} timed out (scenario fault)")
    return failures


def fixture_gateway_from_scenario(
    scenario: Scenario | str,
    *,
    now: datetime,
    window: str = "-24h",
    extra_spl: Iterable[str] = (),
    include_faults: bool = True,
) -> FixtureGateway:
    """Precompute every answer the audit is likely to ask for in ``window``.

    Covers: all saved searches; every index declared in the scenario or referenced by a rule (missing ones come
    back ``exists=False`` from FixtureGateway itself); sourcetype stats per index; field summaries per
    (index, sourcetype) and per (index, None); each rule's SPL plus ``extra_spl``; scheduler history per rule.
    """
    scn = load_scenario(scenario) if isinstance(scenario, str) else scenario
    engine = SimEngine(scn, now=now)
    rules = engine.list_saved_searches()

    index_names = {i.name for i in scn.indexes}
    for rule in rules:
        index_names.update(analyze(rule.search).indexes)

    indexes: dict[str, IndexInfo] = {}
    sourcetypes: dict[str, list[SourcetypeStats]] = {}
    fields: dict[tuple[str, str | None], FieldSummary] = {}
    for name in sorted(index_names):
        info = engine.describe_index(name)
        if not info.exists:
            continue
        indexes[name] = info
        stats = engine.sourcetype_stats(name, window)
        sourcetypes[name] = stats
        fields[(name, None)] = engine.field_summary(name, None, window)
        for st in stats:
            fields[(name, st.sourcetype)] = engine.field_summary(name, st.sourcetype, window)

    searches: dict[str, SearchResult | Exception] = {}
    for spl in [*(r.search for r in rules), *extra_spl]:
        try:
            searches[spl] = engine.run_search(spl, window, "now", FIXTURE_MAX_ROWS)
        except SimError as exc:
            searches[spl] = sim_error_to_exception(exc, spl=spl)

    scheduler = {r.name: engine.scheduler_history(r.name, window) for r in rules}

    return FixtureGateway(
        saved_searches=rules,
        indexes=indexes,
        sourcetypes=sourcetypes,
        fields=fields,
        searches=searches,
        scheduler=scheduler,
        failures=_fault_failures(scn.faults) if include_faults else {},
    )
