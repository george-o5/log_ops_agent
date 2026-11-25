"""Shared data contracts.

Every layer exchanges these models, and they are also the JSON payload persisted by the store.
Rules for changing this file live in CLAUDE.md: add fields with defaults, never rename or remove.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field


def new_id(prefix: str) -> str:
    """Short, prefixed, random identifier (e.g. ``ev-3f9a1c2b7d10``)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- enums


class HealthStatus(StrEnum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"
    UNKNOWN = "UNKNOWN"


class CheckOutcome(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DataSource(StrEnum):
    """Where data came from. Anything other than SPLUNK must be labelled as non-production."""

    SIMULATOR = "simulator"
    SPLUNK = "splunk"
    FIXTURE = "fixture"


# --------------------------------------------------------------------------- platform data


class SavedSearch(_Model):
    """A saved search / detection rule as configured on the platform."""

    id: str
    name: str
    search: str
    app: str | None = None
    owner: str | None = None
    description: str | None = None
    disabled: bool = False
    is_scheduled: bool = False
    cron_schedule: str | None = None
    dispatch_earliest: str | None = None
    dispatch_latest: str | None = None
    alert_type: str | None = None
    alert_comparator: str | None = None
    alert_threshold: str | None = None
    actions: tuple[str, ...] = ()


class IndexInfo(_Model):
    name: str
    exists: bool
    total_event_count: int | None = None
    earliest_event: AwareDatetime | None = None
    latest_event: AwareDatetime | None = None


class SourcetypeStats(_Model):
    index: str
    sourcetype: str
    event_count: int
    latest_event: AwareDatetime | None = None
    window_earliest: str


class FieldStat(_Model):
    name: str
    count: int
    distinct_count: int | None = None


class FieldSummary(_Model):
    index: str
    sourcetype: str | None
    window_earliest: str
    event_count: int
    fields: tuple[FieldStat, ...] = ()

    def coverage(self, field: str) -> float:
        """Fraction of events in the window carrying ``field`` (0.0 when there are no events)."""
        if self.event_count == 0:
            return 0.0
        for f in self.fields:
            if f.name == field:
                return min(1.0, f.count / self.event_count)
        return 0.0


class SearchResult(_Model):
    spl: str
    earliest: str
    latest: str
    rows: tuple[dict[str, Any], ...] = ()
    truncated: bool = False
    scan_count: int | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


class SchedulerRun(_Model):
    rule_name: str
    scheduled_time: AwareDatetime
    status: str  # "success" | "skipped" | "failed" | "continued" (platform vocabulary, kept as-is)
    result_count: int | None = None
    message: str | None = None


# --------------------------------------------------------------------------- SPL analysis


class Threshold(_Model):
    """A numeric comparison found in a ``| where`` or ``| search`` clause, e.g. ``count > 3``."""

    field: str
    op: str
    value: float


class SplAnalysis(_Model):
    """Static facts extracted from a rule's SPL (see ``logops.spl``)."""

    indexes: tuple[str, ...] = ()
    sourcetypes: tuple[str, ...] = ()
    filter_fields: tuple[str, ...] = ()
    """Raw event fields the base search filters on (``action=failed_login`` gives ``action``)."""
    group_by_fields: tuple[str, ...] = ()
    """Fields named in ``by`` clauses."""
    aggregate_fields: tuple[str, ...] = ()
    """Raw fields consumed by aggregation functions (``dc(user)`` gives ``user``)."""
    derived_fields: tuple[str, ...] = ()
    """Fields created by the pipeline (``count``, ``eval x=``, ``as y``) and therefore not expected in raw events."""
    commands: tuple[str, ...] = ()
    thresholds: tuple[Threshold, ...] = ()
    unparsed: tuple[str, ...] = ()
    """Fragments the analyzer did not understand. Non-empty means the analysis is partial."""

    @property
    def required_event_fields(self) -> tuple[str, ...]:
        """Fields that must exist in raw events for the rule to evaluate correctly."""
        meta = {"index", "sourcetype", "source", "host", "_time", "_raw"}
        seen: dict[str, None] = {}
        for name in (*self.filter_fields, *self.group_by_fields, *self.aggregate_fields):
            if name not in meta and name not in self.derived_fields:
                seen.setdefault(name, None)
        return tuple(seen)


# --------------------------------------------------------------------------- audit output


class Evidence(_Model):
    """One observation collected from the platform, referenced by checks, findings and diagnoses."""

    id: str = Field(default_factory=lambda: new_id("ev"))
    kind: str
    op: str
    args: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    source: DataSource
    collected_at: AwareDatetime = Field(default_factory=utcnow)


class CheckResult(_Model):
    check_id: str
    outcome: CheckOutcome
    summary: str
    required: bool = True
    evidence_ids: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


class Finding(_Model):
    id: str = Field(default_factory=lambda: new_id("fd"))
    rule_id: str
    check_id: str
    category: str
    severity: Severity
    title: str
    detail: str
    dependency: str | None = None
    recommendation: str
    evidence_ids: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Diagnosis(_Model):
    """AI-produced explanation. Advisory only: it never changes a status."""

    summary: str
    likely_causes: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    cited_evidence_ids: tuple[str, ...] = ()
    provider: str
    model: str
    created_at: AwareDatetime = Field(default_factory=utcnow)


class RuleAudit(_Model):
    rule: SavedSearch
    analysis: SplAnalysis
    status: HealthStatus
    reason: str
    checks: tuple[CheckResult, ...] = ()
    findings: tuple[Finding, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    diagnosis: Diagnosis | None = None


class AuditReport(BaseModel):
    """One audit run. Counts are always derived from ``rules`` and never supplied by callers."""

    # extra="ignore" so a serialised report, which includes the computed counts, loads back cleanly.
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str = Field(default_factory=lambda: new_id("run"))
    created_at: AwareDatetime = Field(default_factory=utcnow)
    source: DataSource
    environment: str
    rules: tuple[RuleAudit, ...] = ()
    integration_error: str | None = None
    """Set when the audit could not even enumerate rules. The report is then empty, and never padded with fake rules."""
    thresholds: dict[str, Any] = Field(default_factory=dict)
    logops_version: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def counts(self) -> dict[str, int]:
        c = Counter(r.status for r in self.rules)
        return {s.value: c.get(s, 0) for s in HealthStatus}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_rules(self) -> int:
        return len(self.rules)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def finding_count(self) -> int:
        return sum(len(r.findings) for r in self.rules)

    @property
    def is_simulated(self) -> bool:
        return self.source is not DataSource.SPLUNK
