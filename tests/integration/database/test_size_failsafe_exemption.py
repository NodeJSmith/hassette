"""The size failsafe's ``failsafe_exempt`` carve-out, against a real SQLite database."""

import time

from hassette.core.database_service import DatabaseService
from tests.support.helpers import SIZE_FAILSAFE_TRIGGER_MB, seed_listener_for_fk


async def test_size_failsafe_leaves_log_records_untouched(initialized_service: DatabaseService) -> None:
    """log_records is exempt from the size failsafe: it drains executions and blocking_events
    down to nothing while the DB is over the limit, but never deletes a log record.
    """
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    await seed_listener_for_fk(db)

    now = time.time()
    for i in range(10):
        ts = now - (100 - i)
        await db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status,"
            " source_tier) VALUES ('handler', 1, ?, ?, 10.0, 'success', ?)",
            (session_id, ts, "framework" if i % 2 else "app"),
        )
        await db.execute(
            "INSERT INTO blocking_events (session_id, tier, detected_ts, source_tier)"
            " VALUES (?, 'monkeypatch', ?, 'app')",
            (session_id, ts),
        )
        # Deliberately the oldest rows in the database — an unexempt failsafe would delete
        # these first within their own tier, so surviving is not an artifact of recency.
        await db.execute(
            "INSERT INTO log_records (seq, timestamp, level, logger_name, message)"
            " VALUES (?, ?, 'INFO', 'test', 'hello')",
            (i, ts - 1000),
        )
    await db.commit()

    initialized_service.hassette.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    # Every failsafe-managed tier drained (the DB stays over this tiny limit regardless).
    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    assert (await cursor.fetchone())[0] == 0  # pyright: ignore[reportOptionalSubscript]
    cursor = await db.execute("SELECT COUNT(*) FROM blocking_events")
    assert (await cursor.fetchone())[0] == 0  # pyright: ignore[reportOptionalSubscript]
    # ...but the exempt table is fully intact.
    cursor = await db.execute("SELECT COUNT(*) FROM log_records")
    assert (await cursor.fetchone())[0] == 10  # pyright: ignore[reportOptionalSubscript]
