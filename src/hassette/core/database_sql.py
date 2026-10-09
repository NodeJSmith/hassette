"""Low-level SQL helpers shared by ``DatabaseService`` and its retention mixin."""

import logging
from typing import Protocol

import aiosqlite

SQL_BEGIN = "BEGIN"


class LoggerOwner(Protocol):
    """Anything exposing a ``logger`` -- the only attribute ``safe_rollback`` reads from its owner."""

    logger: logging.Logger


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
