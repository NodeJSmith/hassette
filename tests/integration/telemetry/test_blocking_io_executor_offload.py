"""End-to-end integration tests for blocking-IO detection: executor-offload and ignore behavior.

Covers:
    AC#4 (FR#8): A sync handler — run by the framework on a WORKER thread via the executor —
        that performs blocking I/O must produce ZERO HassetteBlockingIOWarnings AND ZERO
        blocking_events rows.  The thread-id gate in both Tier 1 and Tier 2 is what makes
        this true; this test proves that gate holds end-to-end.

    AC#6 (row-suppression half, FR#7): An app configured with blocking_io_behavior='ignore'
        that genuinely blocks the loop (time.sleep on the loop thread, inside an async handler)
        produces NEITHER a warning NOR a blocking_events row.  The resolver unit-tests live in
        T01; this test is the end-to-end persistence half.

Threading model:
    Both tests run on the same asyncio event loop (loop thread = the test thread).  For AC#4
    the blocking time.sleep is explicitly dispatched onto a worker thread (mimicking what
    make_async_adapter does for sync handlers); for AC#6 the sleep fires on the loop thread
    itself but the behavior resolver returns IGNORE so nothing is recorded.

Mock strategy:
    AC#4 tests use the telemetry conftest's ``db``/``db_hassette`` fixtures (sealed mock)
    because they only need the thread-id gate to exclude worker-thread calls — the resolver
    is never invoked at all.

    AC#6 tests use an unsealed MagicMock with explicit resolver wiring so that
    ``resolve_blocking_io_behavior`` can traverse the mock's attribute chain and return
    IGNORE.  This mirrors the unit-test approach in ``test_protect_loop_monkeypatch.py``.
"""

import asyncio
import threading
import time
import warnings
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import hassette.core.block_io_guard as guard_mod
from hassette.core.block_io_guard import install, resolve_blocking_io_behavior, uninstall
from hassette.core.command_executor import CommandExecutor, ExecutionMarker
from hassette.core.database_service import DatabaseService
from hassette.core.loop_watchdog import LoopWatchdog
from hassette.exceptions import HassetteBlockingIOWarning
from hassette.test_utils.config import make_test_config
from hassette.types.enums import BlockingIOBehavior

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _fetch_blocking_events(db_svc: DatabaseService) -> list[dict]:
    """Return all rows from blocking_events as plain dicts."""
    cursor = await db_svc.db.execute("SELECT * FROM blocking_events ORDER BY id")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def _drain(db_svc: DatabaseService) -> None:
    """Block until every enqueued record_blocking_event DB write has been processed.

    The single-writer DB worker drains its queue in FIFO order, so submitting a sentinel coroutine
    and awaiting it guarantees that all writes enqueued before it have finished — deterministic
    where a fixed sleep would race the worker on slow CI.
    """

    async def _sentinel() -> None:
        return None

    await db_svc.submit(_sentinel())


def _make_ignore_hassette(premigrated_db_path: Path) -> MagicMock:
    """Build an unsealed MagicMock hassette wired so the real resolver returns IGNORE.

    The per-app resolution path is what these tests exercise: a live execution marker carries an
    ``app_key``, the guard confirms attribution and resolves it to the owning app via
    ``app_handler.get(app_key)``, and ``resolve_blocking_io_behavior`` reads
    ``owner.app_config.blocking_io_behavior``.

    ``app_handler.get`` returns a per-app owner whose ``app_config.blocking_io_behavior`` is IGNORE,
    so the tests run the genuine owner-lookup + resolution path (a broken ``app_handler.get`` or
    resolver would now fail) rather than short-circuiting on an attribute pinned to the mock.
    """
    config = make_test_config(
        data_dir=premigrated_db_path.parent,
        database={"telemetry_write_queue_max": 500, "max_size_mb": 0},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
        web_api={"run": True},
    )
    h = MagicMock()
    h.config = config

    # The owning app for the bound execution's app_key. The real resolver reads
    # owner.app_config.blocking_io_behavior; returning this from app_handler.get exercises the
    # genuine per-app lookup + resolution path.
    app_owner = SimpleNamespace(
        app_config=SimpleNamespace(
            blocking_io_behavior=BlockingIOBehavior.IGNORE,
            instance_name="ignored_app_0",
        )
    )
    h.app_handler.get.return_value = app_owner

    # Lifecycle signals.
    h.ready_event = AsyncMock()
    h.shutdown_event = MagicMock()
    h.session_id = None
    h.database_service = None
    h._loop_thread_id = threading.get_ident()
    h.children = []

    return h


# ---------------------------------------------------------------------------
# Fixtures — AC#4: use the telemetry conftest's sealed db_hassette
# ---------------------------------------------------------------------------


@pytest.fixture
def loop_thread_id() -> int:
    """The loop thread id — in the test harness this is the main test thread."""
    return threading.get_ident()


@pytest.fixture
async def executor(
    db_hassette: MagicMock,
    db: tuple[DatabaseService, int],
) -> AsyncIterator[CommandExecutor]:
    """CommandExecutor wired to the real DB via the telemetry conftest's ``db`` fixture."""
    _db_service, _session_id = db
    exc = CommandExecutor(db_hassette, parent=None)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


# ---------------------------------------------------------------------------
# Fixtures — AC#6: unsealed mock with IGNORE wiring + dedicated DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def ignore_db(premigrated_db_path: Path) -> AsyncIterator[tuple[DatabaseService, "MagicMock", int]]:
    """DatabaseService + unsealed hassette mock + session_id for AC#6 tests."""
    h = _make_ignore_hassette(premigrated_db_path)
    db_service = DatabaseService(h, parent=None)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    h.session_id = session_id
    h.database_service = db_service
    try:
        yield db_service, h, session_id
    finally:
        await db_service.on_shutdown()


@pytest.fixture
async def ignore_executor(
    ignore_db: tuple[DatabaseService, "MagicMock", int],
) -> AsyncIterator[CommandExecutor]:
    """CommandExecutor wired to the ignore_db hassette and session."""
    _db_service, h, _session_id = ignore_db
    exc = CommandExecutor(h, parent=None)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


# ---------------------------------------------------------------------------
# AC#4 / FR#8: Sync handler (executor offload) — zero warnings, zero rows
# ---------------------------------------------------------------------------


class TestExecutorOffloadProducesNoBlocking:
    """Executor-offloaded sync handlers must never trigger detection (FR#8, AC#4).

    The mechanism: both Tier 1 and Tier 2 gate on the loop thread id.  A sync
    handler runs on a worker thread via run_in_executor, not the loop thread, so
    the gate is never satisfied regardless of what the handler does.
    """

    async def test_tier2_does_not_flag_worker_thread_sleep(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
        loop_thread_id: int,
    ) -> None:
        """time.sleep on a WORKER thread produces zero warnings and zero DB rows (AC#4).

        Tier 2 is installed with the loop_thread_id of the test (= the loop thread).
        A worker thread runs time.sleep — the thread-id gate excludes it, so no
        HassetteBlockingIOWarning fires and no blocking_events row is written.
        """
        db_svc, _ = db
        h = executor.hassette

        # Enable Tier 2 in dev mode so it would fire if the gate were absent.
        h.config.dev_mode = True
        h.config.blocking_io.deep_detection_enabled = True

        assert not guard_mod.is_installed(), "Tier 2 must not be pre-installed"
        install(h, loop_thread_id=loop_thread_id, executor=executor)
        assert guard_mod.is_installed()

        caught_warnings: list[warnings.WarningMessage] = []
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always", HassetteBlockingIOWarning)

                # Dispatch a blocking sleep onto a WORKER thread (mimics make_async_adapter).
                # Capture the worker's thread id to PROVE the sleep ran off the loop thread —
                # otherwise "zero detections" could pass for the wrong reason.
                loop = asyncio.get_running_loop()
                worker_tids: list[int] = []

                def _sleep_on_worker(duration: float) -> None:
                    worker_tids.append(threading.get_ident())
                    time.sleep(duration)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    await loop.run_in_executor(pool, _sleep_on_worker, 0.05)

                assert worker_tids, "worker callable did not run"
                assert worker_tids[0] != loop_thread_id, (
                    "sleep must have run on a worker thread, not the loop thread — test would be vacuous otherwise"
                )

                # Drain so any (unexpected) record_blocking_event tasks would have persisted.
                await _drain(db_svc)
        finally:
            uninstall()
            h.config.blocking_io.deep_detection_enabled = None

        blocking_warnings = [w for w in caught_warnings if issubclass(w.category, HassetteBlockingIOWarning)]
        assert blocking_warnings == [], (
            f"Expected zero HassetteBlockingIOWarnings for worker-thread time.sleep, "
            f"got: {[str(w.message) for w in blocking_warnings]}"
        )

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 0, (
            f"Expected zero blocking_events rows for executor-offloaded sync handler, got {len(rows)}: {rows}"
        )

    async def test_tier1_watchdog_does_not_flag_worker_thread_sleep(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
        loop_thread_id: int,
    ) -> None:
        """Worker-thread sleep keeps the loop responsive — Tier 1 never fires (AC#4, FR#9).

        The loop thread is free while the executor runs the sleep.  The watchdog's
        in-loop tick callback keeps advancing, so no lag episode is opened.
        """
        db_svc, _ = db
        h = executor.hassette
        loop = asyncio.get_running_loop()

        # A short lag threshold so the watchdog is sensitive. The interval must be SMALLER than the
        # threshold: otherwise the gap between ticks alone exceeds the threshold and a responsive
        # loop can look stale, producing false positives that would mask a real regression here.
        orig_lag = h.config.blocking_io.lag_threshold_seconds
        orig_interval = h.config.blocking_io.watchdog_interval_seconds
        h.config.blocking_io.lag_threshold_seconds = 0.05
        h.config.blocking_io.watchdog_interval_seconds = 0.01

        stall_events: list[object] = []
        watchdog = LoopWatchdog(
            h,
            loop=loop,
            loop_thread_id=loop_thread_id,
            executor=executor,
            on_stall=stall_events.append,
        )
        watchdog.start()

        caught_warnings: list[warnings.WarningMessage] = []
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always", HassetteBlockingIOWarning)

                # Sleep on a WORKER thread — the loop is free the whole time. Capture the
                # worker thread id to prove it ran off the loop thread.
                worker_tids: list[int] = []

                def _sleep_on_worker(duration: float) -> None:
                    worker_tids.append(threading.get_ident())
                    time.sleep(duration)

                # Bind a live execution while the worker sleeps. The watchdog only attributes and
                # persists a stall when a marker is live; without one a wrongly-detected stall would
                # be skipped and the zero-rows assertion could pass vacuously. With it bound, any
                # false stall is attributed and surfaces — so zero rows genuinely proves the loop
                # stayed responsive while the sleep ran off-thread.
                _exec_id, token = executor.bind_execution_context("sync_handler_app", 0)
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        await loop.run_in_executor(pool, _sleep_on_worker, 0.2)

                    assert worker_tids, "worker callable did not run"
                    assert worker_tids[0] != loop_thread_id, (
                        "sleep must have run on a worker thread, not the loop thread"
                    )

                    # Give the watchdog multiple poll cycles to notice if it wrongly flags.
                    await asyncio.sleep(0.3)
                    await _drain(db_svc)
                finally:
                    executor.unbind_execution_context(token)
        finally:
            watchdog.stop()
            h.config.blocking_io.lag_threshold_seconds = orig_lag
            h.config.blocking_io.watchdog_interval_seconds = orig_interval

        blocking_warnings = [w for w in caught_warnings if issubclass(w.category, HassetteBlockingIOWarning)]
        assert blocking_warnings == [], (
            f"Tier 1 must not flag a worker-thread sleep, got: {[str(w.message) for w in blocking_warnings]}"
        )
        assert stall_events == [], f"Tier 1 on_stall must not fire for a worker-thread sleep, got: {stall_events}"

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 0, f"Expected zero blocking_events rows for worker-thread sleep, got {len(rows)}: {rows}"


# ---------------------------------------------------------------------------
# AC#6 / FR#7: Per-app 'ignore' behavior — zero warnings, zero rows
# ---------------------------------------------------------------------------


class TestIgnoreBehaviorSuppressesRowAndWarning:
    """Per-app blocking_io_behavior='ignore' suppresses both the warning and the DB row (AC#6).

    The resolver unit-tests (T01) prove resolution order.  This test proves the
    end-to-end persistence half: even when a blocking call genuinely occurs on the
    loop thread, 'ignore' means nothing is recorded.

    The hassette mock is wired with ``app_config.blocking_io_behavior = IGNORE`` so
    the resolver finds IGNORE on the per-app path without needing to traverse the
    global config chain through a sealed mock.
    """

    async def test_tier2_ignore_suppresses_warning_and_row(
        self,
        ignore_executor: CommandExecutor,
        ignore_db: tuple[DatabaseService, "MagicMock", int],
        loop_thread_id: int,
    ) -> None:
        """Tier 2 with ignore behavior: time.sleep on loop thread → no warning, no row.

        Binds a live execution so the guard resolves the marker's app_key to the per-app owner via
        app_handler.get and reads its IGNORE behavior — the genuine resolution path, not a mock
        short-circuit. A resolver spy (wraps, not replace) proves that path was actually reached.
        """
        db_svc, h, _ = ignore_db

        h.config.dev_mode = True
        h.config.blocking_io.deep_detection_enabled = True

        # Live execution: marker.app_key drives app_handler.get(app_key) → the IGNORE owner.
        _exec_id, token = ignore_executor.bind_execution_context("ignored_app", 0)

        assert not guard_mod.is_installed()
        install(h, loop_thread_id=loop_thread_id, executor=ignore_executor)
        assert guard_mod.is_installed()

        caught_warnings: list[warnings.WarningMessage] = []
        # Spy on (without replacing) the resolver: a call proves the guard reached per-app behavior
        # resolution. Combined with app_handler.get being consulted, this fails if either collaborator
        # is broken — the prior version could pass even then.
        with patch(
            "hassette.core.block_io_guard.resolve_blocking_io_behavior",
            wraps=resolve_blocking_io_behavior,
        ) as resolve_spy:
            try:
                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter("always", HassetteBlockingIOWarning)

                    # Call time.sleep on the LOOP thread — Tier 2 fires unless behavior is IGNORE.
                    time.sleep(0.01)  # noqa: ASYNC251

                    await _drain(db_svc)
            finally:
                uninstall()
                ignore_executor.unbind_execution_context(token)

        assert resolve_spy.called, "guard must reach per-app behavior resolution (test not vacuous)"
        h.app_handler.get.assert_called_with("ignored_app", 0)

        blocking_warnings = [w for w in caught_warnings if issubclass(w.category, HassetteBlockingIOWarning)]
        assert blocking_warnings == [], (
            f"ignore behavior must suppress HassetteBlockingIOWarning, "
            f"got: {[str(w.message) for w in blocking_warnings]}"
        )

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 0, f"ignore behavior must suppress blocking_events row, got {len(rows)}: {rows}"

    async def test_tier1_ignore_suppresses_warning_and_row(
        self,
        ignore_executor: CommandExecutor,
        ignore_db: tuple[DatabaseService, "MagicMock", int],
        loop_thread_id: int,
    ) -> None:
        """Tier 1 with ignore behavior: loop stall → no warning, no row.

        A real time.sleep on the loop thread starves the watchdog tick.  With IGNORE
        behavior the watchdog resolves to IGNORE in _emit() and short-circuits before
        warnings.warn and before record_blocking_event.
        """
        db_svc, h, _ = ignore_db
        loop = asyncio.get_running_loop()

        h.config.blocking_io.lag_threshold_seconds = 0.05
        h.config.blocking_io.watchdog_interval_seconds = 0.1

        # The watchdog only acts when an execution marker is live (it attributes the stall to the
        # running execution). Set one so the stall is actually detected and attributed — without
        # it the watchdog skips detection entirely and the test would pass for the wrong reason.
        # task_id is stamped with this task so the watchdog confirms the marker (it freezes the loop
        # in this same task below) and resolves the app's IGNORE behavior rather than global config.
        ignore_executor.current_execution = ExecutionMarker(
            app_key="ignored_app",
            instance_name=None,
            execution_id="exec-ignore",
            started_at=time.monotonic(),
            instance_index=0,
            task_id=id(asyncio.current_task()),
        )

        stall_events: list[object] = []
        watchdog = LoopWatchdog(
            h,
            loop=loop,
            loop_thread_id=loop_thread_id,
            executor=ignore_executor,
            on_stall=stall_events.append,
        )

        caught_warnings: list[warnings.WarningMessage] = []
        # Spy on (without replacing) the watchdog's behavior resolver: a call proves the daemon
        # actually DETECTED the stall and reached the resolve step (non-vacuous). wraps= keeps the
        # real resolver, which reads IGNORE off the per-app owner returned by app_handler.get — so a
        # broken owner lookup or resolver would surface as a warning/row instead of silently passing.
        with patch(
            "hassette.core.loop_watchdog.resolve_blocking_io_behavior",
            wraps=resolve_blocking_io_behavior,
        ) as resolve_spy:
            watchdog.start()
            try:
                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter("always", HassetteBlockingIOWarning)

                    # Stall the loop thread long enough that the watchdog detects it
                    # (0.3s >> the 0.05s threshold, so detection is deterministic).
                    time.sleep(0.3)  # noqa: ASYNC251

                    # Let the watchdog recover and process the (suppressed) episode.
                    await asyncio.sleep(0.4)
                    await _drain(db_svc)
            finally:
                watchdog.stop()

        assert resolve_spy.called, "watchdog must have detected the stall and resolved behavior (test not vacuous)"

        blocking_warnings = [w for w in caught_warnings if issubclass(w.category, HassetteBlockingIOWarning)]
        assert blocking_warnings == [], (
            f"Tier 1 with ignore behavior must produce no warnings, got: {[str(w.message) for w in blocking_warnings]}"
        )

        # IGNORE short-circuits in _emit BEFORE on_stall, so persistence never fires.
        assert stall_events == [], f"IGNORE must short-circuit before on_stall, got: {stall_events}"

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 0, f"Tier 1 with ignore behavior must produce no DB rows, got {len(rows)}: {rows}"
