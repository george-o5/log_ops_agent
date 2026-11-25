"""Gateway profiles: map each gateway op to an MCP tool plus small argument and result adapters.

``sim.toml`` targets the LogOps simulator. ``splunk.toml`` is a template filled from live discovery in Phase 9.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from logops.errors import ConfigError
from logops.gateway.base import GATEWAY_OPS
from logops.models import DataSource

PROFILE_DIR = Path(__file__).parent

ErrorClass = Literal["connect", "auth", "timeout", "unsupported", "bad_response", "search"]

_PLACEHOLDER = re.compile(r"^\{([A-Za-z_]\w*)\}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OpBinding(_Frozen):
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    result_key: str | None = None

    def render_args(self, params: dict[str, Any]) -> dict[str, Any]:
        """``"{param}"`` passes ``params[param]`` through unchanged (keeping its type); anything else is literal."""
        out: dict[str, Any] = {}
        for name, template in self.args.items():
            m = _PLACEHOLDER.match(template) if isinstance(template, str) else None
            if m is None:
                out[name] = template
                continue
            key = m.group(1)
            if key not in params:
                raise ConfigError(f"profile arg {name!r} references unknown parameter {key!r}")
            out[name] = params[key]
        return out


class ErrorMapping(_Frozen):
    kind_path: str | None = None
    message_path: str | None = None
    kinds: dict[str, ErrorClass] = Field(default_factory=dict)
    default: ErrorClass = "bad_response"


class ProfileMeta(_Frozen):
    name: str
    source: DataSource
    timeout_s: float = Field(default=30.0, gt=0, le=600)
    require_simulated_flag: bool = False


class Profile(_Frozen):
    profile: ProfileMeta
    errors: ErrorMapping = ErrorMapping()
    ops: dict[str, OpBinding] = Field(default_factory=dict)

    @field_validator("ops")
    @classmethod
    def _known_ops(cls, v: dict[str, OpBinding]) -> dict[str, OpBinding]:
        unknown = sorted(set(v) - set(GATEWAY_OPS))
        if unknown:
            raise ValueError(f"unknown gateway ops in profile: {unknown}")
        return v

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def source(self) -> DataSource:
        return self.profile.source


def load_profile(name_or_path: str | Path) -> Profile:
    """Load ``profiles/<name>.toml`` (or a path to a TOML file) and validate it."""
    path = Path(name_or_path)
    if path.suffix != ".toml":
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", str(name_or_path)):
            raise ConfigError(f"invalid profile name {name_or_path!r}")
        path = PROFILE_DIR / f"{name_or_path}.toml"
    if not path.is_file():
        raise ConfigError(f"gateway profile not found: {path.name}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"gateway profile {path.name} is not valid TOML: {exc}") from exc
    if "profile" not in data:
        raise ConfigError(
            f"gateway profile {path.name} is an unfilled template (Splunk profiles are written from live "
            "discovery in Phase 9)"
        )
    try:
        return Profile.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"gateway profile {path.name} is invalid: {exc}") from exc


__all__ = ["ErrorClass", "ErrorMapping", "OpBinding", "Profile", "ProfileMeta", "load_profile"]
