"""Unit tests filling coverage gaps in ServiceWatcher.

Complements test_service_watcher_exhausted.py (handle_exhaustion/cooldown_and_retry
status-setting) and tests/integration/test_service_watcher.py (restart_service branch
coverage via a real bus-backed watcher). This file targets the remaining branches:
listener registration, the BusService-recovery gate, on_service_running's early-return
guards, cooldown abort/failure paths, and service lookup.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.bus_service import BusService
from hassette.events import HassetteServiceEvent
from hassette.exceptions import RestartRefusedError
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.test_utils import make_mock_hassette, make_service_failed_event, make_service_running_event, wait_for
from hassette.test_utils.helpers import PLACEHOLDER_SERVICE_NAME, make_crashed_event
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import ResourceRole, RestartType

from .conftest import DummyService, make_watcher, make_watcher_hassette


def make_unsafe_restart_refused_error(resource_name: str = PLACEHOLDER_SERVICE_NAME) -> RestartRefusedError:
    """Build a RestartRefusedError carrying a real UNSAFE TeardownReport, for refusal tests."""
    report = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,), failed_operations=("shutdown_hooks",))
    return RestartRefusedError(resource_name, report)


class TestConfigLogLevel:
    def test_reads_service_watcher_logging_level(self) -> None:
        """config_log_level reflects hassette.config.logging.service_watcher."""
        hassette = make_mock_hassette(sealed=False, logging={"service_watcher": "WARNING"})
        watcher = make_watcher(hassette)

        assert watcher.config_log_level == "WARNING"


class TestOnInitialize:
    async def test_marks_ready_and_registers_listeners(self) -> None:
        """on_initialize() registers listeners then marks the watcher ready."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)

        watcher.register_internal_event_listeners = AsyncMock()

        assert not watcher.ready_event.is_set()

        await watcher.on_initialize()

        watcher.register_internal_event_listeners.assert_awaited_once()
        assert watcher.ready_event.is_set()


class TestRegisterInternalEventListeners:
    async def test_registers_five_listeners_with_correct_status_filters(self) -> None:
        """Registers restart/shutdown/log/running/bus-recovery handlers on the correct statuses."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)

        await watcher.register_internal_event_listeners()

        assert watcher.bus.on.await_count == 5
        registered_by_name = {call.kwargs["name"]: call.kwargs for call in watcher.bus.on.await_args_list}

        topic = str(Topic.HASSETTE_EVENT_SERVICE_STATUS)
        expected_names = {
            "hassette.service_watcher.restart_service": watcher.restart_service,
            "hassette.service_watcher.shutdown_if_crashed": watcher.shutdown_if_crashed,
            "hassette.service_watcher.log_service_event": watcher.log_service_event,
            "hassette.service_watcher.on_service_running": watcher.on_service_running,
            "hassette.service_watcher.on_bus_service_running": watcher.on_bus_service_running,
        }

        assert set(registered_by_name) == set(expected_names)
        for name, handler in expected_names.items():
            call_kwargs = registered_by_name[name]
            assert call_kwargs["topic"] == topic
            assert call_kwargs["handler"] == handler

        # log_service_event listens unconditionally (no `where` filter); the rest are status-gated.
        assert registered_by_name["hassette.service_watcher.log_service_event"].get("where") is None
        assert registered_by_name["hassette.service_watcher.restart_service"].get("where") is not None
        assert registered_by_name["hassette.service_watcher.shutdown_if_crashed"].get("where") is not None
        assert registered_by_name["hassette.service_watcher.on_service_running"].get("where") is not None
        assert registered_by_name["hassette.service_watcher.on_bus_service_running"].get("where") is not None


def make_running_event(
    previous_status: ResourceStatus, resource_name: str = PLACEHOLDER_SERVICE_NAME
) -> HassetteServiceEvent:
    """Build a RUNNING HassetteServiceEvent with a given previous_status, for log_service_event tests."""
    return HassetteServiceEvent.from_service_status(
        resource_name=resource_name,
        role=ResourceRole.SERVICE,
        status=ResourceStatus.RUNNING,
        previous_status=previous_status,
        ready=True,
    )


class TestLogServiceEvent:
    """log_service_event has no side effect beyond logging — assert the collaborator call
    itself (mocked logger), matching the existing codebase convention (e.g.
    test_web_ui_watcher.py's `watcher.logger.warning.assert_called_once()`), not log output
    content via caplog.
    """

    async def test_skips_logging_when_status_unchanged(self) -> None:
        """No transition (status == previous_status) logs at debug without a transition message."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.logger = Mock()

        event = make_running_event(previous_status=ResourceStatus.RUNNING)

        await watcher.log_service_event(event)

        watcher.logger.debug.assert_called_once()
        # The unchanged-status path is a single "not logging" debug call, not a transition log.
        assert watcher.logger.debug.call_count == 1

    async def test_logs_transition_when_status_changed(self) -> None:
        """A real transition logs once at debug (the transition message)."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.logger = Mock()

        event = make_running_event(previous_status=ResourceStatus.STARTING)

        await watcher.log_service_event(event)

        watcher.logger.debug.assert_called_once()
        call_args = watcher.logger.debug.call_args
        # Distinguish from the unchanged-status branch: the transition message carries both statuses.
        assert ResourceStatus.RUNNING in call_args.args
        assert ResourceStatus.STARTING in call_args.args


class TestOnBusServiceRunning:
    async def test_ignores_non_bus_service_events(self) -> None:
        """Events for a resource other than BusService do not trigger reconciliation."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.reconcile_after_bus_recovery = AsyncMock()

        dummy = DummyService(hassette)
        event = make_service_running_event(dummy)  # resource_name == "DummyService"

        await watcher.on_bus_service_running(event)

        watcher.reconcile_after_bus_recovery.assert_not_called()

    async def test_triggers_reconciliation_for_bus_service(self) -> None:
        """A RUNNING event for BusService itself triggers the reconciliation scan."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.reconcile_after_bus_recovery = AsyncMock()

        event = make_running_event(
            resource_name=BusService.__name__,
            previous_status=ResourceStatus.STARTING,
        )

        await watcher.on_bus_service_running(event)

        watcher.reconcile_after_bus_recovery.assert_awaited_once()


class TestOnServiceRunningEarlyReturns:
    async def test_returns_early_when_no_budget_and_not_restarting(self) -> None:
        """A RUNNING event for a service with no budget entry and no in-progress restart is a no-op."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        event = make_service_running_event(dummy)

        with patch.object(dummy, "wait_ready", side_effect=AssertionError("should not be called")):
            await watcher.on_service_running(event)

        # No budget was created as a side effect.
        key = watcher.service_key(dummy.class_name, dummy.role)
        assert key not in watcher._budgets

    async def test_returns_early_when_service_not_found(self) -> None:
        """A RUNNING event for a service no longer present in hassette.children is a no-op."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        # Budget exists (so the first guard passes) but the service itself is gone.
        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._budgets[key] = watcher.get_budget(key, dummy.restart_spec)
        hassette.children = []

        event = make_service_running_event(dummy)

        # Must not raise despite the service being absent.
        await watcher.on_service_running(event)


class TestCooldownAndRetry:
    async def test_aborts_without_restart_when_shutdown_requested(self) -> None:
        """cooldown_and_retry does not attempt a restart if shutdown fires during the cooldown sleep."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=5.0, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)

        hassette.shutdown_event.set()

        # restart() is a module-level function (hassette.resources.operations), not a
        # method — patch it at the call site (service_watcher.py) rather than reassigning
        # an instance attribute, since cooldown_and_retry() calls the free function directly.
        with patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart:
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

            mock_restart.assert_not_called()

    async def test_restart_exception_after_cooldown_is_caught(self) -> None:
        """A service.restart() failure after cooldown is logged, not propagated."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=0.001, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)

        with patch(
            "hassette.core.service_watcher.restart", side_effect=RuntimeError("restart blew up")
        ) as mock_restart:
            # Should not raise even though restart() failed.
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

            mock_restart.assert_awaited_once_with(dummy)

    async def test_skips_restart_when_service_gone_after_cooldown(self) -> None:
        """If the service disappears during cooldown, restart is skipped without error."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        hassette.children = []

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=0.001, max_cooldown_cycles=0)

        # Should not raise despite no matching service.
        await watcher.cooldown_and_retry("GoneService", "Service", "GoneService:Service", spec)


class TestGetService:
    def test_returns_the_matching_service(self) -> None:
        """get_service resolves a child by class_name/role."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        assert watcher.get_service(dummy.class_name, dummy.role) is dummy

    def test_returns_none_when_no_match(self) -> None:
        """get_service returns None rather than an empty collection when nothing matches."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        hassette.children = [DummyService(hassette)]

        assert watcher.get_service("GoneService", ResourceRole.SERVICE) is None

    def test_ignores_non_service_children(self) -> None:
        """A non-Service child sharing the name is not returned."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        not_a_service = MagicMock()
        not_a_service.class_name = "DummyService"
        not_a_service.role = ResourceRole.SERVICE
        hassette.children = [not_a_service]

        assert watcher.get_service("DummyService", ResourceRole.SERVICE) is None


class TestRestartServiceNoServiceFound:
    async def test_returns_early_without_side_effects(self) -> None:
        """restart_service for a resource_name with no matching child is a no-op."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        hassette.children = []

        dummy = DummyService(hassette)
        event = make_service_failed_event(dummy)

        await watcher.restart_service(event)

        hassette.send_event.assert_not_called()
        key = watcher.service_key(dummy.class_name, dummy.role)
        assert key not in watcher._budgets


class TestShutdownIfCrashed:
    async def test_reason_omits_exception_type_when_none(self) -> None:
        """When exception_type is falsy, the fatal reason has no ': <type>' suffix."""
        hassette = make_watcher_hassette()
        hassette.record_fatal_reason = Mock()
        watcher = make_watcher(hassette)

        event = make_crashed_event(exception=None, exception_type=None, exception_traceback=None)

        with patch("hassette.core.service_watcher.request_shutdown"):
            await watcher.shutdown_if_crashed(event)

        hassette.record_fatal_reason.assert_called_once_with(f"service '{PLACEHOLDER_SERVICE_NAME}' crashed")

    async def test_reraises_on_unexpected_internal_failure(self) -> None:
        """If record_fatal_reason itself raises, shutdown_if_crashed logs and re-raises."""
        hassette = make_watcher_hassette()
        hassette.record_fatal_reason = Mock(side_effect=RuntimeError("state corrupted"))
        watcher = make_watcher(hassette)

        event = make_crashed_event(exception="boom", exception_type="RuntimeError", exception_traceback=None)

        with patch("hassette.core.service_watcher.request_shutdown") as mock_request_shutdown:
            with pytest.raises(RuntimeError, match="state corrupted"):
                await watcher.shutdown_if_crashed(event)

            # The failure happened before request_shutdown was reached.
            mock_request_shutdown.assert_not_called()


class TestOnServiceRunningBudgetNoneBranch:
    async def test_clears_in_restart_flag_without_creating_budget(self) -> None:
        """A RUNNING event while restarting (but with no budget entry yet) clears the flag,
        without fabricating a budget.
        """
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        mark_ready(dummy, reason="test")
        hassette.children = [dummy]

        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._restarting.add(key)
        assert key not in watcher._budgets

        event = make_service_running_event(dummy)
        await watcher.on_service_running(event)
        await wait_for(lambda: key not in watcher._restarting, desc="await_service_readiness completed")

        assert key not in watcher._restarting
        assert key not in watcher._budgets


class TestReconcileAfterBusRecoverySkips:
    async def test_skips_non_service_children(self) -> None:
        """Non-Service children (e.g. plain resources) are ignored by the reconciliation scan."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.restart_service = AsyncMock()

        not_a_service = MagicMock()
        hassette.children = [not_a_service]

        await watcher.reconcile_after_bus_recovery()

        watcher.restart_service.assert_not_called()

    async def test_skips_services_not_in_failed_state(self) -> None:
        """Services that are not FAILED are left alone."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.restart_service = AsyncMock()

        dummy = DummyService(hassette)
        dummy._status = ResourceStatus.RUNNING
        hassette.children = [dummy]

        await watcher.reconcile_after_bus_recovery()

        watcher.restart_service.assert_not_called()

    async def test_skips_failed_services_with_existing_budget(self) -> None:
        """A FAILED service that already has a budget entry was handled normally — skip it."""
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.restart_service = AsyncMock()

        dummy = DummyService(hassette)
        dummy._status = ResourceStatus.FAILED
        hassette.children = [dummy]

        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._budgets[key] = watcher.get_budget(key, dummy.restart_spec)

        await watcher.reconcile_after_bus_recovery()

        watcher.restart_service.assert_not_called()


class TestRestartAdmissionBlocked:
    def test_false_when_no_fatal_reason_and_no_shutdown(self) -> None:
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)

        assert watcher.restart_admission_blocked() is False

    def test_true_when_fatal_reason_recorded(self) -> None:
        hassette = make_watcher_hassette()
        hassette.fatal_shutdown_reason = "already fatal"
        watcher = make_watcher(hassette)

        assert watcher.restart_admission_blocked() is True

    def test_true_when_shutdown_requested(self) -> None:
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        hassette.shutdown_event.set()

        assert watcher.restart_admission_blocked() is True


class TestHandleRestartRefused:
    async def test_records_fatal_reason_with_resource_identity(self) -> None:
        """The fatal reason names the role/name that refused, matching the sibling
        handle_exhaustion/restart_service fatal-reason conventions.
        """
        hassette = make_watcher_hassette()
        # record_fatal_reason must be a sync Mock, not the hassette AsyncMock's auto-child --
        # calling an unawaited AsyncMock child here would leak a never-awaited coroutine (see
        # the identical pattern in TestShutdownIfCrashed above).
        hassette.record_fatal_reason = Mock()
        watcher = make_watcher(hassette)
        error = make_unsafe_restart_refused_error(PLACEHOLDER_SERVICE_NAME)

        with patch("hassette.core.service_watcher.request_shutdown"):
            await watcher.handle_restart_refused(PLACEHOLDER_SERVICE_NAME, ResourceRole.SERVICE, error)

        hassette.record_fatal_reason.assert_called_once()
        reason = hassette.record_fatal_reason.call_args.args[0]
        assert PLACEHOLDER_SERVICE_NAME in reason

    async def test_requests_shutdown_not_full_hassette_shutdown(self) -> None:
        """The refusal handler must call request_shutdown(), never hassette.shutdown() inline --
        run_forever() must own root teardown, not this handler.
        """
        hassette = make_watcher_hassette()
        hassette.record_fatal_reason = Mock()
        watcher = make_watcher(hassette)
        error = make_unsafe_restart_refused_error()

        with patch("hassette.core.service_watcher.request_shutdown") as mock_request_shutdown:
            await watcher.handle_restart_refused(PLACEHOLDER_SERVICE_NAME, ResourceRole.SERVICE, error)

        mock_request_shutdown.assert_called_once()
        hassette.shutdown.assert_not_called()

    async def test_sends_one_crashed_event_with_refusal_exception_fields(self) -> None:
        hassette = make_watcher_hassette()
        hassette.record_fatal_reason = Mock()
        watcher = make_watcher(hassette)
        error = make_unsafe_restart_refused_error(PLACEHOLDER_SERVICE_NAME)

        with patch("hassette.core.service_watcher.request_shutdown"):
            await watcher.handle_restart_refused(PLACEHOLDER_SERVICE_NAME, ResourceRole.SERVICE, error)

        hassette.send_event.assert_awaited_once()
        sent_event = hassette.send_event.call_args.args[0]
        assert sent_event.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS
        assert sent_event.payload.data.status == ResourceStatus.CRASHED
        assert sent_event.payload.data.resource_name == PLACEHOLDER_SERVICE_NAME
        assert sent_event.payload.data.exception_type == "RestartRefusedError"
        assert sent_event.payload.data.exception is not None
        assert PLACEHOLDER_SERVICE_NAME in sent_event.payload.data.exception

    async def test_event_dispatch_failure_does_not_undo_fatal_reason_or_shutdown(self) -> None:
        """Event dispatch is telemetry, not the control path -- its failure must not undo the
        already-recorded fatal reason or shutdown request, and must not raise out of the
        handler.
        """
        hassette = make_watcher_hassette()
        hassette.record_fatal_reason = Mock()
        hassette.send_event = AsyncMock(side_effect=RuntimeError("bus dead"))
        watcher = make_watcher(hassette)
        error = make_unsafe_restart_refused_error()

        with patch("hassette.core.service_watcher.request_shutdown") as mock_request_shutdown:
            # Must not raise despite send_event failing.
            await watcher.handle_restart_refused(PLACEHOLDER_SERVICE_NAME, ResourceRole.SERVICE, error)

        hassette.record_fatal_reason.assert_called_once()
        mock_request_shutdown.assert_called_once()


class TestExecuteRestartCatchesRefusal:
    async def test_catches_restart_refused_and_escalates(self) -> None:
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]
        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._restarting.add(key)
        budget = watcher.get_budget(key, dummy.restart_spec)
        budget.record_restart()

        error = make_unsafe_restart_refused_error(dummy.class_name)
        watcher.handle_restart_refused = AsyncMock()

        with patch("hassette.core.service_watcher.restart", side_effect=error):
            await watcher.execute_restart(dummy.class_name, dummy.role, key, dummy.restart_spec, dummy, budget)

        watcher.handle_restart_refused.assert_awaited_once_with(dummy.class_name, dummy.role, error)
        # The in-restart guard is released only after the refusal handler returns.
        assert key not in watcher._restarting

    async def test_skips_restart_when_admission_blocked_at_entry(self) -> None:
        hassette = make_watcher_hassette()
        hassette.fatal_shutdown_reason = "already fatal"
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._restarting.add(key)
        budget = watcher.get_budget(key, dummy.restart_spec)

        with patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart:
            await watcher.execute_restart(dummy.class_name, dummy.role, key, dummy.restart_spec, dummy, budget)

        mock_restart.assert_not_called()
        assert key not in watcher._restarting

    async def test_skips_restart_when_admission_blocked_after_backoff(self) -> None:
        """A fatal reason recorded during the backoff sleep (an await point) must still stop
        the restart() call that follows it.
        """
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._restarting.add(key)
        budget = watcher.get_budget(key, RestartSpec(backoff_base_seconds=1.0))
        budget.record_restart()

        async def block_after_backoff(_duration: float) -> bool:
            hassette.fatal_shutdown_reason = "fatal mid-backoff"
            return True

        with (
            patch.object(watcher, "shutdown_safe_sleep", side_effect=block_after_backoff),
            patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart,
        ):
            await watcher.execute_restart(
                dummy.class_name, dummy.role, key, RestartSpec(backoff_base_seconds=1.0), dummy, budget
            )

        mock_restart.assert_not_called()
        assert key not in watcher._restarting


class TestCooldownAndRetryCatchesRefusal:
    async def test_catches_restart_refused_and_escalates(self) -> None:
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]
        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=0.001, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)

        error = make_unsafe_restart_refused_error(dummy.class_name)
        watcher.handle_restart_refused = AsyncMock()

        with patch("hassette.core.service_watcher.restart", side_effect=error):
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

        watcher.handle_restart_refused.assert_awaited_once_with(dummy.class_name, dummy.role, error)

    async def test_skips_when_admission_blocked_at_entry(self) -> None:
        """Blocked at entry: the cooldown cycle counter must not even be incremented."""
        hassette = make_watcher_hassette()
        hassette.shutdown_event.set()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=999, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)

        with patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart:
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

        mock_restart.assert_not_called()
        assert key not in watcher._cooldown_cycles

    async def test_skips_budget_reset_when_admission_blocked_after_sleep(self) -> None:
        """Fatal admission closing during the cooldown sleep must stop the budget reset too,
        not just the restart() call.
        """
        hassette = make_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]
        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=0.001, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)
        budget = watcher.get_budget(key, spec)
        budget.record_restart()

        async def block_after_sleep(_duration: float) -> bool:
            hassette.fatal_shutdown_reason = "fatal mid-sleep"
            return True

        with (
            patch.object(watcher, "shutdown_safe_sleep", side_effect=block_after_sleep),
            patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart,
        ):
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

        mock_restart.assert_not_called()
        budget.evict_expired()
        assert len(budget._timestamps) == 1, "budget must not be reset once admission is blocked"


class TestRestartServiceAdmissionBlocked:
    async def test_skips_entirely_when_admission_blocked(self) -> None:
        hassette = make_watcher_hassette()
        hassette.fatal_shutdown_reason = "already fatal"
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]
        event = make_service_failed_event(dummy)

        await watcher.restart_service(event)

        hassette.send_event.assert_not_called()
        key = watcher.service_key(dummy.class_name, dummy.role)
        assert key not in watcher._budgets
        assert key not in watcher._restarting
