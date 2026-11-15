"""Seed helpers for ``lifecycle_events`` rows: connection, app status and block changes.

Each per-kind helper returns its steps without inserting. ``seed_session_lifecycle`` merges a session's steps,
checks them against the session's bounds and inserts them in time order, so ids (the authoritative in-session
order, see migrations_sql/026.sql) agree with timestamps. ``details`` is serialized with the writer's
``serialize_details``.

Unlike the other seed modules' helpers, which insert at once, these build steps first: a session's rows from
several kinds can only get ids in time order once all of them are known.
"""

from dataclasses import dataclass

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
DEFAULT_FAILURE_OFFSET_SECONDS = 60.0


@dataclass(frozen=True)
class LifecycleStep:
    """One pending lifecycle_events row, positioned by its absolute timestamp ``at``."""

    at: float
    kind: str
    to_status: str
    details: LifecycleDetails
    from_status: str | None = None
    app_key: str | None = None
    instance_name: str | None = None


def seed_session_lifecycle(ctx: SeedContext, *, session_id: int, steps: list[LifecycleStep]) -> None:
    """Insert one session's lifecycle steps in timestamp order.

    Raises:
        ValueError: A step falls before the session's ``started_at`` or after its ``stopped_at``.
    """
    started_at, stopped_at = ctx.session_bounds(session_id)
    # Fails fast at the step that breaks the bounds; tests/integration/test_seed_db.py checks the same invariant
    # on the seeded database, including rows written without this helper.
    for step in steps:
        if step.at < started_at or (stopped_at is not None and step.at > stopped_at):
            raise ValueError(
                f"lifecycle step {step.kind}->{step.to_status} at {step.at} is outside session {session_id} "
                f"bounds [{started_at}, {stopped_at}]"
            )
    for step in sorted(steps, key=lambda step: step.at):
        params = {
            "session_id": session_id,
            "kind": step.kind,
            "app_key": step.app_key,
            "instance_name": step.instance_name,
            "from_status": step.from_status,
            "to_status": step.to_status,
            "details": serialize_details(step.details),
            "ts": step.at,
        }
        insert_row(ctx.cursor, LIFECYCLE_EVENT_INSERT_SQL, params)


def connection_lifecycle_steps(base_offset: float, ha_restart_offset: float | None = None) -> list[LifecycleStep]:
    """Build a session's connection rows: a healthy start, plus an HA restart ``ha_restart_offset`` seconds after
    ``base_offset`` that drops the socket and waits on the core before reconnecting.
    """
    steps: list[tuple[float, ConnectionState, ConnectionState, ConnectionDetails]] = [
        (0.5, ConnectionState.DISCONNECTED, ConnectionState.CONNECTING, ConnectionDetails()),
        (1.0, ConnectionState.CONNECTING, ConnectionState.CONNECTED, ConnectionDetails()),
    ]
    if ha_restart_offset is not None:
        steps += [
            (
                ha_restart_offset,
                ConnectionState.CONNECTED,
                ConnectionState.DISCONNECTED,
                ConnectionDetails(close_code=1006),
            ),
            (
                ha_restart_offset + 0.1,
                ConnectionState.DISCONNECTED,
                ConnectionState.CONNECTING,
                ConnectionDetails(cause="WebsocketClosedError (close code 1006): Home Assistant closed the connection"),
            ),
            (
                ha_restart_offset + 20.0,
                ConnectionState.CONNECTING,
                ConnectionState.WAITING_FOR_CORE,
                ConnectionDetails(core_state="NOT_RUNNING"),
            ),
            (
                ha_restart_offset + 45.0,
                ConnectionState.WAITING_FOR_CORE,
                ConnectionState.CONNECTED,
                ConnectionDetails(),
            ),
        ]
    return [
        LifecycleStep(
            at=ts(base_offset + offset),
            kind="connection",
            from_status=old,
            to_status=new,
            details=details,
        )
        for offset, old, new, details in steps
    ]


def app_lifecycle_steps(
    *,
    app_key: str,
    instance_name: str,
    base_offset: float,
    failure: str | None = None,
    failure_offset: float = DEFAULT_FAILURE_OFFSET_SECONDS,
) -> list[LifecycleStep]:
    """Build an app instance's status steps at session start: NOT_STARTED -> STARTING -> RUNNING, then FAILED
    with ``failure`` as the exception type ``failure_offset`` seconds after ``base_offset`` when one is given.
    """
    steps: list[tuple[float, ResourceStatus, ResourceStatus, AppDetails]] = [
        (2.0, ResourceStatus.NOT_STARTED, ResourceStatus.STARTING, AppDetails()),
        (2.5, ResourceStatus.STARTING, ResourceStatus.RUNNING, AppDetails()),
    ]
    if failure is not None:
        steps.append(
            (failure_offset, ResourceStatus.RUNNING, ResourceStatus.FAILED, AppDetails(exception_type=failure))
        )
    return [
        LifecycleStep(
            at=ts(base_offset + offset),
            kind="app",
            app_key=app_key,
            instance_name=instance_name,
            from_status=old,
            to_status=new,
            details=details,
        )
        for offset, old, new, details in steps
    ]


def block_change_step(*, app_key: str, to_status: BlockStatus, at_offset: float) -> LifecycleStep:
    """Build one block step for an app excluded by ``run --app``."""
    return LifecycleStep(
        at=ts(at_offset),
        kind="block",
        app_key=app_key,
        to_status=to_status,
        details=BlockDetails(reason=BlockReason.ONLY_APP),
    )
