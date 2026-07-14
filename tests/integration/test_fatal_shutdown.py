"""Integration tests for fatal-exit observability.

Verifies the full run_forever() → FatalError exit path using the real Hassette
instance fixture, and that session telemetry is finalized before the raise.

- Fatal-driven shutdown causes run_forever() to raise FatalError.
- Clean operator shutdown exits 0 (run_forever() returns normally).
- Session row carries failure status, written before teardown completes.

Project rule: no log-capture tests. Assert on FatalError / return value / DB row only.
"""

import typing
from unittest.mock import AsyncMock, Mock, patch

import pytest

from hassette import Hassette
from hassette.core.session_manager import SESSION_STATUS_FAILURE, SESSION_STATUS_SUCCESS
from hassette.exceptions import FatalError


class TestRunForeverFatalOnCrash:
    """run_forever() raises FatalError when _fatal_shutdown_reason is set on exit."""

    async def test_run_forever_raises_fatal_error_when_reason_set(self, hassette_instance: Hassette):
        """When _fatal_shutdown_reason is set before shutdown completes, run_forever() raises FatalError."""
        hassette_instance.wait_for_ready = AsyncMock(return_value=True)
        hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock()
        hassette_instance.session_manager.create_session = AsyncMock()
        hassette_instance.session_manager.cleanup_stale_once_listeners = AsyncMock()
        hassette_instance.shutdown = AsyncMock()

        # Set fatal reason then trigger shutdown — simulates what shutdown_if_crashed does
        def trigger_fatal_shutdown(*_args, **_kwargs):
            hassette_instance.record_fatal_reason("BusService crashed: RuntimeError")
            hassette_instance.shutdown_event.set()

        hassette_instance.session_manager.cleanup_stale_once_listeners.side_effect = trigger_fatal_shutdown

        # start() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (core.py) so real children never spawn.
        with patch("hassette.core.core.start"), pytest.raises(FatalError):
            await hassette_instance.run_forever()

    async def test_run_forever_returns_normally_on_clean_shutdown(self, hassette_instance: Hassette):
        """When no fatal reason is set, run_forever() returns normally (exit 0 path)."""
        hassette_instance.wait_for_ready = AsyncMock(return_value=True)
        hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock()
        hassette_instance.session_manager.create_session = AsyncMock()
        hassette_instance.session_manager.cleanup_stale_once_listeners = AsyncMock()
        hassette_instance.shutdown = AsyncMock()

        def trigger_clean_shutdown(*_args, **_kwargs):
            # No fatal reason — clean operator shutdown
            hassette_instance.shutdown_event.set()

        hassette_instance.session_manager.cleanup_stale_once_listeners.side_effect = trigger_clean_shutdown

        # start() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (core.py) so real children never spawn.
        with patch("hassette.core.core.start"):
            # Must return normally, not raise
            await hassette_instance.run_forever()
        assert hassette_instance.fatal_shutdown_reason is None

    async def test_run_forever_raises_fatal_on_session_init_failure(self, hassette_instance: Hassette):
        """Startup failure in session init branch raises FatalError."""
        hassette_instance.wait_for_ready = AsyncMock(return_value=True)
        hassette_instance.shutdown = AsyncMock()
        hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock(side_effect=RuntimeError("db broke"))
        hassette_instance.session_manager.create_session = AsyncMock()

        # start() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (core.py) so real children never spawn.
        with patch("hassette.core.core.start"), pytest.raises(FatalError):
            await hassette_instance.run_forever()

        assert hassette_instance.fatal_shutdown_reason is not None

    async def test_run_forever_raises_fatal_on_resource_startup_failure(self, hassette_instance: Hassette):
        """Startup failure (resources not ready) branch raises FatalError."""
        # DB wait succeeds, wave wait fails
        hassette_instance.wait_for_ready = AsyncMock(side_effect=[True, False])
        hassette_instance.shutdown = AsyncMock()
        hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock()
        hassette_instance.session_manager.create_session = AsyncMock()

        # start() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (core.py) so real children never spawn.
        with patch("hassette.core.core.start"), pytest.raises(FatalError):
            await hassette_instance.run_forever()

        assert hassette_instance.fatal_shutdown_reason is not None


class TestSessionTelemetryOrdering:
    """Session finalization happens before FatalError is raised."""

    async def test_session_finalized_before_fatal_raise(self, hassette_instance: Hassette):
        """finalize_session is called before FatalError propagates out of run_forever().

        The ordering guarantee: shutdown_event.set() → shutdown_event.wait() unblocks →
        finally: await self.shutdown() → before_shutdown() → finalize_session() →
        shutdown complete → _raise_if_fatal_shutdown() raises FatalError.
        """
        finalize_calls: list[str] = []

        hassette_instance.wait_for_ready = AsyncMock(return_value=True)
        hassette_instance.session_manager.mark_orphaned_sessions = AsyncMock()
        hassette_instance.session_manager.create_session = AsyncMock()
        hassette_instance.session_manager.cleanup_stale_once_listeners = AsyncMock()
        hassette_instance.session_manager.finalize_session = AsyncMock(
            side_effect=lambda **_kw: finalize_calls.append("finalized")
        )

        original_shutdown = hassette_instance.shutdown

        async def tracking_shutdown():
            await original_shutdown()

        hassette_instance.shutdown = tracking_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        def trigger_fatal_shutdown(*_args, **_kwargs):
            hassette_instance.record_fatal_reason("BusService crashed")
            hassette_instance.shutdown_event.set()

        hassette_instance.session_manager.cleanup_stale_once_listeners.side_effect = trigger_fatal_shutdown

        # start() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (core.py) so real children never spawn.
        with patch("hassette.core.core.start"), pytest.raises(FatalError):
            await hassette_instance.run_forever()

        assert finalize_calls == ["finalized"], (
            "finalize_session must be called (session persisted) before FatalError is raised"
        )


class TestFinalizePersistsFatalFailure:
    """finalize_session persists a failure status when a fatal reason is set.

    Regression for the persistence race: on a real fatal crash, the async on_service_crashed
    handler may not record the failure before finalize runs during teardown. finalize must use the
    synchronously-set _fatal_shutdown_reason so the crash is not masked as a clean 'success'.
    """

    async def test_finalize_writes_failure_when_fatal_reason_set(self, hassette_instance: Hassette):
        """With a fatal reason set and no _session_error, finalize writes SESSION_STATUS_FAILURE."""
        sm = hassette_instance.session_manager
        sm._session_id = 7  # coordinator-internal
        sm._session_error = False  # coordinator-internal — the async CRASHED handler did NOT win the race
        hassette_instance.record_fatal_reason("Service 'BusService' restart budget exhausted (PERMANENT)")

        sm._database_service = Mock()  # coordinator-internal
        sm._database_service.db = AsyncMock()  # coordinator-internal
        sm._database_service.is_db_ready = True  # coordinator-internal

        async def run_submitted(coro: typing.Any) -> None:
            await coro

        sm._database_service.submit = run_submitted  # coordinator-internal

        await sm.finalize_session()

        # The finalize UPDATE must set status = 'failure', carrying the fatal reason as error_message.
        execute_calls = sm._database_service.db.execute.await_args_list  # coordinator-internal
        assert execute_calls, "finalize should have issued an UPDATE"
        params = execute_calls[-1].args[1]
        assert SESSION_STATUS_FAILURE in params, f"finalize must persist a failure status, got params {params!r}"
        assert hassette_instance.fatal_shutdown_reason in params

    async def test_finalize_writes_success_when_no_fatal_reason(self, hassette_instance: Hassette):
        """A clean shutdown (no fatal reason, no _session_error) still finalizes as 'success'."""
        sm = hassette_instance.session_manager
        sm._session_id = 8  # coordinator-internal
        sm._session_error = False  # coordinator-internal
        hassette_instance._fatal_shutdown_reason = None  # coordinator-internal — no public reset method exists

        sm._database_service = Mock()  # coordinator-internal
        sm._database_service.db = AsyncMock()  # coordinator-internal
        sm._database_service.is_db_ready = True  # coordinator-internal

        async def run_submitted(coro: typing.Any) -> None:
            await coro

        sm._database_service.submit = run_submitted  # coordinator-internal

        await sm.finalize_session()

        params = sm._database_service.db.execute.await_args_list[-1].args[1]  # coordinator-internal
        assert SESSION_STATUS_SUCCESS in params
        assert SESSION_STATUS_FAILURE not in params
