import pytest
from pydantic import SecretStr, ValidationError

from logops.config import AuditThresholds, Settings
from logops.errors import ConfigError

SECRET = "super-secret-token-value-123456"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    """Never read the developer's real .env in tests."""
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    for key in list(__import__("os").environ):
        if key.startswith("LOGOPS_"):
            monkeypatch.delenv(key)


def test_defaults_are_offline_simulator() -> None:
    s = Settings()
    assert s.mode == "simulator"
    assert not s.ai_configured
    assert s.splunk_verify_tls is True


def test_secrets_never_appear_in_repr_or_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGOPS_SPLUNK_TOKEN", SECRET)
    monkeypatch.setenv("LOGOPS_GROQ_API_KEY", SECRET)
    s = Settings()
    assert SECRET not in repr(s)
    assert SECRET not in str(s.model_dump())
    assert SECRET not in s.model_dump_json()
    assert s.ai_configured


def test_require_splunk_reports_missing_vars() -> None:
    with pytest.raises(ConfigError, match="LOGOPS_SPLUNK_MCP_URL"):
        Settings().require_splunk()


def test_require_splunk_rejects_plain_http() -> None:
    s = Settings(splunk_mcp_url="http://x:8089/services/mcp", splunk_token=SecretStr("t"))
    with pytest.raises(ConfigError, match="https"):
        s.require_splunk()


def test_ai_can_be_disabled_even_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGOPS_GEMINI_API_KEY", SECRET)
    monkeypatch.setenv("LOGOPS_AI_ENABLED", "false")
    assert not Settings().ai_configured


def test_threshold_ordering_validated() -> None:
    with pytest.raises(ValidationError):
        AuditThresholds(freshness_warn_minutes=200, freshness_fail_minutes=100)
