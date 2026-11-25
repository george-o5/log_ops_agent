"""``logops`` command-line entry point. Later phases add sub-commands (audit, sim, history)."""

from __future__ import annotations

import json

import typer

from logops import __version__
from logops.config import Settings
from logops.spl import analyze

app = typer.Typer(no_args_is_help=True, add_completion=False, help="LogOps: detection rule health auditing.")


@app.command()
def version() -> None:
    """Print the LogOps version."""
    typer.echo(__version__)


@app.command()
def config() -> None:
    """Show the effective configuration. Secrets are reported only as set or unset."""
    s = Settings()
    shown = s.model_dump(mode="json", exclude={"splunk_token", "groq_api_key", "gemini_api_key", "hec_token"})
    shown["secrets"] = {
        "splunk_token": s.splunk_token is not None,
        "groq_api_key": s.groq_api_key is not None,
        "gemini_api_key": s.gemini_api_key is not None,
        "hec_token": s.hec_token is not None,
    }
    typer.echo(json.dumps(shown, indent=2))


@app.command("analyze-spl")
def analyze_spl(spl: str) -> None:
    """Show the dependencies LogOps extracts from an SPL query."""
    result = analyze(spl)
    typer.echo(result.model_dump_json(indent=2))
    typer.echo(f"required_event_fields: {list(result.required_event_fields)}")


if __name__ == "__main__":
    app()
