"""Miscellaneous CLI commands: config."""

from hassette_wire import ConfigSchemaResponse

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import render_detail_dict


def cmd_config(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show current configuration (GET /api/config)."""
    client = make_client(ctx)
    result = client.get("/api/config", ConfigSchemaResponse)
    defaults = result.config_defaults
    # A field with no schema default is absent from defaults, so a None value must not match via .get().
    default_keys = {key for key, value in result.config_values.items() if key in defaults and defaults[key] == value}
    render_detail_dict(result.config_values, "Config", json_mode=ctx.json_mode, default_keys=default_keys)
