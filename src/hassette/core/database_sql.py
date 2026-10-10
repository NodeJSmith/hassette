"""Low-level SQL helpers and cleanup-pass tracking shared by ``DatabaseService`` and its mixins."""

import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, TypeVar

import aiosqlite

SQL_BEGIN = "BEGIN"

CLEANUP_PROGRESS_LOG_INTERVAL = 10
"""Batches (retention) or iterations (size failsafe) between "in progress" log lines during a
long cleanup pass, so a pass that runs for minutes on a large backlog leaves a visible trail
instead of going silent until its final summary."""


class LoggerOwner(Protocol):
    """Anything exposing a ``logger`` -- the only attribute ``safe_rollback`` reads from its owner."""

    logger: logging.Logger


class CleanupOwner(Protocol):
    """Anything exposing ``_active_cleanup`` -- the only attribute ``tracks_active_cleanup`` writes."""

    _active_cleanup: str | None


_OwnerT = TypeVar("_OwnerT", bound=CleanupOwner)


def tracks_active_cleanup(
    label: str,
) -> Callable[[Callable[[_OwnerT], Coroutine[Any, Any, None]]], Callable[[_OwnerT], Coroutine[Any, Any, None]]]:
    """Record ``label`` on the owner's ``_active_cleanup`` while the decorated cleanup pass runs.

    A long cleanup pass occupies the single write worker, so queued heartbeat writes time out
    behind it. ``update_heartbeat()`` reads ``_active_cleanup`` to say which pass is holding
    the worker, instead of the timeout reading as an unexplained wedge.
    """

    def decorator(
        func: Callable[[_OwnerT], Coroutine[Any, Any, None]],
    ) -> Callable[[_OwnerT], Coroutine[Any, Any, None]]:
        @functools.wraps(func)
        async def wrapper(owner: _OwnerT) -> None:
            owner._active_cleanup = label
            try:
                await func(owner)
            finally:
                owner._active_cleanup = None

        return wrapper

    return decorator


async def safe_rollback(db: aiosqlite.Connection, owner: LoggerOwner, context: str) -> None:
    """Roll back a transaction, logging (not raising) if the rollback itself fails.

    Callers remain responsible for handling the original exception (re-raising, logging,
    etc.) after this returns -- this only guards the rollback attempt itself. ``owner.logger``
    is accessed only on the failure path, matching pre-extraction behavior where a caller whose
    rollback always succeeds never had to have a real logger configured.

    A failed rollback here leaves the shared write connection's transaction state unknown --
    the next queued write (heartbeat, another retention batch) executes against whatever was
    left behind, not a guaranteed-clean slate. The log message names that consequence rather
    than just the event.
    """
    try:
        await db.rollback()
    except Exception:
        owner.logger.exception("Rollback also failed for %s — write connection state is now unknown", context)
