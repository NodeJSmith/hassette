"""Coverage-focused unit tests for Hassette (core.py).

Targets branches not already exercised by test_hassette_lifecycle.py (unit) and
tests/integration/test_core.py (integration): run_startup_tasks() precheck/env-file
branches, on_initialize() timeout warnings, send_event()'s guard branches,
_shutdown_children()'s exception branches and exit stages, _on_children_stopped(), and several
one-line accessors/helpers.
"""

import asyncio
import queue
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import TypeVar, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from anyio import ClosedResourceError
from hassette_wire import ResourceStatus

import hassette.core.core as core_module
import hassette.core.startup_tasks as startup_tasks_module
from hassette import context
from hassette.config.config import HassetteConfig
from hassette.core.core import Hassette
from hassette.core.startup_tasks import run_startup_tasks
from hassette.exceptions import AppPrecheckFailedError, FatalError
from hassette.logging_ import HassetteQueueHandler, LogPersistenceHandler
from hassette.resources.base import Resource
from hassette.resources.shutdown_deadline import deadline_in
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult, incomplete_outcome
from hassette.testing import wait_for
from hassette.utils.url_utils import build_rest_url, build_ws_url
from tests.support.factories import make_log_record
from tests.support.harness import preserve_config
from tests.support.helpers import write_app
from tests.support.run_forever import stub_run_forever_collaborators

TOTAL_SHUTDOWN_TIMEOUT_SECONDS = 0.5

# wire_services() creates anyio memory streams that are closed explicitly in the
# fixture teardown. However, pytest holds internal references to fixture results,
# so the Hassette object's refcount doesn't reach zero until a later GC cycle.
# When GC finalizes it, anyio's MemoryObject.__del__ fires a ResourceWarning for
# streams that were closed but whose owning object wasn't yet collected. This is
# a CPython GC nondeterminism issue, not a real leak — the streams ARE closed.
pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning:anyio")

T = TypeVar("T")


@pytest.fixture
async def wired_hassette(test_config: HassetteConfig) -> AsyncIterator[Hassette]:
    """A fully-wired Hassette instance for accessor/delegation tests.

    wire_services() creates three anyio memory streams. All are closed
    explicitly below. See pytestmark for the ResourceWarning scoping.
    """
    test_config.reload()
    instance = Hassette(test_config)
    instance.wire_services()
    bus_service = require_wired(instance._bus_service)
    stream_service = require_wired(instance._event_stream_service)
    try:
        yield instance
    finally:
        with suppress(ClosedResourceError):
            if not bus_service.stream._closed:
                await bus_service.stream.aclose()
        with suppress(ClosedResourceError):
            if not stream_service.event_streams_closed:
                await stream_service.close_streams()


class TestUrlProperties:
    def test_ws_url_delegates_to_build_ws_url(self, test_config: HassetteConfig) -> None:
        """ws_url returns the same value as calling build_ws_url(config) directly."""
        hassette = Hassette(test_config)
        assert hassette.ws_url == build_ws_url(test_config)

    def test_rest_url_delegates_to_build_rest_url(self, test_config: HassetteConfig) -> None:
        """rest_url returns the same value as calling build_rest_url(config) directly."""
        hassette = Hassette(test_config)
        assert hassette.rest_url == build_rest_url(test_config)


class TestGetInstance:
    def test_get_instance_returns_context_hassette(
        self, wired_hassette: Hassette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_instance() delegates to context.get_hassette()."""
        monkeypatch.setattr(context, "get_hassette", Mock(return_value=wired_hassette))
        assert Hassette.get_instance() is wired_hassette


class TestDropCountersAndErrorHandlerFailures:
    def test_get_drop_counters_delegates_to_command_executor(self, wired_hassette: Hassette) -> None:
        """get_drop_counters() returns exactly what command_executor.get_drop_counters() returns."""
        command_executor = require_wired(wired_hassette._command_executor)
        command_executor.get_drop_counters = Mock(return_value=(1, 2, 3))
        assert wired_hassette.get_drop_counters() == (1, 2, 3)

    def test_get_error_handler_failures_delegates_to_command_executor(self, wired_hassette: Hassette) -> None:
        """get_error_handler_failures() returns exactly what command_executor.get_error_handler_failures() returns."""
        command_executor = require_wired(wired_hassette._command_executor)
        command_executor.get_error_handler_failures = Mock(return_value=5)
        assert wired_hassette.get_error_handler_failures() == 5


class TestGetLogDropCounters:
    def test_returns_zero_before_logging_service_wired(self, test_config: HassetteConfig) -> None:
        """Both counters return 0 when _logging_service is None (pre-wiring)."""
        hassette = Hassette(test_config)
        assert hassette.get_log_queue_drops() == 0
        assert hassette.get_db_write_queue_drops() == 0

    async def test_db_write_queue_drops_from_persistence_handler(self, wired_hassette: Hassette) -> None:
        """get_db_write_queue_drops() forwards real persistence-handler DB queue drops."""
        logging_service = require_wired(wired_hassette._logging_service)
        db_service = Mock()
        db_service._insert_log_records = Mock(return_value=object())
        db_service.enqueue = Mock(return_value=False)
        handler = LogPersistenceHandler(db_service, asyncio.get_running_loop())
        record = make_log_record(name="hassette", msg="message")

        handler.emit(record)
        handler.flush_if_pending()
        await asyncio.sleep(0)

        logging_service.persistence_handler = handler
        assert wired_hassette.get_db_write_queue_drops() == 1

    def test_log_queue_drops_from_queue_handler(self, wired_hassette: Hassette) -> None:
        """get_log_queue_drops() forwards real log-queue drops, not DB write drops."""
        logging_service = require_wired(wired_hassette._logging_service)
        handler = HassetteQueueHandler(queue.Queue(maxsize=1))
        handler.enqueue(make_log_record(name="hassette", msg="first"))
        handler.enqueue(make_log_record(name="hassette", msg="dropped"))

        logging_service._queue_handler = handler
        assert wired_hassette.get_log_queue_drops() == 1
        assert wired_hassette.get_db_write_queue_drops() == 0


class TestIsLogPersistenceActive:
    def test_returns_false_before_logging_service_wired(self, test_config: HassetteConfig) -> None:
        """is_log_persistence_active() is False when _logging_service is None (pre-wiring)."""
        hassette = Hassette(test_config)
        assert hassette.is_log_persistence_active() is False

    def test_forwards_logging_service_persistence_active(self, wired_hassette: Hassette) -> None:
        """is_log_persistence_active() forwards the logging service's persistence_active."""
        logging_service = require_wired(wired_hassette._logging_service)
        assert wired_hassette.is_log_persistence_active() is False

        logging_service.persistence_handler = Mock()
        logging_service._queue_listener = Mock()
        assert wired_hassette.is_log_persistence_active() is True


class TestStartupTasksEnvFiles:
    def test_skips_loading_env_files_when_disabled(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_startup_tasks() never calls load_dotenv when import_dot_env_files is False."""
        load_dotenv_mock = Mock()
        monkeypatch.setattr(startup_tasks_module, "load_dotenv", load_dotenv_mock)

        with preserve_config(test_config):
            test_config.import_dot_env_files = False
            run_startup_tasks(test_config, Mock())

        load_dotenv_mock.assert_not_called()


class TestStartupTasksAppWarnings:
    def test_unconfigured_app_warning_is_logged_at_warning(
        self, test_config: HassetteConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_startup_tasks() logs each startup warning at WARNING.

        The log line is the warning's only delivery surface, so the logger is the boundary under test;
        the warning text itself is pinned in tests/unit/utils/test_unconfigured_apps.py.
        """
        monkeypatch.setattr(startup_tasks_module, "run_apps_pre_check", Mock())
        write_app(tmp_path, "lights.py", "from hassette import App\n\nclass LightsApp(App): ...\n")

        with preserve_config(test_config):
            test_config.apps.directory = tmp_path
            test_config.apps.apps = {}
            logger = Mock()
            run_startup_tasks(test_config, logger)

        [warning] = [call.args[0] for call in logger.warning.call_args_list]
        assert "[hassette.apps.lights_app]" in warning


class TestStartupTasksAppPrecheck:
    def test_precheck_always_runs(self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_startup_tasks() always calls run_apps_pre_check with the active config."""
        precheck_mock = Mock()
        monkeypatch.setattr(startup_tasks_module, "run_apps_pre_check", precheck_mock)

        run_startup_tasks(test_config, Mock())

        precheck_mock.assert_called_once_with(test_config)

    def test_precheck_failure_reraises_when_not_allowed_to_continue(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_startup_tasks() re-raises AppPrecheckFailedError when allow_startup_if_app_precheck_fails is False."""
        monkeypatch.setattr(
            startup_tasks_module, "run_apps_pre_check", Mock(side_effect=AppPrecheckFailedError("bad app"))
        )

        with preserve_config(test_config):
            test_config.allow_startup_if_app_precheck_fails = False
            with pytest.raises(AppPrecheckFailedError):
                run_startup_tasks(test_config, Mock())

    def test_precheck_failure_continues_when_allowed(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_startup_tasks() swallows AppPrecheckFailedError when allow_startup_if_app_precheck_fails is True."""
        monkeypatch.setattr(
            startup_tasks_module, "run_apps_pre_check", Mock(side_effect=AppPrecheckFailedError("bad app"))
        )

        with preserve_config(test_config):
            test_config.allow_startup_if_app_precheck_fails = True
            run_startup_tasks(test_config, Mock())  # must not raise


class TestRunForeverEdgeCases:
    async def test_skips_loop_watchdog_when_disabled(self, wired_hassette: Hassette) -> None:
        """run_forever() never installs the loop watchdog when watchdog_enabled is False."""
        hassette = wired_hassette
        stub_run_forever_collaborators(hassette)

        with (
            patch("hassette.core.core.start") as mock_start,
            preserve_config(hassette.config),
        ):
            hassette.config.blocking_io.watchdog_enabled = False
            task = asyncio.create_task(hassette.run_forever())
            await wait_for(lambda: mock_start.called, desc="run_forever started")
            hassette.shutdown_event.set()
            await task

        assert hassette._loop_watchdog is None

    async def test_cancelled_during_shutdown_wait_converts_to_graceful_shutdown(self, wired_hassette: Hassette) -> None:
        """run_forever() catches CancelledError while waiting for shutdown and completes without raising."""
        hassette = wired_hassette
        stubs = stub_run_forever_collaborators(hassette)

        with patch("hassette.core.core.start"):
            task = asyncio.create_task(hassette.run_forever())
            await wait_for(lambda: hassette.ready_event.is_set(), desc="run_forever reached the shutdown wait")
            task.cancel()

            # The coroutine swallows CancelledError internally (converts it to graceful shutdown),
            # so awaiting the task must return normally, not raise.
            await task

        assert stubs.shutdown is not None
        stubs.shutdown.assert_awaited()

    async def test_unexpected_exception_during_shutdown_wait_is_logged_and_shuts_down(
        self, wired_hassette: Hassette
    ) -> None:
        """run_forever() logs (not raises) an unexpected exception from shutdown_event.wait()."""
        hassette = wired_hassette
        stubs = stub_run_forever_collaborators(hassette)
        hassette.shutdown_event.wait = AsyncMock(side_effect=RuntimeError("event loop primitive broke"))
        error_mock = Mock()
        hassette.logger.error = error_mock

        with patch("hassette.core.core.start"):
            await hassette.run_forever()  # must not raise

        error_mock.assert_called()
        assert stubs.shutdown is not None
        stubs.shutdown.assert_awaited()


class TestSendEventGuards:
    async def test_raises_before_event_stream_service_wired(self, test_config: HassetteConfig) -> None:
        """send_event() raises RuntimeError naming EventStreamService when unwired."""
        hassette = Hassette(test_config)
        with pytest.raises(RuntimeError, match="EventStreamService"):
            await hassette.send_event(Mock(topic="test.topic"))

    async def test_noop_when_streams_closed(self, wired_hassette: Hassette) -> None:
        """send_event() does not forward to the stream service once event streams are closed."""
        stream_service = require_wired(wired_hassette._event_stream_service)
        await stream_service.close_streams()
        assert wired_hassette.event_streams_closed is True

        send_event_mock = AsyncMock()
        stream_service.send_event = send_event_mock

        await wired_hassette.send_event(Mock(topic="test.topic"))

        send_event_mock.assert_not_awaited()


class TestShutdownChildren:
    async def test_records_child_shutdown_failed_and_continues_siblings(self, wired_hassette: Hassette) -> None:
        """_shutdown_children() makes the outcome INCOMPLETE with a reason naming the failed child, but
        still awaits every sibling's shutdown.
        """
        hassette = wired_hassette
        file_watcher = require_wired(hassette._file_watcher)
        for child in hassette.children:
            stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))
        stub_shutdown(file_watcher, AsyncMock(side_effect=RuntimeError("child broke")))

        result = await hassette._shutdown_children()

        assert result.result is ShutdownResult.INCOMPLETE
        assert result.reason == f"{file_watcher.unique_name}'s shutdown raised RuntimeError"
        shutdown_mock(file_watcher).assert_awaited_once()
        for child in hassette.children:
            if child is not file_watcher:
                shutdown_mock(child).assert_awaited_once()

    async def test_merges_child_outcome_when_shutdown_raises(self, wired_hassette: Hassette) -> None:
        """When a child's ``shutdown()`` call raises, its own already-stored ``shutdown_outcome`` (stored by
        ``_run_shutdown_coordinator()``'s ``except Exception`` branch before it re-raises) is merged first,
        so its reason wins over the generic "shutdown raised".
        """
        hassette = wired_hassette
        file_watcher = require_wired(hassette._file_watcher)
        for child in hassette.children:
            stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))
        stub_shutdown(file_watcher, AsyncMock(side_effect=RuntimeError("coordinator boom")))
        file_watcher._shutdown_outcome = incomplete_outcome(
            "FileWatcherService's shutdown coordinator raised RuntimeError"
        )

        result = await hassette._shutdown_children()

        assert result.result is ShutdownResult.INCOMPLETE
        assert result.reason == "FileWatcherService's shutdown coordinator raised RuntimeError"

    async def test_stop_stage_expiry_force_terminates_unfinished_children(self, wired_hassette: Hassette) -> None:
        """When the stop stage's deadline passes, the root walks away: each unfinished stop-stage child is
        force-terminated and named in the stage's ERROR, and the outcome is INCOMPLETE.
        """
        hassette = wired_hassette
        file_watcher = require_wired(hassette._file_watcher)

        stub_child_shutdowns(hassette)
        stub_shutdown(file_watcher, hang)
        hassette._shutdown_deadline = deadline_in(0.3)

        with patch.object(hassette.logger, "error") as log_error:
            result = await hassette._shutdown_children()

        assert result.result is ShutdownResult.INCOMPLETE
        force_terminal_mock(file_watcher).assert_called_once()
        stage_errors = [call.args for call in log_error.call_args_list if "gave up" in call.args[0]]
        assert len(stage_errors) == 1
        assert stage_errors[0][1] == "stop"
        assert file_watcher.class_name in stage_errors[0][-1]

    async def test_foundation_stage_runs_after_stop_stage_expiry(self, wired_hassette: Hassette) -> None:
        """A stop stage that times out still leaves the foundation stage to run: the session is finalized,
        the database and the executor shut down, and the shutdown snapshot is attempted.
        """
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        session_manager = require_wired(hassette._session_manager)
        app_handler = require_wired(hassette._app_handler)
        executor_service = require_wired(hassette._sync_executor_service)

        stub_child_shutdowns(hassette)
        stub_shutdown(app_handler, hang)
        session_manager.finalize_session = AsyncMock()
        db.write_shutdown_snapshot = AsyncMock()
        hassette._shutdown_deadline = deadline_in(0.3)

        result = await hassette._shutdown_children()

        assert result.result is ShutdownResult.INCOMPLETE
        force_terminal_mock(app_handler).assert_called_once()
        session_manager.finalize_session.assert_awaited_once()
        shutdown_mock(db).assert_awaited_once()
        shutdown_mock(executor_service).assert_awaited_once()
        db.write_shutdown_snapshot.assert_awaited_once()

    async def test_foundation_services_are_exactly_the_children_that_opt_out_of_the_hook_timeout(
        self, wired_hassette: Hassette
    ) -> None:
        """Foundation membership is declared twice: in ``_foundation_services()`` and by each class's
        ``shutdown_hook_timeout_applies = False``. The two must name the same children.
        """
        hassette = wired_hassette
        foundation = {id(service) for service in hassette._foundation_services()}

        for child in hassette.children:
            assert (id(child) in foundation) == (not child.shutdown_hook_timeout_applies), child.class_name

    async def test_foundation_stage_runs_when_the_stop_stage_raises(
        self, wired_hassette: Hassette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stop stage that raises still leaves the foundation stage and the snapshot to run."""
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        session_manager = require_wired(hassette._session_manager)
        executor_service = require_wired(hassette._sync_executor_service)
        for child in hassette.children:
            stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))
        monkeypatch.setattr(hassette, "_run_stop_stage", AsyncMock(side_effect=RuntimeError("stage bookkeeping")))
        session_manager.finalize_session = AsyncMock()
        db.write_shutdown_snapshot = AsyncMock()

        with pytest.raises(RuntimeError, match="stage bookkeeping"):
            await hassette._shutdown_children()

        shutdown_mock(db).assert_awaited_once()
        shutdown_mock(executor_service).assert_awaited_once()
        db.write_shutdown_snapshot.assert_awaited_once()

    async def test_foundation_services_are_not_stopped_in_the_stop_stage(self, wired_hassette: Hassette) -> None:
        """The session, database and executor stop only after every stop-stage child has finished."""
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        session_manager = require_wired(hassette._session_manager)
        order: list[str] = []

        def recorder(name: str) -> AsyncMock:
            def record(*_args, **_kwargs) -> ShutdownOutcome:
                order.append(name)
                return ShutdownOutcome()

            return AsyncMock(side_effect=record)

        for child in hassette.children:
            stub_shutdown(child, recorder(child.class_name))
        session_manager.finalize_session = AsyncMock(side_effect=lambda **_k: order.append("finalize"))
        db.write_shutdown_snapshot = AsyncMock(side_effect=lambda: order.append("snapshot"))

        await hassette._shutdown_children()

        tail = ["finalize", "SessionManager", "DatabaseService", "SyncExecutorService", "snapshot"]
        assert order[-len(tail) :] == tail

    async def test_foundation_stage_expiry_still_snapshots(
        self, wired_hassette: Hassette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A foundation step that outlives the foundation budget is walked away from, and the snapshot still runs."""
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        executor_service = require_wired(hassette._sync_executor_service)
        monkeypatch.setattr(core_module, "FOUNDATION_SHUTDOWN_BUDGET_SECONDS", 0.3)

        stub_child_shutdowns(hassette)
        stub_shutdown(db, hang)
        db.write_shutdown_snapshot = AsyncMock()

        result = await hassette._shutdown_children()

        assert result.result is ShutdownResult.INCOMPLETE
        force_terminal_mock(db).assert_called_once()
        force_terminal_mock(executor_service).assert_called_once()
        db.write_shutdown_snapshot.assert_awaited_once()

    async def test_surviving_executor_threads_are_named_in_an_error(
        self, wired_hassette: Hassette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Executor threads still alive after the join are named in one ERROR."""
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        for child in hassette.children:
            stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))
        db.write_shutdown_snapshot = AsyncMock()
        monkeypatch.setattr(hassette._sync_executor, "surviving_threads", lambda: ["hassette-sync_0"])

        with patch.object(hassette.logger, "error") as log_error:
            await hassette._shutdown_children()

        log_error.assert_any_call("Sync executor threads still running after the shutdown join: %s", "hassette-sync_0")

    async def test_foundation_stage_survives_a_raising_session_finalize(self, wired_hassette: Hassette) -> None:
        """A finalize that raises (a full or detached write queue) still leaves the drain, the close, the join
        and the snapshot to run.
        """
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        session_manager = require_wired(hassette._session_manager)
        executor_service = require_wired(hassette._sync_executor_service)
        for child in hassette.children:
            stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))
        session_manager.finalize_session = AsyncMock(side_effect=TimeoutError("queue full"))
        db.write_shutdown_snapshot = AsyncMock()

        await hassette._shutdown_children()

        shutdown_mock(db).assert_awaited_once()
        shutdown_mock(executor_service).assert_awaited_once()
        db.write_shutdown_snapshot.assert_awaited_once()

    async def test_session_finalize_is_capped_at_its_share_of_the_foundation_budget(
        self, wired_hassette: Hassette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A finalize that hangs is cut off at its own cap, leaving the rest of the foundation stage its time."""
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        session_manager = require_wired(hassette._session_manager)
        executor_service = require_wired(hassette._sync_executor_service)
        monkeypatch.setattr(core_module, "SESSION_FINALIZE_TIMEOUT_SECONDS", 0.1)

        stub_child_shutdowns(hassette)
        session_manager.finalize_session = hang
        db.write_shutdown_snapshot = AsyncMock()

        result = await asyncio.wait_for(hassette._shutdown_children(), timeout=5)

        assert result.result is not ShutdownResult.INCOMPLETE
        force_terminal_mock(db).assert_not_called()
        shutdown_mock(db).assert_awaited_once()
        shutdown_mock(executor_service).assert_awaited_once()


class TestRootShutdown:
    async def test_normal_shutdown_sets_stopped_and_completed(self, wired_hassette: Hassette) -> None:
        """shutdown() sets shutdown_completed and STOPPED status on the ordinary (non-timeout) path."""
        hassette = wired_hassette
        for child in hassette.children:
            stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))

        await hassette.shutdown()

        assert hassette.shutdown_completed is True
        assert hassette.status == ResourceStatus.STOPPED
        assert hassette.shutdown_outcome == ShutdownOutcome()

    async def test_stop_stage_deadline_is_total_minus_foundation_budget(
        self, wired_hassette: Hassette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The root's stop-stage deadline is total_shutdown_timeout_seconds minus the foundation budget, and a
        hanging stop-stage child holds shutdown only that long.
        """
        hassette = wired_hassette
        db = require_wired(hassette._database_service)
        file_watcher = require_wired(hassette._file_watcher)
        monkeypatch.setattr(core_module, "FOUNDATION_SHUTDOWN_BUDGET_SECONDS", 0.2)

        stub_child_shutdowns(hassette)
        stub_shutdown(file_watcher, hang)
        db.write_shutdown_snapshot = AsyncMock()

        loop = asyncio.get_running_loop()
        with preserve_config(hassette.config):
            object.__setattr__(
                hassette.config.lifecycle, "total_shutdown_timeout_seconds", TOTAL_SHUTDOWN_TIMEOUT_SECONDS
            )
            start = loop.time()
            outcome = await hassette.shutdown()
            elapsed = loop.time() - start

        assert 0.25 <= elapsed < 3.0, f"shutdown took {elapsed:.2f}s; the stop stage is 0.3s"
        assert outcome.result is ShutdownResult.INCOMPLETE
        assert outcome.is_restart_safe is False
        assert hassette.status == ResourceStatus.STOPPED
        assert hassette.event_streams_closed is True


class TestFinalizeSessionCounterFallback:
    async def test_falls_back_to_zero_counters_when_get_drop_counters_raises(self, wired_hassette: Hassette) -> None:
        """_finalize_session() finalizes the session with (0, 0, 0) if get_drop_counters() raises."""
        hassette = wired_hassette
        session_manager = require_wired(hassette._session_manager)
        command_executor = require_wired(hassette._command_executor)
        command_executor.get_drop_counters = Mock(side_effect=RuntimeError("counters unavailable"))
        session_manager.finalize_session = AsyncMock()

        await hassette._finalize_session()

        session_manager.finalize_session.assert_awaited_once_with(drop_counters=(0, 0, 0))


class TestOnChildrenStopped:
    async def test_emits_stopped_event_and_closes_streams(self, wired_hassette: Hassette) -> None:
        """_on_children_stopped() calls handle_stop() then closes event streams."""
        hassette = wired_hassette
        stream_service = require_wired(hassette._event_stream_service)
        original_close = stream_service.close_streams
        close_streams_mock = AsyncMock()
        stream_service.close_streams = close_streams_mock

        try:
            # handle_stop() is a module-level function (hassette.resources.lifecycle), not a
            # method — patch it at the call site (core.py) rather than reassigning an instance
            # attribute, since _on_children_stopped() calls the free function directly.
            with patch("hassette.core.core.handle_stop") as mock_handle_stop:
                await hassette._on_children_stopped()

                mock_handle_stop.assert_awaited_once_with(hassette)
            close_streams_mock.assert_awaited_once()
        finally:
            stream_service.close_streams = original_close


class TestRecordFatalReason:
    def test_first_reason_wins(self, test_config: HassetteConfig) -> None:
        """record_fatal_reason() keeps the first recorded reason; later calls are ignored."""
        hassette = Hassette(test_config)
        hassette.record_fatal_reason("first failure")
        hassette.record_fatal_reason("second failure")
        assert hassette.fatal_shutdown_reason == "first failure"


class TestRaiseIfFatalShutdown:
    def test_raises_fatal_error_when_reason_recorded(self, test_config: HassetteConfig) -> None:
        """_raise_if_fatal_shutdown() raises FatalError carrying the recorded reason."""
        hassette = Hassette(test_config)
        hassette.record_fatal_reason("boom")
        with pytest.raises(FatalError, match="boom"):
            hassette._raise_if_fatal_shutdown()

    def test_noop_when_no_reason_recorded(self, test_config: HassetteConfig) -> None:
        """_raise_if_fatal_shutdown() is a no-op on a clean shutdown (no fatal reason)."""
        hassette = Hassette(test_config)
        hassette._raise_if_fatal_shutdown()  # must not raise


class TestWiredAccessorsReturnBackingAttribute:
    def test_accessors_return_their_private_backing_attribute(self, wired_hassette: Hassette) -> None:
        """Each service accessor returns exactly the private attribute wire_services() set, once wired.

        session_id is exercised separately (via test_hassette_lifecycle.py's before-wiring raise
        and integration tests that create a real session) — wire_services() alone does not create
        a session, so accessing it here would raise "Session ID is not initialized".
        """
        hassette = wired_hassette
        assert hassette.states is hassette._states
        assert hassette.state_registry is hassette._state_registry
        assert hassette.type_registry is hassette._type_registry
        assert hassette.app_handler is hassette._app_handler
        assert hassette.api_service is hassette._api_service
        assert hassette.session_manager is hassette._session_manager
        assert hassette.event_stream_service is hassette._event_stream_service
        assert hassette.bus is hassette._bus


class TestTryStateProxy:
    def test_returns_real_proxy_once_wired(self, wired_hassette: Hassette) -> None:
        """try_state_proxy() returns the actual StateProxy instance once wire_services() has run."""
        assert wired_hassette.try_state_proxy() is wired_hassette._state_proxy


async def hang(*_args, **_kwargs) -> None:
    """Stand-in for a shutdown step that never finishes."""
    await asyncio.sleep(1000)


def stub_child_shutdowns(hassette: Hassette) -> None:
    """Make every child's shutdown a no-op and its force-termination observable."""
    for child in hassette.children:
        stub_shutdown(child, AsyncMock(return_value=ShutdownOutcome()))
        child._force_terminal = Mock()


def require_wired(service: T | None) -> T:
    """Narrow a service ``wire_services()`` sets, failing the test if it is still unwired."""
    assert service is not None
    return service


def stub_shutdown(resource: Resource, stub: Callable[..., Awaitable[object]]) -> None:
    """Replace ``resource.shutdown`` (final on ``Resource``) so a test can observe or stall teardown."""
    resource.shutdown = stub  # pyright: ignore[reportAttributeAccessIssue]


def shutdown_mock(resource: Resource) -> AsyncMock:
    """The ``AsyncMock`` a test installed as ``resource.shutdown`` via ``stub_shutdown``."""
    return cast("AsyncMock", resource.shutdown)


def force_terminal_mock(resource: Resource) -> Mock:
    """The ``Mock`` ``stub_child_shutdowns`` installed as ``resource._force_terminal``."""
    return cast("Mock", resource._force_terminal)
