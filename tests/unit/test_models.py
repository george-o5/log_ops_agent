from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from logops.models import (
    AuditReport,
    CheckOutcome,
    CheckResult,
    DataSource,
    Evidence,
    FieldStat,
    FieldSummary,
    Finding,
    HealthStatus,
    RuleAudit,
    SavedSearch,
    SearchResult,
    Severity,
    SplAnalysis,
)


def _rule_audit(status: HealthStatus, findings: int = 0) -> RuleAudit:
    rule = SavedSearch(id=f"r-{status}", name="Rule", search="index=main")
    ev = Evidence(kind="index_info", op="describe_index", args={"name": "main"}, source=DataSource.FIXTURE)
    return RuleAudit(
        rule=rule,
        analysis=SplAnalysis(indexes=("main",)),
        status=status,
        reason="test",
        checks=(
            CheckResult(
                check_id="index_exists", outcome=CheckOutcome.PASS, summary="ok", evidence_ids=(ev.id,)
            ),
        ),
        findings=tuple(
            Finding(
                rule_id=rule.id,
                check_id="index_exists",
                category="data_source",
                severity=Severity.HIGH,
                title="t",
                detail="d",
                recommendation="r",
                evidence_ids=(ev.id,),
            )
            for _ in range(findings)
        ),
        evidence=(ev,),
    )


def test_report_counts_are_derived_from_rules() -> None:
    report = AuditReport(
        source=DataSource.SIMULATOR,
        environment="legacy_demo",
        rules=(
            _rule_audit(HealthStatus.GREEN),
            _rule_audit(HealthStatus.AMBER, 1),
            _rule_audit(HealthStatus.RED, 2),
            _rule_audit(HealthStatus.RED),
        ),
    )
    assert report.counts == {"GREEN": 1, "AMBER": 1, "RED": 2, "UNKNOWN": 0}
    assert report.total_rules == 4
    assert report.finding_count == 3
    assert report.is_simulated


def test_report_json_round_trip() -> None:
    report = AuditReport(
        source=DataSource.SPLUNK, environment="prod", rules=(_rule_audit(HealthStatus.AMBER, 1),)
    )
    payload = report.model_dump_json()
    assert '"counts"' in payload
    loaded = AuditReport.model_validate_json(payload)
    assert loaded == report
    assert not loaded.is_simulated


def test_empty_report_with_integration_error() -> None:
    report = AuditReport(source=DataSource.SIMULATOR, environment="x", integration_error="connect: refused")
    assert report.total_rules == 0
    assert report.counts["UNKNOWN"] == 0


def test_models_are_frozen_and_strict() -> None:
    rule = SavedSearch(id="1", name="n", search="s")
    with pytest.raises(ValidationError):
        rule.name = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        SavedSearch(id="1", name="n", search="s", surprise=True)  # type: ignore[call-arg]


def test_datetimes_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        Evidence(kind="k", op="o", source=DataSource.FIXTURE, collected_at=datetime(2026, 1, 1))
    Evidence(kind="k", op="o", source=DataSource.FIXTURE, collected_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_field_coverage() -> None:
    fs = FieldSummary(
        index="main",
        sourcetype="security_logs",
        window_earliest="-24h",
        event_count=200,
        fields=(FieldStat(name="src_ip", count=150), FieldStat(name="user", count=200)),
    )
    assert fs.coverage("src_ip") == 0.75
    assert fs.coverage("user") == 1.0
    assert fs.coverage("missing") == 0.0
    empty = FieldSummary(index="main", sourcetype=None, window_earliest="-24h", event_count=0)
    assert empty.coverage("anything") == 0.0


def test_search_result_round_trip() -> None:
    r = SearchResult(spl="index=main", earliest="-1h", latest="now", rows=({"count": 3},))
    assert r.row_count == 1
    assert SearchResult.model_validate_json(r.model_dump_json()) == r


def test_finding_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        Finding(
            rule_id="r",
            check_id="c",
            category="x",
            severity=Severity.LOW,
            title="t",
            detail="d",
            recommendation="r",
            confidence=1.5,
        )
