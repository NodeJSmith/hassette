"""Unit tests for AppLifecycleService instance initialization.

Covers ``initialize_instances``/``initialize_instance``: the STARTING/RUNNING writes and their events,
failed-init shutdown and flagging, and skipping an instance process exit reached first. Shutdown,
walk-away and registration-removal tests live in test_app_lifecycle_service_instances.py.
"""

import asyncio
import logging
import typing
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from hassette_wire import ResourceStatus

from hassette.core import app_lifecycle_instances
from hassette.core.app_lifecycle_common import STOPPED_BEFORE_INIT_REASON
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.resources.shutdown_outcome import ShutdownOutcome
from hassette.schemas.app_outcomes import OutcomeResult
from hassette.testing import EventCapture
from tests.support.app_registry_helpers import seed_failed, seed_running
from tests.support.outcomes import AnyNameOutcomes

from .conftest import (
    app_state_payloads,
    failure_writes,
    make_mock_app_instance,
)

if TYPE_CHECKING:
    from hassette.app.app import App


async def initialize_with_mark_ready_patched(
    service: AppLifecycleService, instances: "dict[str, App]", manifest: MagicMock
) -> MagicMock:
    """Run ``initialize_instances`` for ``test_app`` with ``mark_ready`` patched out, returning the patch."""
    with patch("hassette.core.app_lifecycle_instances.mark_ready") as mock_mark_ready:
        await service.initialize_instances("test_app", instances, manifest, outcomes=AnyNameOutcomes())
    return mock_mark_ready


class TestInitializeInstances:
    async def test_success_calls_initialize_and_mark_ready(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_manifest: MagicMock
    ) -> None:
        """Calls initialize() and mark_ready() on each instance."""
        instances: dict[str, App] = {"test_instance": mock_app_instance}

        mock_mark_ready = await initialize_with_mark_ready_patched(lifecycle_service, instances, mock_manifest)

        mock_app_instance.initialize.assert_awaited_once()
        mock_mark_ready.assert_called_once_with(mock_app_instance, reason="initialized")

    async def test_multiple_instances(self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock) -> None:
        """Initializes all provided instances."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")
        instances: dict[str, App] = {app1.app_config.instance_name: app1, app2.app_config.instance_name: app2}

        mock_mark_ready = await initialize_with_mark_ready_patched(lifecycle_service, instances, mock_manifest)

        app1.initialize.assert_awaited_once()
        app2.initialize.assert_awaited_once()
        assert mock_mark_ready.call_args_list == [
            call(app1, reason="initialized"),
            call(app2, reason="initialized"),
        ]

    @pytest.mark.parametrize("error", [TimeoutError("Timed out"), ValueError("Init failed")], ids=["timeout", "raise"])
    async def test_failed_init_shuts_the_instance_down_and_records_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
        error: Exception,
    ) -> None:
        """A failed or timed-out init shuts the instance down with its own hooks skipped, then records the
        init exception as its failure.
        """
        mock_app_instance.initialize.side_effect = error
        instances: dict[str, App] = {"test_instance": mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest, outcomes=AnyNameOutcomes())

        mock_app_instance.shutdown.assert_awaited_once()
        assert mock_app_instance._skip_own_shutdown_hooks is True
        [write] = failure_writes(mock_registry)
        assert write.args[:2] == ("test_app", "test_instance")
        assert write.kwargs["error"] is error
        assert write.kwargs.get("needs_restart") is None

    async def test_failed_init_whose_work_may_still_run_is_flagged(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """An init whose teardown left its initializer pending is FAILED and flagged needs-restart."""
        mock_app_instance.initialize.side_effect = TimeoutError("Timed out")
        mock_app_instance.shutdown = AsyncMock(return_value=ShutdownOutcome(still_running=("resource:initialize:app",)))
        instances: dict[str, App] = {"test_instance": mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest, outcomes=AnyNameOutcomes())

        [write] = failure_writes(mock_registry)
        assert write.args[:2] == ("test_app", "test_instance")
        assert write.kwargs["needs_restart"] is not None

    # dup-ignore-start: pytest test function signature
    async def test_failed_init_event_is_failed_from_starting(
        self,
        real_registry_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """STARTING is sent before init; no STOPPING event is sent for a failed init, and FAILED comes from STARTING."""
        event_capture.install(mock_hassette)
        mock_app_instance.initialize.side_effect = ValueError("boom")
        seed_running(real_registry_service.registry, "test_app", mock_app_instance, status=ResourceStatus.NOT_STARTED)

        await real_registry_service.initialize_instances(
            "test_app", {"test_instance": mock_app_instance}, mock_manifest, outcomes=AnyNameOutcomes()
        )

        starting = app_state_payloads(event_capture, ResourceStatus.STARTING)
        assert [p.previous_status for p in starting] == [ResourceStatus.NOT_STARTED]
        assert app_state_payloads(event_capture, ResourceStatus.STOPPING) == []
        failed = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert [p.previous_status for p in failed] == [ResourceStatus.STARTING]

    @pytest.mark.parametrize(
        "exit_reaches_second",
        [
            pytest.param(
                lambda registry: registry.set_status("test_app", "second", ResourceStatus.STOPPING), id="stopping"
            ),
            pytest.param(
                lambda registry: registry.set_status("test_app", "second", ResourceStatus.STOPPED), id="stopped"
            ),
        ],
    )
    async def test_a_sibling_exit_reached_first_is_not_initialized(
        self,
        real_registry_service: AppLifecycleService,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
        exit_reaches_second: typing.Callable[[typing.Any], object],
    ) -> None:
        """Process exit starts stopping a sibling during an earlier one's init: it fails, never initialized."""
        event_capture.install(mock_hassette)
        registry = real_registry_service.registry
        first = make_mock_app_instance(instance_name="first")
        second = make_mock_app_instance(instance_name="second")
        registry.set_status("test_app", "first", ResourceStatus.NOT_STARTED, app=first)
        registry.set_status("test_app", "second", ResourceStatus.NOT_STARTED, app=second)

        async def first_init_while_exit_reaches_second() -> None:
            exit_reaches_second(registry)

        first.initialize.side_effect = first_init_while_exit_reaches_second
        outcomes = AnyNameOutcomes()

        with patch.object(app_lifecycle_instances, "mark_ready"):
            await real_registry_service.initialize_instances(
                "test_app", {"first": first, "second": second}, mock_manifest, outcomes=outcomes
            )

        second.initialize.assert_not_called()
        by_name = {o.instance_name: o for o in outcomes.snapshot()}
        assert by_name["second"].result is OutcomeResult.FAILED
        assert by_name["second"].reason == STOPPED_BEFORE_INIT_REASON
        assert [p.instance_name for p in app_state_payloads(event_capture, ResourceStatus.STARTING)] == ["first"]

    async def test_a_sibling_flagged_before_its_turn_is_refused_without_a_warning(
        self,
        real_registry_service: AppLifecycleService,
        mock_manifest: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A sibling flagged needs-restart during an earlier one's init is refused, and no refused write is logged."""
        registry = real_registry_service.registry
        first = make_mock_app_instance(instance_name="first")
        second = make_mock_app_instance(instance_name="second")
        registry.set_status("test_app", "first", ResourceStatus.NOT_STARTED, app=first)
        registry.set_status("test_app", "second", ResourceStatus.NOT_STARTED, app=second)

        async def first_init_while_exit_flags_second() -> None:
            seed_failed(registry, "test_app", "second", needs_restart="work still running")

        first.initialize.side_effect = first_init_while_exit_flags_second
        outcomes = AnyNameOutcomes()

        with patch.object(app_lifecycle_instances, "mark_ready"), caplog.at_level(logging.WARNING):
            await real_registry_service.initialize_instances(
                "test_app", {"first": first, "second": second}, mock_manifest, outcomes=outcomes
            )

        second.initialize.assert_not_called()
        by_name = {o.instance_name: o for o in outcomes.snapshot()}
        assert by_name["second"].result is OutcomeResult.REFUSED
        assert not [r for r in caplog.records if "flagged needs-restart" in r.getMessage()]

    async def test_a_failed_running_event_is_logged_and_the_app_keeps_running(
        self,
        lifecycle_service: AppLifecycleService,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """A failure to send the RUNNING event is a telemetry failure: the app isn't shut down and its
        siblings still initialize.
        """
        app0 = make_mock_app_instance(instance_name="instance_0")
        app1 = make_mock_app_instance(instance_name="instance_1")
        mock_hassette.send_event = AsyncMock(side_effect=RuntimeError("bus closed"))

        await lifecycle_service.initialize_instances(
            "test_app", {"instance_0": app0, "instance_1": app1}, mock_manifest, outcomes=AnyNameOutcomes()
        )

        app0.shutdown.assert_not_awaited()
        app1.initialize.assert_awaited_once()
        assert failure_writes(mock_registry) == []

    async def test_exception_traceback_shows_app_frame_not_just_call_site(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Logged traceback includes the app's own deep frame, not just outer call-site frames.

        ``get_short_traceback`` treats a positive limit as "closest to the call site" and a
        negative limit as "closest to the raise" (stdlib ``traceback.format_exc`` semantics).
        Init failures are logged with a limit sized for a nested on_initialize() call chain
        specifically so the app author's own raising line is visible, not just framework
        frames near ``anyio.fail_after`` — so the traceback limit must be negative.
        """

        async def level_5():
            raise ValueError("app bug at level 5")

        async def level_4():
            await level_5()

        async def level_3():
            await level_4()

        async def level_2():
            await level_3()

        async def level_1():
            await level_2()

        mock_app_instance.initialize.side_effect = level_1
        instances: dict[str, App] = {"test_instance": mock_app_instance}

        with patch.object(lifecycle_service, "logger") as mock_logger:
            await lifecycle_service.initialize_instances(
                "test_app", instances, mock_manifest, outcomes=AnyNameOutcomes()
            )

        traceback_arg = mock_logger.error.call_args[0][-1]
        assert "level_5" in traceback_arg

    async def test_continues_after_failure(
        self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Initializes remaining instances after one fails."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app1.initialize = AsyncMock(side_effect=ValueError("Failed"))

        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")

        instances: dict[str, App] = {app1.app_config.instance_name: app1, app2.app_config.instance_name: app2}

        mock_mark_ready = await initialize_with_mark_ready_patched(lifecycle_service, instances, mock_manifest)

        app1.initialize.assert_awaited_once()
        app2.initialize.assert_awaited_once()
        mock_mark_ready.assert_called_once_with(app2, reason="initialized")

    # dup-ignore-start: pytest test function signature
    async def test_emits_running_event_on_success(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with RUNNING status on success."""
        event_capture.install(mock_hassette)
        instances: dict[str, App] = {"test_instance": mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest, outcomes=AnyNameOutcomes())

        running_calls = app_state_payloads(event_capture, ResourceStatus.RUNNING)
        assert len(running_calls) == 1

    # dup-ignore-start: pytest test function signature
    async def test_emits_failed_event_on_error(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with FAILED status on error."""
        event_capture.install(mock_hassette)
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances: dict[str, App] = {"test_instance": mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest, outcomes=AnyNameOutcomes())

        failed_calls = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_calls) == 1


class TestStartingIsOutsideTheStartupTimeout:
    async def test_a_slow_starting_send_does_not_count_against_the_startup_timeout(
        self,
        real_registry_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """STARTING is sent before the startup timeout opens, so a slow bus never fails the app (spec 154 D4)."""
        monkeypatch.setattr(AppLifecycleService, "startup_timeout", property(lambda _self: 0.05))
        sends: list[ResourceStatus] = []

        async def slow_send(event: typing.Any) -> None:
            sends.append(event.payload.data.status)
            if event.payload.data.status is ResourceStatus.STARTING:
                await asyncio.sleep(0.2)

        mock_hassette.send_event = AsyncMock(side_effect=slow_send)
        registry = real_registry_service.registry
        seed_running(registry, "test_app", mock_app_instance, status=ResourceStatus.NOT_STARTED)
        outcomes = AnyNameOutcomes()

        await real_registry_service.initialize_instance(mock_app_instance, "TestApp", outcomes=outcomes)

        assert sends == [ResourceStatus.STARTING, ResourceStatus.RUNNING]
        mock_app_instance.shutdown.assert_not_awaited()
        assert registry.get_instances("test_app")["test_instance"].status is ResourceStatus.RUNNING
