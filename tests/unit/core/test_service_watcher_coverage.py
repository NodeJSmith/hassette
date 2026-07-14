"""Unit tests filling coverage gaps in ServiceWatcher.

Complements test_service_watcher_exhausted.py (handle_exhaustion/cooldown_and_retry
status-setting) and tests/integration/test_service_watcher.py (restart_service branch
coverage via a real bus-backed watcher). This file targets the remaining branches:
listener registration, the BusService-recovery gate, on_service_running's early-return
guards, cooldown abort/failure paths, and the multiple-services-found warning path.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.bus_service import BusService
from hassette.events import HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import RestartSpec
from hassette.test_utils import make_mock_hassette, make_service_failed_event, make_service_running_event, wait_for
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import ResourceRole, RestartType

from .conftest import DummyService, build_watcher_hassette, make_watcher


class TestConfigLogLevel:
    def test_reads_service_watcher_logging_level(self) -> None:
        """config_log_level reflects hassette.config.logging.service_watcher."""
        hassette = make_mock_hassette(sealed=False, logging={"service_watcher": "WARNING"})
        watcher = make_watcher(hassette)

        assert watcher.config_log_level == "WARNING"


class TestOnInitialize:
    async def test_marks_ready_and_registers_listeners(self) -> None:
        """on_initialize() registers listeners then marks the watcher ready."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)

        # boundary-exempt: collaborator of on_initialize
        watcher.register_internal_event_listeners = AsyncMock()

        assert not watcher.ready_event.is_set()

        await watcher.on_initialize()

        watcher.register_internal_event_listeners.assert_awaited_once()
        assert watcher.ready_event.is_set()


class TestRegisterInternalEventListeners:
    async def test_registers_five_listeners_with_correct_status_filters(self) -> None:
        """Registers restart/shutdown/log/running/bus-recovery handlers on the correct statuses."""
        hassette = build_watcher_hassette()
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


class TestLogServiceEvent:
    """log_service_event has no side effect beyond logging — assert the collaborator call
    itself (mocked logger), matching the existing codebase convention (e.g.
    test_web_ui_watcher.py's `watcher.logger.warning.assert_called_once()`), not log output
    content via caplog.
    """

    async def test_skips_logging_when_status_unchanged(self) -> None:
        """No transition (status == previous_status) logs at debug without a transition message."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.logger = Mock()

        payload = ServiceStatusPayload(
            resource_name="SomeService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            previous_status=ResourceStatus.RUNNING,
            ready=True,
            ready_phase=None,
        )
        event = HassetteServiceEvent(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, payload=HassettePayload(data=payload))

        await watcher.log_service_event(event)

        watcher.logger.debug.assert_called_once()
        # The unchanged-status path is a single "not logging" debug call, not a transition log.
        assert watcher.logger.debug.call_count == 1

    async def test_logs_transition_when_status_changed(self) -> None:
        """A real transition logs once at debug (the transition message)."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.logger = Mock()

        payload = ServiceStatusPayload(
            resource_name="SomeService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            previous_status=ResourceStatus.STARTING,
            ready=True,
            ready_phase=None,
        )
        event = HassetteServiceEvent(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, payload=HassettePayload(data=payload))

        await watcher.log_service_event(event)

        watcher.logger.debug.assert_called_once()
        call_args = watcher.logger.debug.call_args
        # Distinguish from the unchanged-status branch: the transition message carries both statuses.
        assert ResourceStatus.RUNNING in call_args.args
        assert ResourceStatus.STARTING in call_args.args


class TestOnBusServiceRunning:
    async def test_ignores_non_bus_service_events(self) -> None:
        """Events for a resource other than BusService do not trigger reconciliation."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.reconcile_after_bus_recovery = AsyncMock()  # boundary-exempt: collaborator of on_bus_service_running

        dummy = DummyService(hassette)
        event = make_service_running_event(dummy)  # resource_name == "DummyService"

        await watcher.on_bus_service_running(event)

        watcher.reconcile_after_bus_recovery.assert_not_called()

    async def test_triggers_reconciliation_for_bus_service(self) -> None:
        """A RUNNING event for BusService itself triggers the reconciliation scan."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.reconcile_after_bus_recovery = AsyncMock()  # boundary-exempt: collaborator of on_bus_service_running

        payload = ServiceStatusPayload(
            resource_name=BusService.__name__,
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            previous_status=ResourceStatus.STARTING,
            ready=True,
            ready_phase=None,
        )
        event = HassetteServiceEvent(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, payload=HassettePayload(data=payload))

        await watcher.on_bus_service_running(event)

        watcher.reconcile_after_bus_recovery.assert_awaited_once()


class TestOnServiceRunningEarlyReturns:
    async def test_returns_early_when_no_budget_and_not_restarting(self) -> None:
        """A RUNNING event for a service with no budget entry and no in-progress restart is a no-op."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        event = make_service_running_event(dummy)

        # branch-isolation: wait_ready set to fail loudly — proves early return before reaching it
        with patch.object(dummy, "wait_ready", side_effect=AssertionError("should not be called")):
            await watcher.on_service_running(event)

        # No budget was created as a side effect.
        key = watcher.service_key(dummy.class_name, dummy.role)
        assert key not in watcher._budgets

    async def test_returns_early_when_service_not_found(self) -> None:
        """A RUNNING event for a service no longer present in hassette.children is a no-op."""
        hassette = build_watcher_hassette()
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
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=5.0, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)

        hassette.shutdown_event.set()

        # restart() is a module-level function (hassette.resources.operations), not a
        # method — patch it at the call site (service_watcher.py) rather than reassigning
        # an instance attribute, since cooldown_and_retry() calls the free function directly.
        # boundary-exempt: collaborator of cooldown_and_retry
        with patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart:
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

            mock_restart.assert_not_called()

    async def test_restart_exception_after_cooldown_is_caught(self) -> None:
        """A service.restart() failure after cooldown is logged, not propagated."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        dummy = DummyService(hassette)
        hassette.children = [dummy]

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=0.001, max_cooldown_cycles=0)
        key = watcher.service_key(dummy.class_name, dummy.role)

        # branch-isolation: restart forced to raise for cooldown_and_retry error path
        # boundary-exempt: collaborator of cooldown_and_retry
        with patch(
            "hassette.core.service_watcher.restart", side_effect=RuntimeError("restart blew up")
        ) as mock_restart:
            # Should not raise even though restart() failed.
            await watcher.cooldown_and_retry(dummy.class_name, dummy.role, key, spec)

            mock_restart.assert_awaited_once_with(dummy)

    async def test_skips_restart_when_service_gone_after_cooldown(self) -> None:
        """If the service disappears during cooldown, restart is skipped without error."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        hassette.children = []

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, cooldown_seconds=0.001, max_cooldown_cycles=0)

        # Should not raise despite no matching service.
        await watcher.cooldown_and_retry("GoneService", "Service", "GoneService:Service", spec)


class TestRestartServiceMultipleMatches:
    async def test_restarts_all_matching_services_and_warns(self) -> None:
        """When two services share class_name/role, restart_service restarts both and warns."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.logger = Mock()

        svc_a = DummyService(hassette)
        svc_b = DummyService(hassette)
        hassette.children = [svc_a, svc_b]

        spec = RestartSpec(restart_type=RestartType.TRANSIENT, backoff_base_seconds=0, budget_intensity=10)
        svc_a.restart_spec = spec  # pyright: ignore[reportAttributeAccessIssue]

        event = make_service_failed_event(svc_a)

        # restart() is a module-level function (hassette.resources.operations), not a
        # method — patch it at the call site (service_watcher.py) rather than reassigning
        # instance attributes, since execute_restart() calls the free function directly.
        # boundary-exempt: collaborator of execute_restart
        with patch("hassette.core.service_watcher.restart", new_callable=AsyncMock) as mock_restart:
            await watcher.restart_service(event)
            key = watcher.service_key(svc_a.class_name, svc_a.role)
            await wait_for(lambda: key not in watcher._restarting, desc="execute_restart completed")

            mock_restart.assert_any_await(svc_a)
            mock_restart.assert_any_await(svc_b)
            assert mock_restart.await_count == 2
        watcher.logger.warning.assert_called_once()


class TestRestartServiceNoServiceFound:
    async def test_returns_early_without_side_effects(self) -> None:
        """restart_service for a resource_name with no matching child is a no-op."""
        hassette = build_watcher_hassette()
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
        hassette = build_watcher_hassette()
        hassette.record_fatal_reason = Mock()
        watcher = make_watcher(hassette)

        payload = ServiceStatusPayload(
            resource_name="SomeService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.CRASHED,
            previous_status=ResourceStatus.FAILED,
            exception=None,
            exception_type=None,
            exception_traceback=None,
            ready=False,
            ready_phase=None,
        )
        event = HassetteServiceEvent(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, payload=HassettePayload(data=payload))

        # boundary-exempt: collaborator of shutdown_if_crashed
        with patch("hassette.core.service_watcher.request_shutdown"):
            await watcher.shutdown_if_crashed(event)

        hassette.record_fatal_reason.assert_called_once_with("service 'SomeService' crashed")

    async def test_reraises_on_unexpected_internal_failure(self) -> None:
        """If record_fatal_reason itself raises, shutdown_if_crashed logs and re-raises."""
        hassette = build_watcher_hassette()
        hassette.record_fatal_reason = Mock(side_effect=RuntimeError("state corrupted"))
        watcher = make_watcher(hassette)

        payload = ServiceStatusPayload(
            resource_name="SomeService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.CRASHED,
            previous_status=ResourceStatus.FAILED,
            exception="boom",
            exception_type="RuntimeError",
            exception_traceback=None,
            ready=False,
            ready_phase=None,
        )
        event = HassetteServiceEvent(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, payload=HassettePayload(data=payload))

        # boundary-exempt: collaborator of shutdown_if_crashed
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
        hassette = build_watcher_hassette()
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
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.restart_service = AsyncMock()  # boundary-exempt: collaborator of reconcile_after_bus_recovery

        not_a_service = MagicMock()
        hassette.children = [not_a_service]

        await watcher.reconcile_after_bus_recovery()

        watcher.restart_service.assert_not_called()

    async def test_skips_services_not_in_failed_state(self) -> None:
        """Services that are not FAILED are left alone."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.restart_service = AsyncMock()  # boundary-exempt: collaborator of reconcile_after_bus_recovery

        dummy = DummyService(hassette)
        dummy._status = ResourceStatus.RUNNING
        hassette.children = [dummy]

        await watcher.reconcile_after_bus_recovery()

        watcher.restart_service.assert_not_called()

    async def test_skips_failed_services_with_existing_budget(self) -> None:
        """A FAILED service that already has a budget entry was handled normally — skip it."""
        hassette = build_watcher_hassette()
        watcher = make_watcher(hassette)
        watcher.restart_service = AsyncMock()  # boundary-exempt: collaborator of reconcile_after_bus_recovery

        dummy = DummyService(hassette)
        dummy._status = ResourceStatus.FAILED
        hassette.children = [dummy]

        key = watcher.service_key(dummy.class_name, dummy.role)
        watcher._budgets[key] = watcher.get_budget(key, dummy.restart_spec)

        await watcher.reconcile_after_bus_recovery()

        watcher.restart_service.assert_not_called()
