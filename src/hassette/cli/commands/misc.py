"""Miscellaneous CLI commands: config, event."""

from typing import Any

import hassette.cli.globals as cli_globals
from hassette.cli.client import make_client
from hassette.cli.output import Column, fmt_relative_time, render_detail, render_table
from hassette.cli.types import LimitArg
from hassette.web.models import ConfigResponse, EventEntry


def cmd_config() -> None:
    """Show current configuration (GET /api/config)."""
    client = make_client()
    result = client.get("/api/config", ConfigResponse)
    render_detail(result, json_mode=cli_globals.json_mode)


EVENT_COLUMNS: list[Column] = [
    Column("type", "Event Type", max_width=30),
    Column("entity_id", "Entity", max_width=26),
    Column("timestamp", "When", max_width=11, formatter=fmt_relative_time),
]


def cmd_event(
    limit: LimitArg = None,
) -> None:
    """Show recent HA events (GET /api/events/recent)."""
    client = make_client()
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    result: list[EventEntry] = client.get("/api/events/recent", list, params=params)
    events = [EventEntry.model_validate(e) for e in result]
    render_table(events, EVENT_COLUMNS, json_mode=cli_globals.json_mode)  # pyright: ignore[reportArgumentType]
