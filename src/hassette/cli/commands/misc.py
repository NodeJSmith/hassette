"""Miscellaneous CLI commands: config, event."""

from typing import Annotated, Any

from cyclopts import Parameter

from hassette.cli.client import make_client
from hassette.cli.context import CLIContext
from hassette.cli.output import Column, fmt_relative_time, render_detail, render_table
from hassette.cli.types import LimitArg
from hassette.web.models import ConfigResponse, EventEntry


def cmd_config(*, ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()) -> None:  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
    """Show current configuration (GET /api/config)."""
    client = make_client(ctx)
    result = client.get("/api/config", ConfigResponse)
    render_detail(result, json_mode=ctx.json_mode)


EVENT_COLUMNS: list[Column] = [
    Column("type", "Event Type", max_width=30),
    Column("entity_id", "Entity", max_width=26),
    Column("timestamp", "When", max_width=11, formatter=fmt_relative_time),
]


def cmd_event(
    limit: LimitArg = None,
    *,
    ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext(),  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
) -> None:
    """Show recent HA events (GET /api/events/recent)."""
    client = make_client(ctx)
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    result: list[EventEntry] = client.get("/api/events/recent", list, params=params)
    events = [EventEntry.model_validate(e) for e in result]
    render_table(events, EVENT_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
