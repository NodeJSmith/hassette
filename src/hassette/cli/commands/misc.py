"""Miscellaneous CLI commands: config."""

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import render_detail_dict
from hassette.web.models import ConfigSchemaResponse


def cmd_config(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show current configuration (GET /api/config)."""
    client = make_client(ctx)
    result = client.get("/api/config", ConfigSchemaResponse)
    render_detail_dict(result.config_values, "Config", json_mode=ctx.json_mode)
