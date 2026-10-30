"""Shared sqlite/aiosqlite helpers for migration, schema, telemetry, and disk-size tests.

Replaces the ``conn = sqlite3.connect(db_path); try: ...; finally: conn.close()``
boilerplate repeated across migration/schema test files, and the hand-typed
``INSERT INTO executions (...)`` column list repeated across migration, schema,
and telemetry repository tests.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiosqlite

SHRUNK_FRACTION = 0.1
"""A cleared 200-entry (~800 KB) cache must fall below this fraction of its prior size; an empty one is ~12 KB."""


@contextmanager
def sqlite_conn(db_path: Path, *, foreign_keys: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """Open a sync sqlite3 connection to ``db_path``, closing it on exit.

    Replaces the ``conn = sqlite3.connect(db_path); try: ...; finally: conn.close()``
    pattern repeated across migration/schema test files. Pass ``foreign_keys=True``
    to run ``PRAGMA foreign_keys = ON`` immediately after connecting — several tests
    need FK enforcement active before inserting rows that exercise FK CHECK behavior.
    """
    conn = sqlite3.connect(db_path)
    try:
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


def insert_execution_row(
    conn: "sqlite3.Connection | aiosqlite.Connection",
    *,
    kind: str = "handler",
    listener_id: int | None = None,
    job_id: int | None = None,
    session_id: int = 1,
    execution_start_ts: float = 1.0,
    duration_ms: float = 5.0,
    status: str = "success",
) -> Any:
    """Insert a row into the ``executions`` table for tests.

    ``source_tier`` is intentionally left out of the column list: the real schema
    defaults it to ``'app'`` (see ``001.sql``), and every pre-existing call site that
    specified it explicitly always passed that same default value, so omitting it and
    relying on the default is behaviorally identical — including for the ``telemetry_db``
    fixture (``tests/unit/core/conftest.py``), which is built from the full migrated
    schema via ``run_migrations()`` and so defaults ``source_tier`` the same way.

    Works with both a sync ``sqlite3.Connection`` (migration/schema tests — call
    plainly) and an async ``aiosqlite.Connection`` (the ``telemetry_db`` fixture —
    ``await`` the call). This just forwards to ``conn.execute()``, so which behavior
    you get follows whatever ``conn`` itself is.

    ``001.sql``'s ``CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)`` requires
    exactly one of the two to be set. When a caller passes neither, default the one matching
    ``kind`` (``job_id`` for ``kind="job"``, ``listener_id`` otherwise) to an arbitrary
    placeholder id — foreign key enforcement is off by default in these tests, so the
    placeholder need not reference a real row.
    """
    if listener_id is None and job_id is None:
        if kind == "job":
            job_id = 1
        else:
            listener_id = 1
    return conn.execute(
        "INSERT INTO executions (kind, listener_id, job_id, session_id, execution_start_ts, duration_ms, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, listener_id, job_id, session_id, execution_start_ts, duration_ms, status),
    )


async def count_rows(db: "aiosqlite.Connection", table: str, **filters: object) -> int:
    """Return the number of rows in ``table``, AND-ing an equality filter per keyword argument.

    A ``None`` filter value matches ``IS NULL``, since ``column = NULL`` never matches any row.
    Table and column names are interpolated, so pass only literals from test code, never user input.
    """
    sql = f"SELECT COUNT(*) FROM {table}"
    clauses = [f"{column} IS NULL" if value is None else f"{column} = ?" for column, value in filters.items()]
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    values = tuple(value for value in filters.values() if value is not None)
    cursor = await db.execute(sql, values)
    row = await cursor.fetchone()
    assert row is not None
    return row[0]


def sqlite_disk_bytes(db_path: Path) -> int:
    """Size in bytes of a SQLite database file plus its WAL and SHM sidecars, whichever exist.

    The sum is what a reclaim or ``VACUUM`` has to shrink: the main file alone can look unchanged
    while the freed pages still sit in the WAL.
    """
    sidecars = (Path(f"{db_path}{suffix}") for suffix in ("", "-wal", "-shm"))
    return sum(path.stat().st_size for path in sidecars if path.exists())
