"""SQL helpers shared by ``DatabaseService`` and its retention and size-failsafe mixins."""

import logging
import time
from dataclasses import dataclass
from typing import Protocol

import aiosqlite

SQL_BEGIN = "BEGIN"

CLEANUP_PROGRESS_LOG_INTERVAL = 10
"""Batches (retention) or iterations (size failsafe) between "in progress" log lines during a
long cleanup pass, so a pass that runs for minutes on a large backlog leaves a visible trail
instead of going silent until its final summary."""

FREE_PAGE_RECLAIM_CHUNK_PAGES = 2000
"""Pages ``reclaim_free_pages()`` frees per ``PRAGMA incremental_vacuum`` statement, so the free
list is drained in bounded steps rather than one statement that runs for as long as it takes."""

FREE_PAGE_RECLAIM_BUDGET_SECONDS = 20.0
"""Wall-clock budget for one ``reclaim_free_pages()`` call. A free list of hundreds of MiB takes
tens of seconds to reclaim while every other queued write waits; capping the call keeps that
wait well inside ``write_submit_timeout_seconds``, and the next cycle continues where it stopped."""


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


@dataclass(frozen=True, slots=True)
class FreePageReclaim:
    """Outcome of ``reclaim_free_pages()``."""

    reclaimed: int
    """Pages removed from the database's free list. The file only shrinks once the WAL is checkpointed."""

    remaining: int
    """Free pages still in the database afterward."""

    budget_exhausted: bool
    """The time budget ran out while reclaimable free pages remained."""


async def read_int_pragma(db: aiosqlite.Connection, pragma: str) -> int:
    """Return the integer value of a read-only pragma such as ``freelist_count`` or ``page_size``."""
    cursor = await db.execute(f"PRAGMA {pragma}")
    row = await cursor.fetchone()
    await cursor.close()
    return row[0] if row else 0


async def get_freelist_count(db: aiosqlite.Connection) -> int:
    """Return the number of unused pages in the database file."""
    return await read_int_pragma(db, "freelist_count")


async def get_live_data_mb(db: aiosqlite.Connection) -> float:
    """Return the size of the database's in-use pages in megabytes -- what deleting rows can shrink.

    Unlike the on-disk size, this excludes free pages and the WAL file, and it reads the same
    whether or not the WAL has been checkpointed.
    """
    page_count = await read_int_pragma(db, "page_count")
    free = await get_freelist_count(db)
    page_size = await read_int_pragma(db, "page_size")
    return (page_count - free) * page_size / (1024 * 1024)


async def run_incremental_vacuum(db: aiosqlite.Connection, pages: int | None = None) -> None:
    """Run ``PRAGMA incremental_vacuum``, freeing up to ``pages`` pages (all of them when None).

    The pragma frees one page per statement step, so ``execute()`` alone frees a single page, and
    Python 3.11's ``sqlite3`` resets the statement after one step because it returns no columns, so
    fetching the result doesn't help there. ``executescript()`` steps it to completion on every
    supported Python. It commits any open transaction first; every caller runs it outside one.
    """
    sql = "PRAGMA incremental_vacuum" if pages is None else f"PRAGMA incremental_vacuum({pages})"
    await db.executescript(sql)


async def reclaim_free_pages(db: aiosqlite.Connection) -> FreePageReclaim:
    """Drain the free list in ``FREE_PAGE_RECLAIM_CHUNK_PAGES`` chunks until empty or out of time.

    Stops early, with ``budget_exhausted`` False, when a chunk frees nothing -- the database is
    not in ``auto_vacuum = INCREMENTAL`` mode, so its free pages can't be reclaimed this way.
    Does not checkpoint; the main file only shrinks once the WAL is checkpointed.
    """
    deadline = time.monotonic() + FREE_PAGE_RECLAIM_BUDGET_SECONDS
    start = remaining = await get_freelist_count(db)
    while remaining > 0:
        await run_incremental_vacuum(db, min(remaining, FREE_PAGE_RECLAIM_CHUNK_PAGES))
        after = await get_freelist_count(db)
        if after >= remaining:  # nothing freed: auto_vacuum isn't INCREMENTAL
            return FreePageReclaim(start - after, after, budget_exhausted=False)
        remaining = after
        if remaining > 0 and time.monotonic() >= deadline:
            return FreePageReclaim(start - remaining, remaining, budget_exhausted=True)
    return FreePageReclaim(start - remaining, remaining, budget_exhausted=False)
