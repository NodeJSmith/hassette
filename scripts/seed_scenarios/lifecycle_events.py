"""Seed helpers for ``lifecycle_events`` rows: connection, app status and block changes.

``add_lifecycle_event`` serializes ``details`` with the writer's ``serialize_details``.
"""

from hassette.core.telemetry.lifecycle_rows import (
    AppDetails,
    BlockDetails,
    BlockStatus,
    ConnectionDetails,
    LifecycleDetails,
    serialize_details,
)
from hassette.types.enums import BlockReason, ConnectionState, ResourceStatus
from seed_scenarios.base import SeedContext, build_insert_sql, insert_row, ts

# lifecycle_events table columns (see migrations_sql/026.sql), excluding the autoincrement id.
LIFECYCLE_EVENT_COLUMNS = (
    "session_id",
    "kind",
    "app_key",
    "instance_name",
    "from_status",
    "to_status",
    "details",
    "ts",
)
LIFECYCLE_EVENT_INSERT_SQL = build_insert_sql("lifecycle_events", LIFECYCLE_EVENT_COLUMNS)


def add_lifecycle_event(
    ctx: SeedContext,
    *,
    session_id: int,
    kind: str,
    to_status: str,
    details: LifecycleDetails,
    at: float,
    from_status: str | None = None,
    app_key: str | None = None,
    instance_name: str | None = None,
) -> None:
    """Insert a lifecycle_events row."""
    params = {
        "session_id": session_id,
        "kind": kind,
        "app_key": app_key,
        "instance_name": instance_name,
        "from_status": from_status,
        "to_status": to_status,
        "details": serialize_details(details),
        "ts": at,
    }
    insert_row(ctx.cursor, LIFECYCLE_EVENT_INSERT_SQL, params)


def seed_connection_lifecycle(
    ctx: SeedContext, *, session_id: int, base_offset: float, ha_restart_at: float | None = None
) -> None:
    """Seed a session's connection rows: a healthy start, plus an HA restart ``ha_restart_at`` seconds after
    ``base_offset`` that drops the socket and waits on the core before reconnecting.
    """
    steps: list[tuple[float, ConnectionState, ConnectionState, ConnectionDetails]] = [
        (0.5, ConnectionState.DISCONNECTED, ConnectionState.CONNECTING, ConnectionDetails()),
        (1.0, ConnectionState.CONNECTING, ConnectionState.CONNECTED, ConnectionDetails()),
    ]
    if ha_restart_at is not None:
        steps += [
            (
                ha_restart_at,
                ConnectionState.CONNECTED,
                ConnectionState.DISCONNECTED,
                ConnectionDetails(close_code=1006),
            ),
            (
                ha_restart_at + 0.1,
                ConnectionState.DISCONNECTED,
                ConnectionState.CONNECTING,
                ConnectionDetails(cause="WebsocketClosedError (close code 1006): Home Assistant closed the connection"),
            ),
            (
                ha_restart_at + 20.0,
                ConnectionState.CONNECTING,
                ConnectionState.WAITING_FOR_CORE,
                ConnectionDetails(core_state="NOT_RUNNING"),
            ),
            (ha_restart_at + 45.0, ConnectionState.WAITING_FOR_CORE, ConnectionState.CONNECTED, ConnectionDetails()),
        ]
    for offset, old, new, details in steps:
        add_lifecycle_event(
            ctx,
            session_id=session_id,
            kind="connection",
            from_status=old,
            to_status=new,
            details=details,
            at=ts(base_offset + offset),
        )


def seed_app_lifecycle(
    ctx: SeedContext,
    *,
    session_id: int,
    app_key: str,
    instance_name: str,
    base_offset: float,
    failure: str | None = None,
) -> None:
    """Seed an app instance's status rows at session start: NOT_STARTED -> STARTING -> RUNNING, then FAILED
    with ``failure`` as the exception type when one is given.
    """
    steps: list[tuple[float, ResourceStatus, ResourceStatus, AppDetails]] = [
        (2.0, ResourceStatus.NOT_STARTED, ResourceStatus.STARTING, AppDetails()),
        (2.5, ResourceStatus.STARTING, ResourceStatus.RUNNING, AppDetails()),
    ]
    if failure is not None:
        steps.append((60.0, ResourceStatus.RUNNING, ResourceStatus.FAILED, AppDetails(exception_type=failure)))
    for offset, old, new, details in steps:
        add_lifecycle_event(
            ctx,
            session_id=session_id,
            kind="app",
            app_key=app_key,
            instance_name=instance_name,
            from_status=old,
            to_status=new,
            details=details,
            at=ts(base_offset + offset),
        )


def seed_block_change(
    ctx: SeedContext, *, session_id: int, app_key: str, to_status: BlockStatus, at_offset: float
) -> None:
    """Seed one block row for an app excluded by ``run --app``."""
    add_lifecycle_event(
        ctx,
        session_id=session_id,
        kind="block",
        app_key=app_key,
        to_status=to_status,
        details=BlockDetails(reason=BlockReason.ONLY_APP),
        at=ts(at_offset),
    )
