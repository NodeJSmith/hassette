"""Integration tests for telemetry source tier feature (WP08).

Tests the full telemetry pipeline for framework-internal listeners and jobs,
including error handling, pre-DB queue drain, orphan records, reconciliation,
and drop counter behavior.
"""

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette import HassetteConfig
from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.test_utils.harness import HassetteHarness

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def harness_config(tmp_path: Path) -> HassetteConfig:
    """Create a test config pointing to a temporary database."""
    config = HassetteConfig(data_dir=tmp_path, token="test-token")
    config.telemetry_write_queue_max = 10  # Small queue for testing overflow
    return config


@pytest.fixture
async def mock_hassette_with_db(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database service for direct executor tests."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.command_executor_log_level = "INFO"
    hassette.config.telemetry_write_queue_max = 1000
    hassette.config.db_write_queue_max = 2000
    hassette.ready_event = asyncio.Event()
    hassette._loop_thread_id = threading.get_ident()

    db_service = DatabaseService(hassette, parent=hassette)
    await db_service.on_initialize()

    now = time.time()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    session_id = cursor.lastrowid
    assert session_id is not None

    await db_service.db.commit()
    hassette.session_id = session_id
    hassette.database_service = db_service
    hassette.wait_for_ready = AsyncMock(return_value=True)

    yield hassette

    await db_service.on_shutdown()


# ============================================================================
# AC-10: Framework listener/job error → source_tier='framework'
# ============================================================================


@pytest.mark.asyncio
async def test_framework_listener_registers_with_source_tier(harness_config: HassetteConfig) -> None:
    """Framework listener via Bus.on() on a framework Resource → source_tier='framework' in DB."""
    async with HassetteHarness(harness_config).with_bus() as harness:

        async def test_handler(event: MagicMock) -> None:
            pass

        bus = harness.hassette._bus
        bus.on(
            topic="test.topic",
            handler=test_handler,
            name="hassette.test.listener",
        )
        await harness.hassette._bus_service.await_registrations_complete(bus.parent.app_key)

        listeners = await harness.hassette._bus_service.router.get_topic_listeners("test.topic")
        assert len(listeners) > 0
        listener = listeners[0]
        assert listener.source_tier == "framework"
        assert listener.app_key.startswith("__hassette__.")


@pytest.mark.asyncio
async def test_framework_job_registers_with_db(mock_hassette_with_db: MagicMock) -> None:
    """Framework job registration creates DB record with source_tier='framework'."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a framework job via CommandExecutor
    reg = ScheduledJobRegistration(
        app_key="__hassette__",
        instance_index=0,
        job_name="test_job",
        handler_method="__hassette__.test_job",
        trigger_type=None,
        trigger_label="once",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test.py:1",
        registration_source=None,
        source_tier="framework",
    )
    job_id = await executor.register_job(reg)

    # Verify job ID was returned
    assert isinstance(job_id, int)
    assert job_id > 0

    # Verify it was persisted with source_tier='framework'
    rows = await db_service.submit(
        db_service.db.execute("SELECT id, app_key, source_tier FROM scheduled_jobs WHERE id = ?", (job_id,))
    )
    rows_list = await rows.fetchall()
    assert len(rows_list) == 1
    persisted_id, app_key, source_tier = rows_list[0]
    assert persisted_id == job_id
    assert app_key == "__hassette__"
    assert source_tier == "framework"


@pytest.mark.asyncio
async def test_command_executor_records_source_tier_on_error(mock_hassette_with_db: MagicMock) -> None:
    """Framework listener error → invocation record with source_tier='framework'."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    # Create a listener invocation that fails
    listener = MagicMock()
    listener.invoke = AsyncMock(side_effect=ValueError("handler error"))
    listener.error_handler = None

    from hassette.core.commands import InvokeHandler

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test.topic",
        listener_id=1,
        source_tier="framework",
        effective_timeout=None,
    )

    # Execute the command
    await executor.execute(cmd)

    # Verify record was queued with correct source_tier
    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.source_tier == "framework"
    assert record.status == "error"
    assert record.error_type == "ValueError"


@pytest.mark.asyncio
async def test_command_executor_job_registration_with_source_tier(mock_hassette_with_db: MagicMock) -> None:
    """Framework job registration stores source_tier='framework' in DB."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a framework job
    reg = ScheduledJobRegistration(
        app_key="__hassette__",
        instance_index=0,
        job_name="test_job",
        handler_method="__hassette__.test_job",
        trigger_type=None,
        trigger_label="once",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test.py:1",
        registration_source=None,
        source_tier="framework",
    )
    job_id = await executor.register_job(reg)

    # Verify persisted with correct source_tier
    rows = await db_service.submit(
        db_service.db.execute("SELECT app_key, source_tier FROM scheduled_jobs WHERE id = ?", (job_id,))
    )
    rows_list = await rows.fetchall()
    assert len(rows_list) == 1
    app_key, source_tier = rows_list[0]
    assert app_key == "__hassette__"
    assert source_tier == "framework"


# ============================================================================
# AC-11a: Pre-DB queue drain
# ============================================================================


@pytest.mark.asyncio
async def test_queue_persistence_via_drain_and_persist(mock_hassette_with_db: MagicMock) -> None:
    """Records queued → _drain_and_persist() → persisted to DB."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a listener to get valid listener_id
    reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test.py:1",
        registration_source=None,
        source_tier="app",
    )
    listener_id = await executor.register_listener(reg)

    # Queue an invocation record
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.error_handler = None

    from hassette.core.commands import InvokeHandler

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=listener_id,
        source_tier="app",
        effective_timeout=None,
    )
    await executor.execute(cmd)

    # Drain and persist
    await executor._drain_and_persist()

    # Query the database
    rows = await db_service.submit(
        db_service.db.execute(
            "SELECT listener_id, source_tier, status FROM handler_invocations WHERE listener_id = ?",
            (listener_id,),
        )
    )
    rows_list = await rows.fetchall()

    assert len(rows_list) > 0
    queried_listener_id, source_tier, status = rows_list[0]
    assert queried_listener_id == listener_id
    assert source_tier == "app"
    assert status == "success"


# ============================================================================
# AC-11b: Pre-registration orphan
# ============================================================================


@pytest.mark.asyncio
async def test_pre_registration_orphan_persisted_with_null_listener_id(mock_hassette_with_db: MagicMock) -> None:
    """Handler invocation before DB registration → listener_id=None in DB."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Queue an invocation record with listener_id=None (pre-registration)
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.error_handler = None

    from hassette.core.commands import InvokeHandler

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=None,  # Not yet registered
        source_tier="app",
        effective_timeout=None,
    )
    await executor.execute(cmd)

    # Drain and persist
    await executor._drain_and_persist()

    # Query the database for orphan records
    rows = await db_service.submit(
        db_service.db.execute("SELECT listener_id, status FROM handler_invocations WHERE listener_id IS NULL")
    )
    rows_list = await rows.fetchall()

    assert len(rows_list) > 0
    listener_id, status = rows_list[0]
    assert listener_id is None
    assert status == "success"


# ============================================================================
# AC-19: Reconciliation safety
# ============================================================================


@pytest.mark.asyncio
async def test_reconciliation_excludes_framework_app_key(mock_hassette_with_db: MagicMock) -> None:
    """Reconciliation with non-framework app_key → __hassette__ rows unaffected."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a framework listener
    fw_reg = ListenerRegistration(
        app_key="__hassette__",
        instance_index=0,
        handler_method="__hassette__.on_event",
        topic="test.topic",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test.py:1",
        registration_source=None,
        source_tier="framework",
    )
    fw_listener_id = await executor.register_listener(fw_reg)

    # Register an app listener
    app_reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="test.topic",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test.py:1",
        registration_source=None,
        source_tier="app",
    )
    await executor.register_listener(app_reg)

    # Reconcile only the app (not the framework)
    await executor.reconcile_registrations(
        app_key="test_app",
        live_listener_ids=[],  # Mark app listener as stale
        live_job_ids=[],
        session_id=hassette.session_id,
    )

    # Verify framework listener still exists
    rows = await db_service.submit(
        db_service.db.execute("SELECT id, app_key FROM listeners WHERE id = ?", (fw_listener_id,))
    )
    rows_list = await rows.fetchall()

    assert len(rows_list) == 1
    listener_id, app_key = rows_list[0]
    assert listener_id == fw_listener_id
    assert app_key == "__hassette__"


# ============================================================================
# Tier isolation: framework not exposed in app summaries
# ============================================================================


@pytest.mark.asyncio
async def test_telemetry_query_service_exists(harness_config: HassetteConfig) -> None:
    """TelemetryQueryService can be instantiated (filtering tested in DB tests)."""
    async with HassetteHarness(harness_config).with_bus() as harness:
        # Create telemetry query service
        query_service = TelemetryQueryService(harness.hassette, parent=harness.hassette)

        # Verify service exists and has the method
        assert hasattr(query_service, "get_all_app_summaries")
        assert callable(query_service.get_all_app_summaries)


# ============================================================================
# Drop counter e2e: overflow tracking
# ============================================================================


@pytest.mark.asyncio
async def test_drop_counter_overflow_when_queue_full(mock_hassette_with_db: MagicMock) -> None:
    """Write queue full → dropped records incremented (AC-13)."""
    hassette = mock_hassette_with_db
    hassette.config.telemetry_write_queue_max = 2
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    # Enqueue records until queue is full
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.error_handler = None

    from hassette.core.commands import InvokeHandler

    for i in range(hassette.config.telemetry_write_queue_max):
        cmd = InvokeHandler(
            listener=listener,
            event=MagicMock(),
            topic="test",
            listener_id=i + 1,
            source_tier="app",
            effective_timeout=None,
        )
        await executor.execute(cmd)

    # Queue should be full
    assert executor._write_queue.full()

    # Try to enqueue one more — should be dropped
    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=999,
        source_tier="app",
        effective_timeout=None,
    )
    await executor.execute(cmd)

    # Verify drop counter incremented
    dropped_overflow, _exhausted, _no_session, _shutdown = executor.get_drop_counters()
    assert dropped_overflow > 0


@pytest.mark.asyncio
async def test_get_drop_counters_returns_tuple(mock_hassette_with_db: MagicMock) -> None:
    """get_drop_counters() returns (overflow, exhausted, no_session, shutdown) counters."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    # Initially all counters should be 0
    overflow, exhausted, no_session, shutdown = executor.get_drop_counters()
    assert isinstance(overflow, int)
    assert isinstance(exhausted, int)
    assert isinstance(no_session, int)
    assert isinstance(shutdown, int)
    assert overflow == 0
    assert exhausted == 0
    assert no_session == 0
    assert shutdown == 0


@pytest.mark.asyncio
async def test_sentinel_filtering_listener_id_zero(mock_hassette_with_db: MagicMock) -> None:
    """Sentinel filtering: listener_id=0 dropped (regression check)."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Build a record with listener_id=0 (sentinel)
    bad_record = HandlerInvocationRecord(
        listener_id=0,  # Sentinel value
        session_id=hassette.session_id,
        execution_start_ts=0,
        duration_ms=1,
        status="success",
        source_tier="app",
    )

    # Try to persist it
    await executor._persist_batch([bad_record], [])

    # Verify it was not persisted (silently dropped with REGRESSION log)
    rows = await db_service.submit(db_service.db.execute("SELECT COUNT(*) FROM handler_invocations"))
    rows_list = await rows.fetchall()
    assert rows_list[0][0] == 0  # No records persisted


@pytest.mark.asyncio
async def test_sentinel_filtering_session_id_zero(mock_hassette_with_db: MagicMock) -> None:
    """Sentinel filtering: session_id=0 dropped (regression check)."""
    hassette = mock_hassette_with_db
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Build a record with session_id=0 (sentinel)
    bad_record = HandlerInvocationRecord(
        listener_id=1,
        session_id=0,  # Sentinel value
        execution_start_ts=0,
        duration_ms=1,
        status="success",
        source_tier="app",
    )

    # Try to persist it
    await executor._persist_batch([bad_record], [])

    # Verify it was not persisted
    rows = await db_service.submit(db_service.db.execute("SELECT COUNT(*) FROM handler_invocations"))
    rows_list = await rows.fetchall()
    assert rows_list[0][0] == 0  # No records persisted
