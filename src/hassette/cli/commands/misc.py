"""Miscellaneous CLI commands: config, event."""

from typing import Any

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_relative_time, render_detail_dict, render_table
from hassette.cli.types import LimitArg
from hassette.web.models import ConfigSchemaResponse, EventEntry


def cmd_config(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show current configuration (GET /api/config)."""
    client = make_client(ctx)
    result = client.get("/api/config", ConfigSchemaResponse)
    render_detail_dict(result.config_values, "Config", json_mode=ctx.json_mode)


EVENT_COLUMNS: list[Column] = [
    Column("type", "Event Type", max_width=30),
    Column("entity_id", "Entity", max_width=26),
    Column("timestamp", "When", max_width=11, formatter=fmt_relative_time),
]


def cmd_event(
    limit: LimitArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show recent HA events (GET /api/events/recent)."""
    client = make_client(ctx)
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    result: list[EventEntry] = client.get("/api/events/recent", list, params=params)
    events = [EventEntry.model_validate(e) for e in result]
    render_table(events, EVENT_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
