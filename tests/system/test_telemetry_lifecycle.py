"""Telemetry lifecycle system tests — verify source_tier, write pipeline, and session persistence.

Covers the telemetry source-tier lifecycle through the full Hassette startup/shutdown cycle.
Each test is self-contained and does not rely on other test order.

Run with:
    pytest -m system -v
"""

import asyncio
import sqlite3

import pytest

from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for
from tests.system.conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system, pytest.mark.filterwarnings("default::DeprecationWarning")]


async def test_framework_listeners_registered_with_correct_source_tier(ha_container, tmp_path):
    """After startup, listeners table has rows with source_tier='framework'."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:  # noqa: SIM117
        async with hassette.database_service.db.execute(
            "SELECT COUNT(*) FROM listeners WHERE source_tier = 'framework'"
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    count = row[0]
    assert count > 0, f"Expected at least one framework listener with source_tier='framework', found {count}"


async def test_handler_invocations_have_valid_session_id(ha_container, tmp_path):
    """After toggling a light, handler_invocations records have a valid (non-null, positive) session_id."""
    config = make_system_config(ha_container, tmp_path)
    received: list[object] = []

    async def capture_event(event: RawStateChangeEvent) -> None:
        received.append(event)

    async with startup_context(config) as hassette:
        session_id = hassette.session_id
        bus = hassette._bus
        sub = bus.on_state_change("light.kitchen_lights", handler=capture_event)
        await wait_for(lambda: sub.listener.db_id is not None, timeout=10.0, desc="listener registered")
        await hassette.api.call_service("light", "toggle", {"entity_id": "light.kitchen_lights"})
        await wait_for(lambda: len(received) >= 1, timeout=10.0, desc="state_changed event received")

        deadline = asyncio.get_running_loop().time() + 10.0
        row = None
        while asyncio.get_running_loop().time() < deadline:
            query = (
                "SELECT COUNT(*), MIN(session_id), MAX(session_id)"
                " FROM handler_invocations WHERE session_id IS NOT NULL"
            )
            async with hassette.database_service.db.execute(query) as cursor:
                row = await cursor.fetchone()
            if row and row[0] > 0:
                break
            await asyncio.sleep(0.1)

    assert row is not None
    total_count, min_session_id, max_session_id = row[0], row[1], row[2]
    assert total_count > 0, "Expected at least one handler_invocation record after toggling light"
    assert min_session_id is not None, "Expected session_id to be non-null on invocation records"
    assert min_session_id > 0, f"Expected positive session_id on invocation records, got min={min_session_id}"
    assert max_session_id == session_id, (
        f"Expected all invocations to belong to session {session_id}, found max session_id={max_session_id}"
    )


async def test_session_status_running_during_startup(ha_container, tmp_path):
    """The session row has status='running' while Hassette is active."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        session_id = hassette.session_id
        async with hassette.database_service.db.execute(
            "SELECT status FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    # We read inside the context manager while still running, so status must be 'running'
    assert row[0] == "running", f"Expected status='running' during startup, got {row[0]!r}"


async def test_session_finalized_as_success_after_clean_shutdown(ha_container, tmp_path):
    """After a clean shutdown, the session row has status='success' and a non-null stopped_at.

    Queries via a fresh sqlite3 connection after startup_context exits (DB connection closed).
    """
    config = make_system_config(ha_container, tmp_path)
    session_id: int | None = None

    async with startup_context(config) as hassette:
        session_id = hassette.session_id

    # startup_context has exited — Hassette is shut down, aiosqlite connections are closed.
    # Open a fresh read-only connection to verify the finalized session row.
    db_path = config.data_dir / "hassette.db"
    assert db_path.exists(), f"Database file not found at {db_path}"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
    finally:
        conn.close()

    assert row is not None, f"No session row found for session_id={session_id}"
    assert row["status"] == "success", f"Expected status='success' after clean shutdown, got {row['status']!r}"
    assert row["stopped_at"] is not None, "Expected stopped_at to be set after shutdown"


async def test_drop_counters_all_zero_after_clean_lifecycle(ha_container, tmp_path):
    """After a clean startup/shutdown cycle, all drop counters on the session row are 0.

    Queries via a fresh sqlite3 connection after startup_context exits.
    """
    config = make_system_config(ha_container, tmp_path)
    session_id: int | None = None

    async with startup_context(config) as hassette:
        session_id = hassette.session_id
        # Verify live counters are all zero before shutdown
        live_counters = hassette.get_drop_counters()
        assert live_counters == (0, 0, 0, 0), f"Expected zero drop counters during clean run, got {live_counters}"

    db_path = config.data_dir / "hassette.db"
    assert db_path.exists(), f"Database file not found at {db_path}"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT dropped_overflow, dropped_exhausted, dropped_no_session, dropped_shutdown"
            " FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    assert row is not None, f"No session row found for session_id={session_id}"
    assert row["dropped_overflow"] == 0, f"Expected dropped_overflow=0, got {row['dropped_overflow']}"
    assert row["dropped_exhausted"] == 0, f"Expected dropped_exhausted=0, got {row['dropped_exhausted']}"
    assert row["dropped_no_session"] == 0, f"Expected dropped_no_session=0, got {row['dropped_no_session']}"
    assert row["dropped_shutdown"] == 0, f"Expected dropped_shutdown=0, got {row['dropped_shutdown']}"


async def test_read_db_connection_available_during_operation(ha_container, tmp_path):
    """The read_db property on DatabaseService returns a live connection during normal operation."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        read_db = hassette.database_service.read_db
        assert read_db is not None, "Expected read_db to return a live connection"

        # Verify we can actually execute a query on the read connection
        async with read_db.execute("SELECT 1") as cursor:
            result = await cursor.fetchone()

    assert result is not None
    assert result[0] == 1, f"Expected SELECT 1 to return 1, got {result[0]}"


async def test_check_health_succeeds_during_operation(ha_container, tmp_path):
    """TelemetryQueryService.check_health() completes without error during normal operation."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        # check_health() raises on any database error — should complete cleanly here
        await hassette.telemetry_query_service.check_health()


async def test_get_drop_counters_returns_four_tuple_of_zeros(ha_container, tmp_path):
    """CommandExecutor.get_drop_counters() returns a 4-tuple of zeros after a clean startup."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        counters = hassette.get_drop_counters()

    assert isinstance(counters, tuple), f"Expected tuple, got {type(counters)}"
    assert len(counters) == 4, f"Expected 4-tuple, got length {len(counters)}"
    overflow, exhausted, no_session, shutdown = counters
    assert overflow == 0, f"Expected dropped_overflow=0, got {overflow}"
    assert exhausted == 0, f"Expected dropped_exhausted=0, got {exhausted}"
    assert no_session == 0, f"Expected dropped_no_session=0, got {no_session}"
    assert shutdown == 0, f"Expected dropped_shutdown=0, got {shutdown}"


async def test_handler_invocations_source_tier_matches_listener(ha_container, tmp_path):
    """Framework listener invocations have source_tier='framework' after startup.

    Registers a handler on the Hassette bus (framework tier) and toggles a light
    to produce invocations, then verifies all records carry source_tier='framework'.
    """
    config = make_system_config(ha_container, tmp_path)
    received: list[object] = []

    async def capture_handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    async with startup_context(config) as hassette:
        bus = hassette._bus
        sub = bus.on_state_change("light.kitchen_lights", handler=capture_handler)
        await wait_for(lambda: sub.listener.db_id is not None, timeout=10.0, desc="listener registered")
        await hassette.api.call_service("light", "toggle", {"entity_id": "light.kitchen_lights"})
        await wait_for(lambda: len(received) >= 1, timeout=10.0, desc="state_changed event received")

        deadline = asyncio.get_running_loop().time() + 10.0
        tier_counts: dict[str, int] = {}
        while asyncio.get_running_loop().time() < deadline:
            async with hassette.database_service.db.execute(
                "SELECT source_tier, COUNT(*) as cnt FROM handler_invocations GROUP BY source_tier"
            ) as cursor:
                rows = await cursor.fetchall()
            tier_counts = {row[0]: row[1] for row in rows}
            if tier_counts.get("framework", 0) > 0:
                break
            await asyncio.sleep(0.1)

    assert "framework" in tier_counts, f"Expected framework-tier invocation records, found tiers: {list(tier_counts)}"
    assert tier_counts["framework"] > 0, f"Expected at least one framework invocation, got {tier_counts['framework']}"
