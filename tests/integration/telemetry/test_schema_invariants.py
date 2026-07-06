"""Schema structural invariants — verified against the canonical migrated database."""

import inspect

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.repository import TelemetryRepository


async def test_on_conflict_target_matches_index(db: tuple[DatabaseService, int]) -> None:
    """idx_listeners_natural columns exactly match the ON CONFLICT target in register_listener().

    Queries sqlite_master for idx_listeners_natural and asserts:
    (a) its column list is exactly (app_key, instance_index, name, topic)
    (b) the repository's ON CONFLICT target is verbatim (app_key, instance_index, name, topic)
    """
    db_service, _ = db
    conn = db_service.db

    cursor = await conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_listeners_natural'")
    row = await cursor.fetchone()
    assert row is not None, "idx_listeners_natural index must exist in schema"

    index_sql: str = row[0]
    assert "app_key, instance_index, name, topic" in index_sql, (
        f"idx_listeners_natural must index (app_key, instance_index, name, topic), got: {index_sql!r}"
    )
    assert "COALESCE" not in index_sql, "idx_listeners_natural must not use COALESCE expression"
    assert "WHERE" not in index_sql, "idx_listeners_natural must not be a partial index"
    assert "handler_method" not in index_sql, "idx_listeners_natural must not include handler_method"

    source = inspect.getsource(TelemetryRepository.register_listener)
    assert "ON CONFLICT(app_key, instance_index, name, topic)" in source, (
        "register_listener() ON CONFLICT target must be (app_key, instance_index, name, topic) "
        "to match idx_listeners_natural"
    )
    assert "COALESCE" not in source or "ON CONFLICT" not in source.split("COALESCE")[0], (
        "register_listener() ON CONFLICT must not use COALESCE"
    )


async def test_unique_index_enforced(db: tuple[DatabaseService, int]) -> None:
    """Two listeners with the same natural key (app_key, instance_index, name, topic) raise IntegrityError."""
    db_service, _ = db
    conn = db_service.db

    sql = """
        INSERT INTO listeners
            (app_key, instance_index, name, handler_method, topic, once, priority, source_location)
        VALUES ('app', 0, 'app.handler', 'app.handler', 'light.on', 0, 0, 'app.py:1')
    """
    await conn.execute(sql)
    await conn.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(sql)


async def test_active_views_exist(db: tuple[DatabaseService, int]) -> None:
    """active_listeners and active_scheduled_jobs views are queryable on the canonical schema."""
    db_service, _ = db
    conn = db_service.db

    cursor = await conn.execute("SELECT * FROM active_listeners")
    rows = await cursor.fetchall()
    assert rows == []

    cursor = await conn.execute("SELECT * FROM active_scheduled_jobs")
    rows = await cursor.fetchall()
    assert rows == []
