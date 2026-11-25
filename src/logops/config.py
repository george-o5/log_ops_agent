"""Configuration.

Everything comes from environment variables prefixed ``LOGOPS_`` (or a local ``.env``). Secrets are ``SecretStr``,
so they never appear in ``repr()``, logs or tracebacks. Nothing here prints or validates token *contents*:
token length and format are the platform's business.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from logops.errors import ConfigError


class AuditThresholds(BaseModel):
    """Tunable limits used by checks. Recorded on every report so results stay explainable."""

    model_config = ConfigDict(frozen=True)

    freshness_warn_minutes: int = Field(default=30, gt=0)
    freshness_fail_minutes: int = Field(default=120, gt=0)
    volume_drop_warn_pct: float = Field(default=50.0, gt=0, le=100)
    field_min_coverage: float = Field(default=0.5, ge=0, le=1)
    data_window: str = "-24h"

    @model_validator(mode="after")
    def _ordered(self) -> AuditThresholds:
        if self.freshness_warn_minutes >= self.freshness_fail_minutes:
            raise ValueError("freshness_warn_minutes must be lower than freshness_fail_minutes")
        return self


IntegrationMode = Literal["simulator", "splunk"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOGOPS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mode: IntegrationMode = "simulator"
    db_path: Path = Path("logops.db")
    request_timeout_s: float = Field(default=30.0, gt=0, le=600)

    # Simulator
    sim_scenario: str = "legacy_demo"

    # Official Splunk MCP Server (Phase 9)
    splunk_mcp_url: str | None = None
    splunk_token: SecretStr | None = None
    splunk_verify_tls: bool = True

    # AI (optional)
    ai_enabled: bool = True
    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"

    # Optional HEC (synthetic data push)
    hec_url: str | None = None
    hec_token: SecretStr | None = None

    thresholds: AuditThresholds = AuditThresholds()

    @property
    def ai_configured(self) -> bool:
        return self.ai_enabled and bool(self.groq_api_key or self.gemini_api_key)

    def require_splunk(self) -> tuple[str, SecretStr]:
        """Return (url, token) for real Splunk mode, or raise a clear ConfigError."""
        missing = [
            n
            for n, v in (
                ("LOGOPS_SPLUNK_MCP_URL", self.splunk_mcp_url),
                ("LOGOPS_SPLUNK_TOKEN", self.splunk_token),
            )
            if not v
        ]
        if missing:
            raise ConfigError(f"Splunk mode requires: {', '.join(missing)}")
        assert self.splunk_mcp_url is not None and self.splunk_token is not None
        if not self.splunk_mcp_url.startswith("https://"):
            raise ConfigError("LOGOPS_SPLUNK_MCP_URL must use https://")
        return self.splunk_mcp_url, self.splunk_token
