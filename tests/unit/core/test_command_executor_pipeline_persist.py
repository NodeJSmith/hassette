"""Unit tests for CommandExecutor write-pipeline record building and persistence.

Companion files: ``test_command_executor_pipeline_queue.py`` covers the bounded queue and
retry/backoff behavior; ``test_command_executor_pipeline_serve.py`` covers the ``serve()`` loop,
blocking-event handling, and completion-event warnings. Together these three files replace the
former ``test_command_executor_pipeline.py``.

Tests cover:
- source_tier and is_di_failure in build_record
- flush_queue graceful handling on DB closed
- TelemetryRepository.persist_execution_batch column coverage
"""

import time
from unittest.mock import AsyncMock, MagicMock

import aiosqlite

from hassette.commands import InvokeHandler
from hassette.core import execution_pipeline
from hassette.core.execution_record import ExecutionRecord
from hassette.core.execution_record_builder import build_execution_record
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.types.types import SourceTier

from .conftest import init_executor, make_invocation
from .test_command_executor import make_result


# Real InvokeHandler, unlike the shared make_invoke_handler_cmd() in tests/support/factories.py
# which returns a MagicMock — build_record tests here assert on the constructed object's own
# fields directly.
def make_real_invoke_handler_cmd(*, listener_id: int = 5, source_tier: SourceTier = "app") -> InvokeHandler:
    listener = MagicMock()
    listener.invoker.invoke = AsyncMock()
    event = MagicMock()
    return InvokeHandler(
        listener=listener,
        event=event,
        topic="test/topic",
        listener_id=listener_id,
        source_tier=source_tier,
        effective_timeout=None,
    )


def test_build_record_reads_source_tier():
    """build_record sets source_tier from cmd.source_tier and returns ExecutionRecord."""
    executor = init_executor()

    cmd = make_real_invoke_handler_cmd(listener_id=5, source_tier="framework")
    result = make_result()

    record = build_execution_record(
        cmd, result, time.time(), "test-exec-id", session_id=executor.hassette.try_session_id()
    )

    assert isinstance(record, ExecutionRecord)
    assert record.kind == "handler"
    assert record.source_tier == "framework"
    assert record.listener_id == 5


def test_build_record_reads_is_di_failure():
    """build_record sets is_di_failure from result.is_di_failure."""
    executor = init_executor()

    cmd = make_real_invoke_handler_cmd(listener_id=5, source_tier="app")
    result = make_result(status="error", error_type="DependencyError", error_message="dep failed", is_di_failure=True)

    record = build_execution_record(
        cmd, result, time.time(), "test-exec-id", session_id=executor.hassette.try_session_id()
    )

    assert isinstance(record, ExecutionRecord)
    assert record.is_di_failure is True


def test_build_record_reads_thread_leaked():
    """build_record copies thread_leaked from result to ExecutionRecord."""
    executor = init_executor()

    cmd = make_real_invoke_handler_cmd(listener_id=1, source_tier="app")

    result = make_result(status="timed_out", thread_leaked=True)

    record = build_execution_record(cmd, result, time.time(), "exec-id", session_id=executor.hassette.try_session_id())
    assert record.thread_leaked is True

    result.thread_leaked = False
    record = build_execution_record(
        cmd, result, time.time(), "exec-id-2", session_id=executor.hassette.try_session_id()
    )
    assert record.thread_leaked is False


async def test_flush_queue_handles_db_closed():
    """flush_queue does not raise when DB submit raises RuntimeError (DB closed at shutdown)."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    executor._write_queue.put_nowait(inv)

    submit_attempts = 0

    # Make submit raise RuntimeError (simulating closed DB) — close the coro to avoid leak
    async def fail_submit(coro):
        nonlocal submit_attempts
        submit_attempts += 1
        coro.close()  # prevent "coroutine was never awaited" warning
        raise RuntimeError("database is closed")

    executor.hassette.database_service.submit = fail_submit  # pyright: ignore[reportAttributeAccessIssue]

    async def fake_persist(_recs):
        pass

    executor.repository.persist_execution_batch = fake_persist  # pyright: ignore[reportAttributeAccessIssue]

    # flush_queue must NOT raise — shutdown must complete
    await execution_pipeline.flush_queue(executor)

    # flush_queue drains the queue *before* it attempts to persist, so an empty queue alone
    # proves nothing. Pin the persist attempt itself — this fails if flush_queue ever dequeues
    # and returns early, which is the regression the empty-queue check cannot see.
    assert submit_attempts == 1, "flush_queue must make its best-effort persist attempt"
    assert executor._write_queue.empty()


async def test_persist_execution_batch_includes_source_tier():
    """TelemetryRepository.persist_execution_batch INSERT includes source_tier column."""
    schema = """
PRAGMA foreign_keys = ON;

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    stopped_at REAL,
    last_heartbeat_at REAL NOT NULL,
    status TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    error_traceback TEXT
);

CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT    NOT NULL CHECK (kind IN ('handler', 'job')),
    listener_id           INTEGER,
    job_id                INTEGER,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT,
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
    source_tier           TEXT    NOT NULL DEFAULT 'app',
    execution_id          TEXT UNIQUE,
    trigger_context_id    TEXT,
    trigger_origin        TEXT,
    trigger_mode          TEXT,
    retry_count           INTEGER NOT NULL DEFAULT 0,
    attempt_number        INTEGER NOT NULL DEFAULT 1,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    thread_leaked         INTEGER NOT NULL DEFAULT 0
);
"""

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(schema)
        await db.commit()

        # Insert a session so FK reference works
        await db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, ?)",
            (time.time(), time.time(), "running"),
        )
        await db.commit()

        mock_db_service = MagicMock()
        mock_db_service.db = db
        repo = TelemetryRepository(mock_db_service)

        record = ExecutionRecord(
            kind="handler",
            listener_id=None,
            session_id=1,
            execution_start_ts=time.time(),
            duration_ms=1.0,
            status="success",
            source_tier="framework",
            is_di_failure=False,
        )

        await repo.persist_execution_batch([record])

        cursor = await db.execute("SELECT source_tier, is_di_failure FROM executions WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None
        assert row["source_tier"] == "framework"
        assert row["is_di_failure"] == 0
