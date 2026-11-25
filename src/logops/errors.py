"""Typed errors.

Two families, deliberately kept apart:

* ``IntegrationError``: we could not talk to the data platform (or it refused us). This says nothing
  about the rule being audited, so checks that hit it become ``ERROR`` and the rule ``UNKNOWN``.
* ``SearchError``: the platform was reachable and *rejected the SPL*. That is evidence about the rule.
"""

from __future__ import annotations


class LogOpsError(Exception):
    """Base class for all LogOps errors."""


class IntegrationError(LogOpsError):
    """The integration could not complete an operation."""

    kind: str = "integration"


class ConnectError(IntegrationError):
    kind = "connect"


class AuthError(IntegrationError):
    kind = "auth"


class IntegrationTimeout(IntegrationError):
    kind = "timeout"


class UnsupportedOperation(IntegrationError):
    """The backend cannot perform this operation (e.g. SPL outside the simulator subset)."""

    kind = "unsupported"


class BadResponse(IntegrationError):
    """The backend answered, but not in a shape we can validate."""

    kind = "bad_response"


class SearchError(LogOpsError):
    """The backend rejected or failed to execute a search (syntax or execution error)."""

    def __init__(self, message: str, *, spl: str | None = None) -> None:
        super().__init__(message)
        self.spl = spl


class ConfigError(LogOpsError):
    """Invalid or missing configuration."""
