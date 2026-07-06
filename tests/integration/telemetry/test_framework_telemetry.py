"""Integration tests for telemetry source tier feature.

Tests the full telemetry pipeline for framework-internal listeners and jobs,
including error handling, pre-DB queue drain, orphan records, reconciliation,
and drop counter behavior.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette import HassetteConfig
from hassette.commands import InvokeHandler
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.test_utils.config import TEST_TOKEN
from hassette.test_utils.factories import make_job_registration, make_listener_registration
from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.mock_hassette import make_mock_hassette


@pytest.fixture
def harness_config(tmp_path: Path) -> HassetteConfig:
    """Create a test config pointing to a temporary database."""
    config = HassetteConfig(data_dir=tmp_path, token=TEST_TOKEN)
    config.database.telemetry_write_queue_max = 10  # Small queue for testing overflow
    return config


@pytest.fixture
async def framework_hassette(premigrated_db_path: Path) -> AsyncIterator[MagicMock]:
    """Create a mock Hassette with database service for direct executor tests."""
    hassette = make_mock_hassette(
        sealed=False,
        data_dir=premigrated_db_path.parent,
        set_ready=False,
        database={"max_size_mb": 0},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
    )

    db_service = DatabaseService(hassette, parent=None)
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

    yield hassette

    await db_service.on_shutdown()


async def test_framework_listener_registers_with_source_tier(harness_config: HassetteConfig) -> None:
    """Framework listener via Bus.on() on a framework Resource → source_tier='framework' in DB."""
    async with HassetteHarness(harness_config).with_bus() as harness:

        async def test_handler(event: MagicMock) -> None:
            pass

        bus = harness.bus
        await bus.on(
            topic="test.topic",
            handler=test_handler,
            name="hassette.test.listener",
        )

        listeners = harness.bus_service.router.get_topic_listeners("test.topic")
        assert len(listeners) > 0
        listener = listeners[0]
        assert listener.identity.source_tier == "framework"
        assert listener.identity.app_key.startswith("__hassette__.")


async def test_framework_job_registers_with_db(framework_hassette: MagicMock) -> None:
    """Framework job registration creates DB record with source_tier='framework'."""
    hassette = framework_hassette
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a framework job via CommandExecutor
    reg = make_job_registration(
        app_key="__hassette__",
        handler_method="__hassette__.test_job",
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


async def test_command_executor_records_source_tier_on_error(framework_hassette: MagicMock) -> None:
    """Framework listener error → invocation record with source_tier='framework'."""
    hassette = framework_hassette
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    # Create a listener invocation that fails
    listener = MagicMock()
    listener.invoker.invoke = AsyncMock(side_effect=ValueError("handler error"))
    listener.invoker.error_handler = None

    mock_event = MagicMock()
    mock_event.payload.event_id = None
    mock_event.payload.origin = None
    cmd = InvokeHandler(
        listener=listener,
        event=mock_event,
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
    assert isinstance(record, ExecutionRecord)
    assert record.kind == "handler"
    assert record.source_tier == "framework"
    assert record.status == "error"
    assert record.error_type == "ValueError"


async def test_command_executor_job_registration_with_source_tier(framework_hassette: MagicMock) -> None:
    """Framework job registration stores source_tier='framework' in DB."""
    hassette = framework_hassette
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a framework job
    reg = make_job_registration(
        app_key="__hassette__",
        handler_method="__hassette__.test_job",
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


async def test_queue_persistence_via_drain_and_persist(framework_hassette: MagicMock) -> None:
    """Records queued → drain_and_persist() → persisted to executions table."""
    hassette = framework_hassette
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a listener to get valid listener_id
    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    # Queue an invocation record
    listener = MagicMock()
    listener.invoker.invoke = AsyncMock()
    listener.invoker.error_handler = None

    mock_event = MagicMock()
    mock_event.payload.event_id = None
    mock_event.payload.origin = None
    cmd = InvokeHandler(
        listener=listener,
        event=mock_event,
        topic="test",
        listener_id=listener_id,
        source_tier="app",
        effective_timeout=None,
    )
    await executor.execute(cmd)

    # Drain and persist
    await executor.drain_and_persist()

    # Query the unified executions table
    rows = await db_service.submit(
        db_service.db.execute(
            "SELECT listener_id, source_tier, status FROM executions WHERE listener_id = ?",
            (listener_id,),
        )
    )
    rows_list = await rows.fetchall()

    assert len(rows_list) > 0
    queried_listener_id, source_tier, status = rows_list[0]
    assert queried_listener_id == listener_id
    assert source_tier == "app"
    assert status == "success"


async def test_reconciliation_excludes_framework_app_key(framework_hassette: MagicMock) -> None:
    """Reconciliation with non-framework app_key → __hassette__ rows unaffected."""
    hassette = framework_hassette
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    db_service = hassette.database_service

    # Register a framework listener
    fw_reg = make_listener_registration(
        app_key="__hassette__",
        handler_method="__hassette__.on_event",
        topic="test.topic",
        name="__hassette__.on_event",
        source_tier="framework",
    )
    fw_listener_id = await executor.register_listener(fw_reg)

    # Register an app listener
    app_reg = make_listener_registration(topic="test.topic")
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


async def test_telemetry_query_service_exists(harness_config: HassetteConfig) -> None:
    """TelemetryQueryService can be instantiated (filtering tested in DB tests)."""
    async with HassetteHarness(harness_config).with_bus() as harness:
        # Create telemetry query service
        query_service = TelemetryQueryService(harness.hassette, parent=harness.hassette)

        # Verify service exists and has the method
        assert hasattr(query_service, "get_all_app_summaries")
        assert callable(query_service.get_all_app_summaries)


async def test_drop_counter_overflow_when_queue_full(framework_hassette: MagicMock) -> None:
    """Write queue full → dropped records incremented (AC-13)."""
    hassette = framework_hassette
    hassette.config.database.telemetry_write_queue_max = 2
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    # Enqueue records until queue is full
    listener = MagicMock()
    listener.invoker.invoke = AsyncMock()
    listener.invoker.error_handler = None

    for i in range(hassette.config.database.telemetry_write_queue_max):
        mock_event = MagicMock()
        mock_event.payload.event_id = None
        mock_event.payload.origin = None
        cmd = InvokeHandler(
            listener=listener,
            event=mock_event,
            topic="test",
            listener_id=i + 1,
            source_tier="app",
            effective_timeout=None,
        )
        await executor.execute(cmd)

    # Queue should be full
    assert executor._write_queue.full()

    # Try to enqueue one more — should be dropped
    overflow_event = MagicMock()
    overflow_event.payload.event_id = None
    overflow_event.payload.origin = None
    cmd = InvokeHandler(
        listener=listener,
        event=overflow_event,
        topic="test",
        listener_id=999,
        source_tier="app",
        effective_timeout=None,
    )
    await executor.execute(cmd)

    # Verify drop counter incremented
    dropped_overflow, _exhausted, _shutdown = executor.get_drop_counters()
    assert dropped_overflow > 0


async def test_get_drop_counters_returns_tuple(framework_hassette: MagicMock) -> None:
    """get_drop_counters() returns (overflow, exhausted, shutdown) counters."""
    hassette = framework_hassette
    executor = CommandExecutor(hassette, parent=hassette)
    await executor.on_initialize()

    # Initially all counters should be 0
    overflow, exhausted, shutdown = executor.get_drop_counters()
    assert isinstance(overflow, int)
    assert isinstance(exhausted, int)
    assert isinstance(shutdown, int)
    assert overflow == 0
    assert exhausted == 0
    assert shutdown == 0
