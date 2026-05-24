"""Miscellaneous CLI commands: config, service, event."""

from typing import Any

from hassette.cli.client import HassetteCLIClient
from hassette.cli.output import Column, fmt_relative_time, render_detail, render_raw, render_table
from hassette.cli.types import JsonArg, LimitArg
from hassette.config.config import HassetteConfig
from hassette.web.models import ConfigResponse, EventEntry

# ---------------------------------------------------------------------------
# hassette config
# ---------------------------------------------------------------------------


def cmd_config(
    json: JsonArg = False,
) -> None:
    """Show current configuration (GET /api/config)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)
    result = client.get("/api/config", ConfigResponse)
    render_detail(result, json_mode=json)


# ---------------------------------------------------------------------------
# hassette service
# ---------------------------------------------------------------------------


def cmd_service(
    json: JsonArg = False,
) -> None:
    """List available HA services (GET /api/services)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)
    result: dict[str, Any] = client.get("/api/services", dict)
    render_raw(result, json_mode=json)


# ---------------------------------------------------------------------------
# hassette event
# ---------------------------------------------------------------------------

EVENT_COLUMNS: list[Column] = [
    Column("type", "Event Type", max_width=30),
    Column("entity_id", "Entity", max_width=26),
    Column("timestamp", "When", max_width=11, formatter=fmt_relative_time),
]


def cmd_event(
    limit: LimitArg = None,
    json: JsonArg = False,
) -> None:
    """Show recent HA events (GET /api/events/recent)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    result: list[EventEntry] = client.get("/api/events/recent", list, params=params or None)
    events = [EventEntry.model_validate(e) for e in result]
    render_table(events, EVENT_COLUMNS, json_mode=json)  # pyright: ignore[reportArgumentType]
