"""Telemetry write throughput: records per second from ``CommandExecutor`` into a real SQLite DB.

Each round enqueues ``RECORDS_PER_ROUND`` app-tier execution records through
``execution_pipeline.enqueue_record`` (the path every handler and job completion takes), then
drains the executor's write queue with ``drain_and_persist`` -- the same call ``serve()`` makes
-- until it is empty. Every batch goes through ``DatabaseService.submit()``, its single-writer
worker, and ``TelemetryRepository.persist_execution_batch`` into a migrated temp database.

``serve()`` itself is not driven: its flush-interval timer only fires when the queue sits idle,
which never happens while a round is draining, so calling ``drain_and_persist`` directly times
the same work without polling for "all records committed".
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from hassette.config.models import DatabaseConfig
from hassette.core import execution_pipeline
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from tests.integration.telemetry.helpers import open_db_with_session
from tests.support.factories import make_execution_record, make_listener_registration
from tests.support.mock_hassette import make_mock_hassette

from .conftest import RunAsync, record_throughput

PRODUCTION_DATABASE_CONFIG = DatabaseConfig()
"""Production batch settings: every ``DatabaseConfig`` field at its shipped default.

The settings that shape a write here are ``telemetry_write_queue_max`` (CommandExecutor queue
bound), ``write_queue_max`` (DatabaseService queue bound) and ``write_submit_timeout_seconds``;
the batch size itself is ``execution_pipeline._BATCH_DRAIN_CAP``, which has no config knob.
"""

PRODUCTION_BATCH_SIZE = execution_pipeline._BATCH_DRAIN_CAP
"""Records ``drain_and_persist`` takes off the queue per batch (one SQLite transaction each)."""

RECORDS_PER_ROUND = 5 * PRODUCTION_BATCH_SIZE
"""Records written per timed round: five full batches.

Kept below ``telemetry_write_queue_max`` times ``command_executor_capacity_warn_threshold``
(750 at the defaults), so enqueueing a round never drops records or logs capacity warnings.
"""

ROUNDS = 30
"""Timed rounds; each one writes ``RECORDS_PER_ROUND`` new rows into the same database."""


@dataclass(frozen=True)
class TelemetryWriter:
    executor: CommandExecutor
    session_id: int
    listener_id: int

    def make_round_records(self, round_index: int) -> list[ExecutionRecord]:
        """``RECORDS_PER_ROUND`` records with execution ids no earlier round used (the column is unique)."""
        return [
            make_execution_record(
                session_id=self.session_id,
                listener_id=self.listener_id,
                execution_start_ts=float(i),
                execution_id=f"bench_exec_{round_index}_{i}",
            )
            for i in range(RECORDS_PER_ROUND)
        ]


@pytest.fixture
def telemetry_writer(run_async: RunAsync, tmp_path: Path) -> Iterator[TelemetryWriter]:
    """A ``CommandExecutor`` over a real, migrated ``DatabaseService`` at production batch settings.

    Builds the database, a running session row and one registered listener (the FK every record
    points at) on the ``run_async`` loop, so the DB write worker task lives on the loop that
    times each round.
    """

    async def build() -> tuple[DatabaseService, CommandExecutor, int]:
        hassette = make_mock_hassette(
            data_dir=tmp_path,
            set_ready=False,
            sealed=False,
            database=PRODUCTION_DATABASE_CONFIG.model_dump(),
        )
        db_service, session_id = await open_db_with_session(hassette)
        hassette.session_id = session_id
        hassette.try_session_id.return_value = session_id
        hassette.database_service = db_service

        executor = CommandExecutor(hassette, parent=hassette)
        await executor.on_initialize()
        listener_id = await executor.register_listener(make_listener_registration())
        return db_service, executor, listener_id

    db_service, executor, listener_id = run_async(build())
    assert executor._write_queue.maxsize == PRODUCTION_DATABASE_CONFIG.telemetry_write_queue_max
    try:
        yield TelemetryWriter(executor=executor, session_id=executor.hassette.try_session_id(), listener_id=listener_id)
    finally:
        run_async(db_service.on_shutdown())


def test_telemetry_write_throughput(
    benchmark: BenchmarkFixture,
    run_async: RunAsync,
    telemetry_writer: TelemetryWriter,
    request: pytest.FixtureRequest,
) -> None:
    """Enqueue and persist ``RECORDS_PER_ROUND`` records in ``PRODUCTION_BATCH_SIZE`` batches."""
    executor = telemetry_writer.executor
    rounds_run = 0

    def setup():
        nonlocal rounds_run
        records = telemetry_writer.make_round_records(rounds_run)
        rounds_run += 1
        return (records,), {}

    async def write_round(records: list[ExecutionRecord]) -> None:
        for record in records:
            execution_pipeline.enqueue_record(executor, record)
        while not executor._write_queue.empty():
            await execution_pipeline.drain_and_persist(executor)

    benchmark.pedantic(lambda records: run_async(write_round(records)), setup=setup, rounds=ROUNDS, iterations=1)

    assert executor.get_drop_counters() == (0, 0, 0)
    # --benchmark-disable runs the round once instead of ROUNDS times.
    total = run_async(_count_executions(executor))
    assert total == RECORDS_PER_ROUND * rounds_run
    record_throughput(benchmark, request, records_per_round=RECORDS_PER_ROUND)


async def _count_executions(executor: CommandExecutor) -> int:
    db = executor.hassette.database_service.db
    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row is not None
    return row[0]
