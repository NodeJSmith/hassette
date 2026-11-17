"""Rows of the ``lifecycle_events`` table: the per-kind details models and the functions owners call to write one.

Three owners write rows, each at the moment its state changes: ``AppInstanceLifecycleMixin.set_app_status`` (app
status), ``WebsocketService.set_connection_state`` (connection state) and ``reconcile_blocked_apps`` (block state).
Each calls one ``record_*`` function here, which hands a builder for the row to ``SessionManager.write_lifecycle_row``.

Writing is best-effort and never raises into the owner (design/specs/152-lifecycle-history-writers, Posture): a row
that can't be built or queued is counted under ``PipelineCounter.LIFECYCLE_ROWS_DROPPED`` and logged, and the
owner's transition goes ahead regardless.

The details models are the only place the ``details`` JSON keys are defined. They change only by adding optional
fields, so readers tolerate a missing key and rows carry no version.
"""

import logging
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from hassette.core.pipeline_counters import PipelineCounter
from hassette.types.enums import BlockReason, ConnectionState

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.app_registry import StatusChange

LOGGER = logging.getLogger(__name__)

LifecycleKind = Literal["app", "connection", "block"]
"""The ``kind`` column, one per row source; ``026.sql`` constrains it to these."""

BlockStatus = Literal["blocked", "unblocked", "removed"]
"""A block row's ``to_status``. ``removed`` closes a block whose app left the enabled config."""


class AppDetails(BaseModel):
    """``details`` of an app status row."""

    model_config = ConfigDict(frozen=True)

    exception_type: str | None = None
    """The failure's exception class name, on FAILED rows."""
    needs_restart_reason: str | None = None
    """Why the instance needs a Hassette restart, when the change carries the needs-restart flag."""
    pending_tasks: tuple[str, ...] | None = None
    """Tasks still pending when the flagged teardown ended, alongside ``needs_restart_reason``."""


class ConnectionDetails(BaseModel):
    """``details`` of a connection row. Each field is set only at the call site that knows it."""

    model_config = ConfigDict(frozen=True)

    cause: str | None = None
    """A human-readable description of why the connection failed, the same text the reconnect log uses: on
    CONNECTING after a failure, and on AUTH_FAILED. For display, not parsing."""
    core_state: str | None = None
    """Home Assistant's core state, on WAITING_FOR_CORE."""
    close_code: int | None = None
    """The socket's close code, on DISCONNECTED after the receive task died."""


class BlockDetails(BaseModel):
    """``details`` of a block row."""

    model_config = ConfigDict(frozen=True)

    reason: BlockReason


LifecycleDetails = AppDetails | ConnectionDetails | BlockDetails


def serialize_details(details: LifecycleDetails) -> str:
    """The ``details`` column's JSON: unset fields are left out, so readers treat a missing key as unset."""
    return details.model_dump_json(exclude_none=True)


@dataclass(frozen=True, slots=True)
class LifecycleChange:
    """What an owner reports about one change: every ``lifecycle_events`` column but the id, session and time.

    ``SessionManager.write_lifecycle_row`` adds the session id and time, and serializes ``details``.
    """

    kind: LifecycleKind
    to_status: str
    from_status: str | None
    details: LifecycleDetails
    app_key: str | None = None
    instance_name: str | None = None


def record_app_change(hassette: "Hassette", change: "StatusChange") -> None:
    """Record an app instance status change as ``AppRegistry.set_status`` applied it."""
    record_lifecycle_change(hassette, lambda: app_change(change))


def record_connection_change(
    hassette: "Hassette", old: ConnectionState, new: ConnectionState, detail: ConnectionDetails | None
) -> None:
    """Record a ``ConnectionState`` transition, with whatever detail the call site that caused it knows."""
    record_lifecycle_change(
        hassette,
        lambda: LifecycleChange(
            kind="connection", from_status=old, to_status=new, details=detail or ConnectionDetails()
        ),
    )


def record_block_change(hassette: "Hassette", app_key: str, to_status: BlockStatus, reason: BlockReason) -> None:
    """Record an app entering or leaving the blocked set."""
    record_lifecycle_change(
        hassette,
        lambda: LifecycleChange(
            kind="block", app_key=app_key, from_status=None, to_status=to_status, details=BlockDetails(reason=reason)
        ),
    )


def app_change(change: "StatusChange") -> LifecycleChange:
    """Build an app row's change from a ``StatusChange``."""
    flag = change.needs_restart
    details = AppDetails(
        exception_type=type(change.error).__name__ if change.error is not None else None,
        needs_restart_reason=flag.reason if flag is not None else None,
        pending_tasks=flag.pending_tasks if flag is not None else None,
    )
    return LifecycleChange(
        kind="app",
        app_key=change.app_key,
        instance_name=change.instance_name,
        from_status=change.previous,
        to_status=change.status,
        details=details,
    )


def record_lifecycle_change(hassette: "Hassette", build: Callable[[], LifecycleChange]) -> None:
    """Hand ``build`` to the session manager's writer, which builds and queues the row; never raises.

    The writer counts and warns about every row it drops, a failed build included. The one drop it can't see is
    a Hassette with no session manager wired (``hassette.session_manager`` raises), which happens only in tests
    and harnesses: that drop is counted here and logged at DEBUG, since there is no writer holding pacing state.
    """
    try:
        session_manager = hassette.session_manager
    except Exception:
        session_manager = None
    if session_manager is None:
        hassette.pipeline_counters.increment(PipelineCounter.LIFECYCLE_ROWS_DROPPED)
        LOGGER.debug("No session manager wired; dropping lifecycle row")
        return
    session_manager.write_lifecycle_row(build)
