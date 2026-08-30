"""Coverage-focused unit tests for Hassette (core.py).

Targets branches not already exercised by test_hassette_lifecycle.py (unit) and
tests/integration/test_core.py (integration): startup_tasks() precheck/env-file
branches, on_initialize() timeout warnings, send_event()'s guard branches,
_shutdown_children()'s exception/timeout branches, shutdown()'s total-timeout
wrapper, _on_children_stopped(), and several one-line accessors/helpers.
"""

import asyncio
import logging
import queue
from contextlib import contextmanager, suppress
from unittest.mock import AsyncMock, Mock, patch

import pytest
from anyio import ClosedResourceError

import hassette.core.core as core_module
from hassette import context
from hassette.config.config import HassetteConfig
from hassette.core.core import Hassette
from hassette.exceptions import AppPrecheckFailedError, FatalError
from hassette.logging_ import HassetteQueueHandler, LogPersistenceHandler
from hassette.resources.base import Resource
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.test_utils import preserve_config, wait_for
from hassette.types.enums import ResourceStatus
from hassette.utils.url_utils import build_rest_url, build_ws_url

# wire_services() creates anyio memory streams that are closed explicitly in the
# fixture teardown. However, pytest holds internal references to fixture results,
# so the Hassette object's refcount doesn't reach zero until a later GC cycle.
# When GC finalizes it, anyio's MemoryObject.__del__ fires a ResourceWarning for
# streams that were closed but whose owning object wasn't yet collected. This is
# a CPython GC nondeterminism issue, not a real leak — the streams ARE closed.
pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning:anyio")


@pytest.fixture
async def wired_hassette(test_config: HassetteConfig):
    """A fully-wired Hassette instance for accessor/delegation tests.

    wire_services() creates three anyio memory streams. All are closed
    explicitly below. See pytestmark for the ResourceWarning scoping.
    """
    test_config.reload()
    instance = Hassette(test_config)
    instance.wire_services()
    try:
        yield instance
    finally:
        with suppress(ClosedResourceError):
            if not instance._bus_service.stream._closed:
                await instance._bus_service.stream.aclose()
        with suppress(ClosedResourceError):
            if not instance._event_stream_service.event_streams_closed:
                await instance._event_stream_service.close_streams()


class TestUrlProperties:
    def test_ws_url_delegates_to_build_ws_url(self, test_config: HassetteConfig) -> None:
        """ws_url returns the same value as calling build_ws_url(config) directly."""
        h = Hassette(test_config)
        assert h.ws_url == build_ws_url(test_config)

    def test_rest_url_delegates_to_build_rest_url(self, test_config: HassetteConfig) -> None:
        """rest_url returns the same value as calling build_rest_url(config) directly."""
        h = Hassette(test_config)
        assert h.rest_url == build_rest_url(test_config)


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
        wired_hassette._command_executor.get_drop_counters = Mock(return_value=(1, 2, 3))
        assert wired_hassette.get_drop_counters() == (1, 2, 3)

    def test_get_error_handler_failures_delegates_to_command_executor(self, wired_hassette: Hassette) -> None:
        """get_error_handler_failures() returns exactly what command_executor.get_error_handler_failures() returns."""
        wired_hassette._command_executor.get_error_handler_failures = Mock(return_value=5)
        assert wired_hassette.get_error_handler_failures() == 5


class TestGetLogDropCounters:
    def test_returns_zero_before_logging_service_wired(self, test_config: HassetteConfig) -> None:
        """Both counters return 0 when _logging_service is None (pre-wiring)."""
        h = Hassette(test_config)
        assert h.get_log_queue_drops() == 0
        assert h.get_db_write_queue_drops() == 0

    async def test_db_write_queue_drops_from_persistence_handler(self, wired_hassette: Hassette) -> None:
        """get_db_write_queue_drops() forwards real persistence-handler DB queue drops."""
        db_service = Mock()
        db_service._insert_log_records = Mock(return_value=object())
        db_service.enqueue = Mock(return_value=False)
        handler = LogPersistenceHandler(db_service, asyncio.get_running_loop())
        record = logging.LogRecord("hassette", logging.INFO, "", 0, "message", (), None)

        handler.emit(record)
        handler.flush_if_pending()
        await asyncio.sleep(0)

        wired_hassette._logging_service.persistence_handler = handler
        assert wired_hassette.get_db_write_queue_drops() == 1

    def test_log_queue_drops_from_queue_handler(self, wired_hassette: Hassette) -> None:
        """get_log_queue_drops() forwards real log-queue drops, not DB write drops."""
        handler = HassetteQueueHandler(queue.Queue(maxsize=1))
        handler.enqueue(logging.LogRecord("hassette", logging.INFO, "", 0, "first", (), None))
        handler.enqueue(logging.LogRecord("hassette", logging.INFO, "", 0, "dropped", (), None))

        wired_hassette._logging_service._queue_handler = handler
        assert wired_hassette.get_log_queue_drops() == 1
        assert wired_hassette.get_db_write_queue_drops() == 0


class TestIsLogPersistenceActive:
    def test_returns_false_before_logging_service_wired(self, test_config: HassetteConfig) -> None:
        """is_log_persistence_active() is False when _logging_service is None (pre-wiring)."""
        h = Hassette(test_config)
        assert h.is_log_persistence_active() is False

    def test_forwards_logging_service_persistence_active(self, wired_hassette: Hassette) -> None:
        """is_log_persistence_active() forwards the logging service's persistence_active."""
        assert wired_hassette.is_log_persistence_active() is False

        wired_hassette._logging_service.persistence_handler = Mock()
        wired_hassette._logging_service._queue_listener = Mock()
        assert wired_hassette.is_log_persistence_active() is True


class TestStartupTasksEnvFiles:
    def test_skips_loading_env_files_when_disabled(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """startup_tasks() never calls load_dotenv when import_dot_env_files is False."""
        load_dotenv_mock = Mock()
        monkeypatch.setattr(core_module, "load_dotenv", load_dotenv_mock)

        with preserve_config(test_config):
            test_config.import_dot_env_files = False
            test_config.run_app_precheck = False
            h = Hassette(test_config)
            h.startup_tasks()

        load_dotenv_mock.assert_not_called()


class TestStartupTasksAppPrecheck:
    def test_precheck_disabled_never_runs_precheck(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """startup_tasks() does not call run_apps_pre_check when run_app_precheck is False."""
        precheck_mock = Mock()
        monkeypatch.setattr(core_module, "run_apps_pre_check", precheck_mock)

        with preserve_config(test_config):
            test_config.run_app_precheck = False
            h = Hassette(test_config)
            h.startup_tasks()

        precheck_mock.assert_not_called()

    def test_precheck_failure_reraises_when_not_allowed_to_continue(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """startup_tasks() re-raises AppPrecheckFailedError when allow_startup_if_app_precheck_fails is False."""
        monkeypatch.setattr(core_module, "run_apps_pre_check", Mock(side_effect=AppPrecheckFailedError("bad app")))

        with preserve_config(test_config):
            test_config.run_app_precheck = True
            test_config.allow_startup_if_app_precheck_fails = False
            h = Hassette(test_config)
            with pytest.raises(AppPrecheckFailedError):
                h.startup_tasks()

    def test_precheck_failure_continues_when_allowed(
        self, test_config: HassetteConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """startup_tasks() swallows AppPrecheckFailedError when allow_startup_if_app_precheck_fails is True."""
        monkeypatch.setattr(core_module, "run_apps_pre_check", Mock(side_effect=AppPrecheckFailedError("bad app")))

        with preserve_config(test_config):
            test_config.run_app_precheck = True
            test_config.allow_startup_if_app_precheck_fails = True
            h = Hassette(test_config)
            h.startup_tasks()  # must not raise


class TestRunForeverEdgeCases:
    async def test_skips_loop_watchdog_when_disabled(self, wired_hassette: Hassette) -> None:
        """run_forever() never installs the loop watchdog when watchdog_enabled is False."""
        h = wired_hassette
        h.wait_for_ready = AsyncMock(return_value=True)
        h._session_manager.mark_orphaned_sessions = AsyncMock()
        h._session_manager.create_session = AsyncMock()
        h.shutdown = AsyncMock()

        # start() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (core.py) rather than reassigning instance
        # attributes, since run_forever() calls the free function directly for every child.
        with (
            patch("hassette.core.core.start") as mock_start,
            preserve_config(h.config),
        ):
            h.config.blocking_io.watchdog_enabled = False
            task = asyncio.create_task(h.run_forever())
            await wait_for(lambda: mock_start.called, desc="run_forever started")
            h.shutdown_event.set()
            await task

        assert h._loop_watchdog is None

    async def test_cancelled_during_shutdown_wait_converts_to_graceful_shutdown(self, wired_hassette: Hassette) -> None:
        """run_forever() catches CancelledError while waiting for shutdown and completes without raising."""
        h = wired_hassette
        h.wait_for_ready = AsyncMock(return_value=True)
        h._session_manager.mark_orphaned_sessions = AsyncMock()
        h._session_manager.create_session = AsyncMock()
        h.shutdown = AsyncMock()

        with patch("hassette.core.core.start"):
            task = asyncio.create_task(h.run_forever())
            await wait_for(lambda: h.ready_event.is_set(), desc="run_forever reached the shutdown wait")
            task.cancel()

            # The coroutine swallows CancelledError internally (converts it to graceful shutdown),
            # so awaiting the task must return normally, not raise.
            await task

        h.shutdown.assert_awaited()

    async def test_unexpected_exception_during_shutdown_wait_is_logged_and_shuts_down(
        self, wired_hassette: Hassette
    ) -> None:
        """run_forever() logs (not raises) an unexpected exception from shutdown_event.wait()."""
        h = wired_hassette
        h.wait_for_ready = AsyncMock(return_value=True)
        h._session_manager.mark_orphaned_sessions = AsyncMock()
        h._session_manager.create_session = AsyncMock()
        h.shutdown = AsyncMock()
        h.shutdown_event.wait = AsyncMock(side_effect=RuntimeError("event loop primitive broke"))
        error_mock = Mock()
        h.logger.error = error_mock

        with patch("hassette.core.core.start"):
            await h.run_forever()  # must not raise

        error_mock.assert_called()
        h.shutdown.assert_awaited()


class TestSendEventGuards:
    async def test_raises_before_event_stream_service_wired(self, test_config: HassetteConfig) -> None:
        """send_event() raises RuntimeError naming EventStreamService when unwired."""
        h = Hassette(test_config)
        with pytest.raises(RuntimeError, match="EventStreamService"):
            await h.send_event(Mock(topic="test.topic"))

    async def test_noop_when_streams_closed(self, wired_hassette: Hassette) -> None:
        """send_event() does not forward to the stream service once event streams are closed."""
        await wired_hassette._event_stream_service.close_streams()
        assert wired_hassette.event_streams_closed is True

        send_event_mock = AsyncMock()
        wired_hassette._event_stream_service.send_event = send_event_mock

        await wired_hassette.send_event(Mock(topic="test.topic"))

        send_event_mock.assert_not_awaited()


class TestShutdownChildren:
    async def test_records_child_shutdown_failed_and_continues_siblings(self, wired_hassette: Hassette) -> None:
        """_shutdown_children() logs a per-child failure, records CHILD_SHUTDOWN_FAILED and the
        child's identity in the aggregated report, but still awaits every sibling's shutdown.
        """
        h = wired_hassette
        for child in h.children:
            child.shutdown = AsyncMock()
        h._file_watcher.shutdown = AsyncMock(side_effect=RuntimeError("child broke"))
        error_mock = Mock()
        h.logger.error = error_mock

        result = await h._shutdown_children()

        assert TeardownCause.CHILD_SHUTDOWN_FAILED in result.causes
        assert h._file_watcher.unique_name in result.affected_resources
        h._file_watcher.shutdown.assert_awaited_once()
        for child in h.children:
            if child is not h._file_watcher:
                child.shutdown.assert_awaited_once()
        error_mock.assert_called()

    async def test_merges_child_report_when_shutdown_raises(self, wired_hassette: Hassette) -> None:
        """When a child's ``shutdown()`` call raises, its own already-stored ``teardown_report``
        (e.g. ``COORDINATOR_FAILED``, stored by ``_run_shutdown_coordinator()``'s
        ``except Exception`` branch before it re-raises) must be merged into the parent's
        aggregated report -- not dropped in favor of only the generic ``CHILD_SHUTDOWN_FAILED``
        cause.
        """
        h = wired_hassette
        for child in h.children:
            child.shutdown = AsyncMock()
        h._file_watcher.shutdown = AsyncMock(side_effect=RuntimeError("coordinator boom"))
        h._file_watcher._teardown_report = TeardownReport(
            causes=(TeardownCause.COORDINATOR_FAILED,), failed_operations=("_run_shutdown_coordinator",)
        )

        result = await h._shutdown_children()

        assert TeardownCause.CHILD_SHUTDOWN_FAILED in result.causes
        assert TeardownCause.COORDINATOR_FAILED in result.causes, (
            "child's own stored cause must be merged into the parent"
        )
        assert "_run_shutdown_coordinator" in result.failed_operations
        assert h._file_watcher.unique_name in result.affected_resources

    async def test_force_terminates_wave_on_timeout_and_records_timed_out_cause(self, wired_hassette: Hassette) -> None:
        """_shutdown_children() force-terminates the timed-out wave's children and records
        CHILD_SHUTDOWN_TIMED_OUT on the aggregated report.
        """
        h = wired_hassette

        async def hang(*_args, **_kwargs):
            await asyncio.sleep(1000)

        for child in h.children:
            child.shutdown = AsyncMock()
            child._force_terminal = Mock()
        h._file_watcher.shutdown = hang

        with preserve_config(h.config):
            # 0.5s still triggers force-termination with 10x+ margin over the hanging
            # child's 1000s sleep, while giving CI scheduling jitter enough headroom.
            h.config.lifecycle.resource_shutdown_timeout_seconds = 0.5
            result = await h._shutdown_children()

        assert TeardownCause.CHILD_SHUTDOWN_TIMED_OUT in result.causes
        h._file_watcher._force_terminal.assert_called_once()

    async def test_wave_timeout_does_not_abandon_later_waves(self, wired_hassette: Hassette) -> None:
        """A wave that times out force-terminates its own children and records evidence, but
        the loop must still proceed to every remaining (lower-dependency) wave.

        Regression test: ``_shutdown_children()`` used to ``return`` immediately on the first
        wave timeout, silently abandoning every wave below it -- including the last wave, which
        owns real OS resources (the sync-executor thread pool, DB connections, the HTTP
        session). AppHandler depends (transitively) on everything else, so it shuts down in the
        first wave; SyncExecutorService and DatabaseService have no dependencies, so they shut
        down in the very last wave. Hanging AppHandler must not prevent those from ever being
        asked to shut down.
        """
        h = wired_hassette

        async def hang(*_args, **_kwargs):
            await asyncio.sleep(1000)

        for child in h.children:
            child.shutdown = AsyncMock()
            child._force_terminal = Mock()
        h._app_handler.shutdown = hang

        with preserve_config(h.config):
            h.config.lifecycle.resource_shutdown_timeout_seconds = 0.5
            result = await h._shutdown_children()

        assert TeardownCause.CHILD_SHUTDOWN_TIMED_OUT in result.causes
        h._app_handler._force_terminal.assert_called_once()
        h._sync_executor_service.shutdown.assert_awaited_once()
        h._database_service.shutdown.assert_awaited_once()


@contextmanager
def hanging_shutdown_body(h: Hassette, total_shutdown_timeout_seconds: float):
    """Patch ``Resource._shutdown_body()`` to hang forever and set a short total-shutdown
    timeout, so tests can exercise the coordinator's force-terminal path deterministically.

    Patches ``_shutdown_body()``, not ``shutdown()``: ``shutdown()`` is the ``@final``
    coordinator front door (``coordinate_shutdown()``) that itself enforces the timeout being
    tested here. Hassette doesn't override ``shutdown()``, only ``_shutdown_body()`` — patching
    ``Resource.shutdown`` would replace ``h.shutdown()``'s own entry point (and every child's)
    with the hang, bypassing the total-timeout enforcement entirely instead of exercising it.
    """

    async def hang_forever(_self):
        await asyncio.sleep(1000)

    with (
        patch.object(Resource, "_shutdown_body", new=hang_forever),
        preserve_config(h.config),
    ):
        h.config.lifecycle.total_shutdown_timeout_seconds = total_shutdown_timeout_seconds
        yield


class TestShutdownTotalTimeout:
    async def test_forces_all_children_terminal_when_super_shutdown_times_out(self, wired_hassette: Hassette) -> None:
        """shutdown() force-terminates every child if the wrapped super().shutdown() exceeds the total timeout."""
        h = wired_hassette
        for child in h.children:
            child._force_terminal = Mock()

        with hanging_shutdown_body(h, total_shutdown_timeout_seconds=0.05):
            await h.shutdown()

        assert h.shutdown_completed is True
        assert h.status == ResourceStatus.STOPPED
        for child in h.children:
            child._force_terminal.assert_called_once()

    async def test_normal_shutdown_sets_stopped_and_completed(self, wired_hassette: Hassette) -> None:
        """shutdown() sets shutdown_completed and STOPPED status on the ordinary (non-timeout) path."""
        h = wired_hassette
        for child in h.children:
            child.shutdown = AsyncMock()

        await h.shutdown()

        assert h.shutdown_completed is True
        assert h.status == ResourceStatus.STOPPED

    async def test_total_timeout_report_has_total_timeout_and_forced_terminal_causes(
        self, wired_hassette: Hassette
    ) -> None:
        """shutdown() returns/stores a report with ``is_restart_safe`` ``False`` with TOTAL_TIMEOUT
        and FORCED_TERMINAL causes when the total shutdown timeout fires, while still closing
        event streams via the existing fallback.
        """
        h = wired_hassette
        for child in h.children:
            child._force_terminal = Mock()

        # 0.5s (with the 0.9 ROOT_SHUTDOWN_BODY_TIMEOUT_FRACTION) still gives the body
        # ~450ms to win its race against the coordinator's outer wait, matching the
        # sibling test's precedent for real-world CI scheduling jitter headroom.
        with hanging_shutdown_body(h, total_shutdown_timeout_seconds=0.5):
            report = await h.shutdown()

        assert report.is_restart_safe is False
        assert TeardownCause.TOTAL_TIMEOUT in report.causes
        assert TeardownCause.FORCED_TERMINAL in report.causes
        assert h.teardown_report == report
        assert h.event_streams_closed is True

    async def test_total_timeout_stores_report_before_force_terminating_children(
        self, wired_hassette: Hassette
    ) -> None:
        """Root timeout evidence is stored on the resource's own teardown report before
        descendants are force-finalized, so a caller observing mid-force-terminal already
        sees ``is_restart_safe`` ``False`` rather than an absent report.
        """
        h = wired_hassette
        observed_unsafe_before_force: list[bool] = []

        def record_and_force() -> None:
            report = h._teardown_report
            observed_unsafe_before_force.append(report is not None and not report.is_restart_safe)

        for child in h.children:
            child._force_terminal = Mock(side_effect=record_and_force)

        # 0.5s (with the 0.9 ROOT_SHUTDOWN_BODY_TIMEOUT_FRACTION) still gives the body
        # ~450ms to win its race against the coordinator's outer wait, matching the
        # sibling test's precedent for real-world CI scheduling jitter headroom.
        with hanging_shutdown_body(h, total_shutdown_timeout_seconds=0.5):
            await h.shutdown()

        assert observed_unsafe_before_force, "no children were force-terminated"
        assert all(observed_unsafe_before_force), (
            "root's own teardown report must be stored (UNSAFE) before force-finalizing descendants"
        )


class TestBeforeShutdownCounterFallback:
    async def test_falls_back_to_zero_counters_when_get_drop_counters_raises(self, wired_hassette: Hassette) -> None:
        """before_shutdown() finalizes the session with (0, 0, 0) if get_drop_counters() raises."""
        h = wired_hassette
        h._command_executor.get_drop_counters = Mock(side_effect=RuntimeError("counters unavailable"))
        h._session_manager.finalize_session = AsyncMock()

        await h.before_shutdown()

        h._session_manager.finalize_session.assert_awaited_once_with(drop_counters=(0, 0, 0))


class TestOnChildrenStopped:
    async def test_emits_stopped_event_and_closes_streams(self, wired_hassette: Hassette) -> None:
        """_on_children_stopped() calls handle_stop() then closes event streams."""
        h = wired_hassette
        original_close = h._event_stream_service.close_streams
        close_streams_mock = AsyncMock()
        h._event_stream_service.close_streams = close_streams_mock

        try:
            # handle_stop() is a module-level function (hassette.resources.lifecycle), not a
            # method — patch it at the call site (core.py) rather than reassigning an instance
            # attribute, since _on_children_stopped() calls the free function directly.
            with patch("hassette.core.core.handle_stop") as mock_handle_stop:
                await h._on_children_stopped()

                mock_handle_stop.assert_awaited_once_with(h)
            close_streams_mock.assert_awaited_once()
        finally:
            h._event_stream_service.close_streams = original_close


class TestRecordFatalReason:
    def test_first_reason_wins(self, test_config: HassetteConfig) -> None:
        """record_fatal_reason() keeps the first recorded reason; later calls are ignored."""
        h = Hassette(test_config)
        h.record_fatal_reason("first failure")
        h.record_fatal_reason("second failure")
        assert h.fatal_shutdown_reason == "first failure"


class TestRaiseIfFatalShutdown:
    def test_raises_fatal_error_when_reason_recorded(self, test_config: HassetteConfig) -> None:
        """_raise_if_fatal_shutdown() raises FatalError carrying the recorded reason."""
        h = Hassette(test_config)
        h.record_fatal_reason("boom")
        with pytest.raises(FatalError, match="boom"):
            h._raise_if_fatal_shutdown()

    def test_noop_when_no_reason_recorded(self, test_config: HassetteConfig) -> None:
        """_raise_if_fatal_shutdown() is a no-op on a clean shutdown (no fatal reason)."""
        h = Hassette(test_config)
        h._raise_if_fatal_shutdown()  # must not raise


class TestWiredAccessorsReturnBackingAttribute:
    def test_accessors_return_their_private_backing_attribute(self, wired_hassette: Hassette) -> None:
        """Each service accessor returns exactly the private attribute wire_services() set, once wired.

        session_id is exercised separately (via test_hassette_lifecycle.py's before-wiring raise
        and integration tests that create a real session) — wire_services() alone does not create
        a session, so accessing it here would raise "Session ID is not initialized".
        """
        h = wired_hassette
        assert h.states is h._states
        assert h.state_registry is h._state_registry
        assert h.type_registry is h._type_registry
        assert h.app_handler is h._app_handler
        assert h.api_service is h._api_service
        assert h.session_manager is h._session_manager
        assert h.event_stream_service is h._event_stream_service
        assert h.bus is h._bus


class TestTryStateProxy:
    def test_returns_real_proxy_once_wired(self, wired_hassette: Hassette) -> None:
        """try_state_proxy() returns the actual StateProxy instance once wire_services() has run."""
        assert wired_hassette.try_state_proxy() is wired_hassette._state_proxy
