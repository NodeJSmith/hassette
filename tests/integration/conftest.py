"""Shared fixtures for integration tests."""

import asyncio
import shutil
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette import Hassette
from hassette.commands import InvokeHandler
from hassette.config.config import HassetteConfig
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.sync_executor import SyncExecutor
from hassette.test_utils import make_mock_hassette
from hassette.test_utils.helpers import cleanup_hassette_streams
from hassette.types.enums import ExecutionMode

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


# db_hassette config overrides — named so re-tuning is a single-site edit.
DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX = 500
DB_HASSETTE_DATABASE_MAX_SIZE_MB = 0
DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS = 5

_HARNESS_FIXTURES = frozenset(
    {
        "hassette_with_sync_executor",
        "hassette_with_bus",
        "hassette_with_scheduler",
        "hassette_with_file_watcher",
        "hassette_with_state_proxy",
        "hassette_with_state_registry",
        "hassette_with_app_handler",
        # hassette_with_mock_api excluded: yields (Api, SimpleTestServer), not HassetteHarness.
        # hassette_with_app_handler_custom_config excluded: function-scoped, recreated fresh per test.
    }
)


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig, request: pytest.FixtureRequest) -> Hassette:
    """Provide a fresh Hassette instance and restore context afterwards.

    ``wire_services()`` sets the ``HASSETTE_INSTANCE`` ContextVar internally. Because this
    fixture is a *plain* (non-generator) async fixture, pytest-asyncio's own
    ``_apply_contextvar_changes`` machinery already diffs every ContextVar mutated during
    setup against the outer context and registers a synchronous finalizer that resets it —
    no manual Token bookkeeping needed here. (A manually-captured Token would in fact be
    *invalid* to reset later: setup runs inside a copied ``contextvars.Context`` that isn't
    the same Context our own code runs in afterward, and ``ContextVar.reset()`` raises
    ``ValueError`` across Context boundaries.) Without this, the ContextVar would leak the
    (possibly sealed/torn-down) instance into later tests.

    Tests that drive ``run_forever()`` also install a custom asyncio task factory
    (``loop.set_task_factory(make_task_factory(self.task_bucket))`` in
    ``Hassette.run_forever()``) that routes every new task through this instance's
    TaskBucket, and never restores it — mirroring the gap ``HassetteHarness.stop()``
    closes via its own ``_previous_task_factory`` restore. If a test triggers real
    shutdown, that bucket seals.

    This fixture is deliberately a *plain* async fixture (no ``yield``) with cleanup
    registered via ``request.addfinalizer()`` as a *synchronous* callback, rather than
    an ``async def ... yield ...`` generator. pytest-asyncio always resumes an
    async-generator fixture's teardown by creating a brand-new asyncio Task on the
    shared loop (``asyncio_default_test_loop_scope = "session"`` in pyproject.toml, so
    this loop is reused across the whole session). If that loop's task factory is still
    pointing at a now-sealed bucket, *that very task creation* raises before any of the
    generator's own ``finally`` code gets a chance to run — a chicken-and-egg deadlock
    (confirmed via the reproduction in this task: the error surfaced as
    "sealed and rejected new work: async_finalizer"/"shutdown_asyncgens", not from our
    own cleanup code). A plain synchronous finalizer sidesteps this: it runs as ordinary
    Python code with no task creation involved, so it can restore the task factory
    *first* and only then use ``loop.run_until_complete()`` (also safe once the factory
    is back to normal) to drive the async stream cleanup.
    """
    test_config.reload()
    instance = Hassette(test_config)
    instance.wire_services()
    loop = asyncio.get_running_loop()
    previous_task_factory = loop.get_task_factory()

    def _teardown() -> None:
        # Order matters: restore the task factory before anything that might create a
        # new Task, including run_until_complete()'s internal ensure_future() call.
        loop.set_task_factory(previous_task_factory)
        loop.run_until_complete(cleanup_hassette_streams(instance))

    # PT021: request.addfinalizer() instead of `yield` is deliberate here, not the usual
    # missed-convention case that rule flags — see the docstring above for why a `yield`
    # based async-generator fixture deadlocks for this specific fixture.
    request.addfinalizer(_teardown)  # noqa: PT021
    return instance


@pytest.fixture(autouse=True)
async def cleanup_harness(request: pytest.FixtureRequest) -> None:
    """Reset all active module-scoped harness components before each test.

    Function-scoped fixtures (hassette_with_app_handler_custom_config)
    are recreated fresh per test and don't need cleanup.
    """
    for name in _HARNESS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        await harness.reset()


@pytest.fixture
def premigrated_db_path(_migrated_db_template: Path, tmp_path: Path) -> Path:
    """Copy the pre-migrated DB template into a fresh tmp_path for test isolation."""
    dst = tmp_path / "hassette.db"
    shutil.copy2(_migrated_db_template, dst)
    return dst


@pytest.fixture
def db_hassette(premigrated_db_path: Path, sync_executor: SyncExecutor) -> AsyncMock:
    """Provide a mock Hassette with real validated config pointing to a pre-migrated DB.

    Note: telemetry/conftest.py defines a variant with web_api={"run": True} for telemetry tests.
    """
    hassette = make_mock_hassette(
        data_dir=premigrated_db_path.parent,
        set_ready=False,
        sealed=False,
        database={
            "telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
            "max_size_mb": DB_HASSETTE_DATABASE_MAX_SIZE_MB,
        },
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
        scheduler={"min_delay_seconds": 0.1, "max_delay_seconds": 60.0, "default_delay_seconds": 1.0},
    )
    # _create_task_bucket reads hassette.sync_executor when wiring every Resource built
    # from this mock (CommandExecutor, BusService, SchedulerService) — wire the real
    # SyncExecutor so run_in_thread works instead of raising on a None executor.
    hassette._sync_executor = sync_executor
    hassette.sync_executor = sync_executor
    return hassette


@pytest.fixture
async def initialized_db(db_hassette: AsyncMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a real DatabaseService and create a session row.

    Yields:
        Tuple of (DatabaseService instance, session_id).
    """
    db_service = DatabaseService(db_hassette, parent=db_hassette)
    await db_service.on_initialize()
    try:
        now = time.time()
        cursor = await db_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        db_hassette.session_id = session_id
        db_hassette.try_session_id.return_value = session_id
        await db_service.db.commit()
        db_hassette.database_service = db_service
        yield db_service, session_id
    finally:
        await db_service.on_shutdown()


@pytest.fixture
async def executor(
    db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]
) -> AsyncIterator[CommandExecutor]:
    """Create and prepare a CommandExecutor with real DB wired in."""
    _db_service, _session_id = initialized_db
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


def invoke_cmd(listener: MagicMock, *, listener_id: int = 1, effective_timeout: float | None = None) -> InvokeHandler:
    """Build the InvokeHandler command the executor receives for a bus dispatch."""
    return InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=listener_id,
        source_tier="app",
        effective_timeout=effective_timeout,
    )


def pop_execution_record(executor: CommandExecutor) -> ExecutionRecord:
    """Pop the record ``executor`` queued for the execution that just ran.

    Asserts the queue is non-empty and the entry is an ``ExecutionRecord`` so callers can go
    straight to the field they care about.
    """
    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, ExecutionRecord)
    return record


def make_mock_job(
    *,
    owner_id: str = "test_owner",
    app_key: str = "my_app",
    instance_index: int = 1,
    name: str = "test_job",
    error_handler: Callable[..., Any] | None = None,
    db_id: int | None = None,
    mode: ExecutionMode = ExecutionMode.SINGLE,
) -> MagicMock:
    """Return a mock ScheduledJob with the union of fields needed across integration tests."""
    job = MagicMock()
    job.owner_id = owner_id
    job.app_key = app_key
    job.instance_index = instance_index
    job.name = name
    job.job = MagicMock(__qualname__="MyApp.my_job")
    job.trigger = None
    job.args = ()
    job.kwargs = {}
    job.db_id = db_id
    job.mode = mode
    job.error_handler = error_handler
    job.group = None
    return job


def make_manifest_mock(
    app_key: str = "my_app",
    filename: str = "my_app.py",
    class_name: str = "MyApp",
    enabled: bool = True,
    autostart: bool = True,
    app_config: dict | list[dict] | None = None,
    app_dir: Path | None = None,
    full_path: Path | None = None,
) -> MagicMock:
    """Build a manifest mock for config/source endpoint tests."""
    m = MagicMock()
    m.app_key = app_key
    m.filename = filename
    m.class_name = class_name
    m.enabled = enabled
    m.autostart = autostart
    m.app_config = app_config if app_config is not None else {"instance_name": f"{class_name}.0"}
    m.app_dir = app_dir or Path("/apps")
    m.full_path = full_path or (m.app_dir / filename)
    return m
