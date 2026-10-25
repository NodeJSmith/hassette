"""Integration tests for ServiceWatcher fatal-error and restart-refusal escalation."""

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import patch

from hassette_wire import ResourceStatus

from hassette import HassetteConfig
from hassette.core.service_status_predicates import SERVICE_STATUS_PATH
from hassette.core.service_watcher import ServiceWatcher
from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.events import HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.testing import EventCapture
from hassette.types import Topic
from hassette.types.enums import ResourceRole, RestartType
from tests.support.helpers import (
    PLACEHOLDER_APP_NAME,
    PLACEHOLDER_RESOURCE_NAME,
    make_crashed_event,
    make_service_failed_event,
)

from .helpers import (
    ALWAYS_FAIL,
    AWAIT_TIMEOUT,
    budget_entries,
    crashed_events,
    isolated_watcher,
    make_call_counts,
    make_fast_spec,
    register_dummy_service,
    restart_and_await,
    restart_once,
)

if TYPE_CHECKING:
    from collections.abc import Callable

SERVICE_RESOURCE_NAME_PATH = "payload.data.resource_name"
"""Accessor path to a service-status event's resource_name, for narrowing test listeners."""


def get_refusing_dummy_service(
    called: dict[str, int],
    hassette,
    *,
    refuse_after: int = 1,
    restart_spec: RestartSpec | None = None,
) -> Service:
    """A Service whose ``on_shutdown`` hook raises starting on the ``refuse_after``-th call
    (1-indexed), producing ``TeardownCause.SHUTDOWN_HOOK_FAILED`` evidence -- a restart-unsafe
    teardown report -- so ``restart()`` raises ``RestartRefusedError`` from that call onward.

    ``refuse_after=1`` (the default) refuses on every restart attempt, for tests that only need
    the very first restart to hit refusal. A caller driving a service through a normal restart
    (or budget exhaustion) before forcing refusal on a later, post-cooldown attempt passes a
    higher value.
    """
    spec = restart_spec if restart_spec is not None else RestartSpec()

    class _Refusing(Service):
        """Restarts cleanly until on_shutdown call number `refuse_after`, then always refuses."""

        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            await asyncio.Event().wait()

        async def on_shutdown(self):
            called["cancel"] += 1
            if called["cancel"] >= refuse_after:
                raise RuntimeError("shutdown hook fails from this call onward")

        async def on_initialize(self):
            called["start"] += 1

    return _Refusing(hassette)


async def test_fatal_error_records_fatal_reason(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A service raising a configured fatal error records _fatal_shutdown_reason synchronously."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        assert hassette._fatal_shutdown_reason is None

        dummy = register_dummy_service(
            watcher,
            restart_type=RestartType.TRANSIENT,
            budget_intensity=5,
            fatal_error_names=("RuntimeError",),
        )

        event = make_service_failed_event(dummy.service, exception=RuntimeError("boom"))
        await watcher.restart_service(event)  # fatal-error path triggers immediately

        assert hassette._fatal_shutdown_reason is not None
        assert "RuntimeError" in hassette._fatal_shutdown_reason


async def test_fatal_error_triggers_immediate_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """Service with fatal_error_names: matching exception triggers immediate shutdown, no restart."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        dummy = register_dummy_service(
            watcher,
            restart_type=RestartType.TRANSIENT,
            fatal_error_names=("FatalDbError", "SchemaVersionError"),
            budget_intensity=5,
        )

        # Create a failed event with exception_type matching a fatal error name
        fatal_event = HassetteServiceEvent(
            topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
            payload=HassettePayload(
                data=ServiceStatusPayload(
                    resource_name=dummy.service.class_name,
                    role=dummy.service.role,
                    status=ResourceStatus.FAILED,
                    previous_status=ResourceStatus.RUNNING,
                    exception="fatal db error",
                    exception_type="FatalDbError",
                    exception_traceback=None,
                    ready=False,
                    ready_phase=None,
                ),
            ),
        )

        with EventCapture.capturing(hassette) as capture:
            await watcher.restart_service(fatal_event)

        # Should have emitted CRASHED and triggered shutdown
        assert hassette.shutdown_event.is_set()
        assert len(capture.events) >= 1
        # First event should be CRASHED
        assert capture.events[0].payload.data.status == ResourceStatus.CRASHED
        # No restart should have been attempted
        assert dummy.calls["start"] == 0


async def test_non_retryable_error_skips_restart(watcher: ServiceWatcher):
    """Service with non_retryable_error_names: matching exception skips restart, goes to exhaustion."""
    hassette = watcher.hassette
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TEMPORARY,
        non_retryable_error_names=("NonRetryableError",),
        budget_intensity=5,
    )

    nr_event = HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            data=ServiceStatusPayload(
                resource_name=dummy.service.class_name,
                role=dummy.service.role,
                status=ResourceStatus.FAILED,
                previous_status=ResourceStatus.RUNNING,
                exception="non-retryable",
                exception_type="NonRetryableError",
                ready=False,
                ready_phase=None,
            ),
        ),
    )

    with EventCapture.capturing(hassette) as capture:
        await watcher.restart_service(nr_event)

    # No restart attempt made
    assert dummy.calls["start"] == 0
    # TEMPORARY exhaustion → EXHAUSTED_DEAD emitted
    assert len(capture.events) == 1
    assert capture.events[0].payload.data.status == ResourceStatus.EXHAUSTED_DEAD


async def test_non_retryable_error_from_restart_attempt_ends_episode(watcher: ServiceWatcher):
    """A restart attempt that raises a non-retryable error goes straight to exhaustion, not a retry.

    The attempt's own FAILED event is dropped while the episode runs, so the episode itself must
    route the error the way restart_service() routes one carried by a FAILED event.
    """
    dummy = register_dummy_service(
        watcher,
        fail_times=ALWAYS_FAIL,
        restart_type=RestartType.TEMPORARY,
        budget_intensity=5,
        non_retryable_error_names=("RuntimeError",),
    )

    await restart_and_await(watcher, dummy.failed_event)

    assert dummy.calls["start"] == 1, "A non-retryable failure must not be retried"
    assert budget_entries(watcher, dummy.key) == 1
    assert dummy.service.status == ResourceStatus.EXHAUSTED_DEAD


async def test_episode_failed_event_with_non_retryable_error_is_not_routed_twice(watcher: ServiceWatcher):
    """The attempt's own FAILED event, carrying a non-retryable error and delivered while the
    episode is still routing that same failure (service still FAILED), is dropped by the
    in-restart guard instead of being routed a second time.
    """
    dummy = register_dummy_service(
        watcher,
        fail_times=ALWAYS_FAIL,
        restart_type=RestartType.TEMPORARY,
        budget_intensity=5,
        non_retryable_error_names=("RuntimeError",),
    )
    attempt_event = make_service_failed_event(dummy.service, exception=RuntimeError("initialize failed"))
    real_dispatch = watcher.dispatch_status_event_best_effort
    real_exhaustion = watcher.handle_exhaustion
    exhaustion_calls = 0
    late_event_delivered = False

    async def dispatch_with_late_event(name: str, role: ResourceRole, event: HassetteServiceEvent) -> None:
        nonlocal late_event_delivered
        if not late_event_delivered:
            late_event_delivered = True
            assert dummy.service.status == ResourceStatus.FAILED, "precondition: status not yet moved on"
            await watcher.restart_service(attempt_event)
        await real_dispatch(name, role, event)

    async def counting_exhaustion(*args: Any, **kwargs: Any) -> None:
        nonlocal exhaustion_calls
        exhaustion_calls += 1
        await real_exhaustion(*args, **kwargs)

    with (
        patch.object(watcher, "dispatch_status_event_best_effort", side_effect=dispatch_with_late_event),
        patch.object(watcher, "handle_exhaustion", side_effect=counting_exhaustion),
    ):
        await restart_and_await(watcher, dummy.failed_event)

    assert late_event_delivered
    assert exhaustion_calls == 1, "The episode-owned FAILED event must not route the failure again"
    assert dummy.service.status == ResourceStatus.EXHAUSTED_DEAD


async def test_fatal_error_from_restart_attempt_triggers_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A restart attempt that raises a configured fatal error shuts down instead of retrying."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        dummy = register_dummy_service(
            watcher,
            fail_times=ALWAYS_FAIL,
            restart_type=RestartType.TRANSIENT,
            budget_intensity=5,
            fatal_error_names=("RuntimeError",),
        )

        await restart_and_await(watcher, dummy.failed_event)

        assert dummy.calls["start"] == 1, "A fatal failure must not be retried"
        assert hassette.fatal_shutdown_reason is not None
        assert "RuntimeError" in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()


async def test_restart_refused_during_backoff_escalates_to_fatal_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A RestartRefusedError raised from restart() inside execute_restart() (the immediate
    backoff+restart path) is caught and escalated through handle_restart_refused(): one fatal
    reason, one root shutdown request, exactly one CRASHED event, and no retry.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        calls = make_call_counts()
        spec = make_fast_spec(restart_type=RestartType.TRANSIENT, budget_intensity=5)
        # refuse_after=1: the very first restart attempt refuses.
        service = get_refusing_dummy_service(calls, hassette, refuse_after=1, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        assert hassette.fatal_shutdown_reason is None

        with EventCapture.capturing(hassette) as capture:
            await restart_and_await(watcher, failed_event)

        # One fatal reason, naming the refused service, and root shutdown requested.
        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()

        # Exactly one CRASHED event, carrying the refusal's exception fields.
        events = crashed_events(capture.events)
        assert len(events) == 1
        assert events[0].payload.data.resource_name == service.class_name
        assert events[0].payload.data.exception_type == "RestartRefusedError"
        assert events[0].payload.data.exception is not None
        assert service.class_name in events[0].payload.data.exception

        # restart() (and thus on_shutdown) was attempted exactly once -- no retry after refusal.
        assert calls["cancel"] == 1
        assert calls["start"] == 0, "initialize() must not run after a refused shutdown"

        # A duplicate trigger after the handler returns: no second CRASHED event or recovery.
        with EventCapture.capturing(hassette) as capture2:
            await watcher.restart_service(failed_event)
        assert capture2.events == []
        assert calls == {"cancel": 1, "start": 0}


async def test_restart_refused_during_cooldown_escalates_to_fatal_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A RestartRefusedError raised from restart() inside cooldown_and_retry() (the TRANSIENT
    post-cooldown restart path) is caught and escalated the same way as the backoff path: one
    fatal reason, one root shutdown request, exactly one CRASHED event, and no retry.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        calls = make_call_counts()
        spec = make_fast_spec(
            restart_type=RestartType.TRANSIENT,
            budget_intensity=1,
            cooldown_seconds=0.01,
            max_cooldown_cycles=0,
        )
        # refuse_after=2: the first restart (which consumes the one budget slot) succeeds
        # cleanly; the second on_shutdown call -- the post-cooldown restart attempt -- refuses.
        service = get_refusing_dummy_service(calls, hassette, refuse_after=2, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)
        key = watcher.service_key(service.class_name, service.role)

        # First restart succeeds cleanly, consuming the one budget slot.
        await restart_and_await(watcher, failed_event)
        assert calls == {"cancel": 1, "start": 1}
        assert hassette.fatal_shutdown_reason is None

        # Second FAILED event exceeds budget (intensity=1) -> TRANSIENT cooldown scheduled.
        with EventCapture.capturing(hassette) as capture:
            await restart_once(watcher, failed_event)
            cooldown_task = watcher._cooldown_tasks[key]
            await asyncio.wait_for(asyncio.shield(cooldown_task), timeout=AWAIT_TIMEOUT)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()

        events = crashed_events(capture.events)
        assert len(events) == 1
        assert events[0].payload.data.resource_name == service.class_name
        assert events[0].payload.data.exception_type == "RestartRefusedError"

        # restart() was attempted exactly once during cooldown (on_shutdown call #2) -- no retry,
        # and initialize() never ran for that refused attempt.
        assert calls == {"cancel": 2, "start": 1}


async def test_restart_refusal_shutdown_survives_event_dispatch_failure(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A broken event bus (send_event raising) must not prevent the fatal reason or the root
    shutdown request -- event dispatch is telemetry, not the control path.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        calls = make_call_counts()
        spec = make_fast_spec(restart_type=RestartType.TRANSIENT, budget_intensity=5)
        service = get_refusing_dummy_service(calls, hassette, refuse_after=1, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        with patch.object(hassette, "send_event", side_effect=RuntimeError("bus dead")):
            await restart_and_await(watcher, failed_event)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()


async def dispatch_and_wait(watcher: ServiceWatcher, event: HassetteServiceEvent) -> None:
    """Send ``event`` through the real bus and return once dispatch for it has completed.

    Registers a throwaway sentinel listener carrying the same status filter the watcher's own
    handlers do, minus the role filter, narrowed further to ``event``'s own resource_name so an
    unrelated resource reaching the same status mid-test cannot satisfy the wait. That makes
    "the watcher's handler did not run" a checked negative rather than a race with an event that
    had not been delivered yet.

    The sentinel firing proves the event was delivered and matched, but each matching handler
    runs as its own task — so this also waits for dispatch to go idle, otherwise a watcher
    handler that *did* wrongly match could still be mid-flight when the caller asserts it never
    ran.
    """
    fired = asyncio.Event()
    hassette = watcher.hassette
    status_payload = event.payload.data

    async def sentinel(_: HassetteServiceEvent) -> None:
        hassette.task_bucket.post_to_loop(fired.set)

    await watcher.bus.on(
        topic=str(Topic.HASSETTE_EVENT_SERVICE_STATUS),
        handler=sentinel,
        name=f"test.service_watcher.sentinel.{status_payload.resource_name}.{status_payload.status}",
        where=P.ValueIs(source=get_path(SERVICE_STATUS_PATH), condition=status_payload.status)
        & P.ValueIs(source=get_path(SERVICE_RESOURCE_NAME_PATH), condition=status_payload.resource_name),
    )

    await hassette.send_event(event)
    await asyncio.wait_for(fired.wait(), timeout=AWAIT_TIMEOUT)
    await hassette.bus_service.await_dispatch_idle(timeout=AWAIT_TIMEOUT)


async def test_app_role_crashed_event_does_not_shut_down_process(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """An APP-role CRASHED event records no fatal reason and requests no shutdown.

    Apps emit HASSETTE_EVENT_SERVICE_STATUS through the same lifecycle machinery services do,
    so shutdown_if_crashed would otherwise take the whole process down for one crashed app
    instance. The role filter on the subscription is what prevents it.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        await watcher.register_internal_event_listeners()

        await dispatch_and_wait(watcher, make_crashed_event(resource_name=PLACEHOLDER_APP_NAME, role=ResourceRole.APP))

        assert hassette.fatal_shutdown_reason is None, "APP-role crash must not record a fatal reason"
        assert not hassette.shutdown_event.is_set(), "APP-role crash must not request shutdown"


async def test_resource_role_crashed_event_still_shuts_down_process(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A RESOURCE-role CRASHED event still records a fatal reason and requests shutdown.

    The role filter excludes apps, not everything that is not a Service. Several framework
    components are plain ``Resource`` subclasses rather than ``Service`` -- notably
    ``AppLifecycleService``, which calls ``handle_crash`` when ``bootstrap_apps()`` raises. That
    crash reaches the watcher as a RESOURCE-role event, and it must still stop the process:
    ``AppHandler`` runs bootstrap as a detached task, so nothing else converts the failure into a
    non-zero exit, and Hassette would otherwise keep running with no apps bootstrapped.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        await watcher.register_internal_event_listeners()

        await dispatch_and_wait(
            watcher,
            make_crashed_event(resource_name=PLACEHOLDER_RESOURCE_NAME, role=ResourceRole.RESOURCE),
        )

        assert hassette.fatal_shutdown_reason is not None, "RESOURCE-role crash must record a fatal reason"
        assert PLACEHOLDER_RESOURCE_NAME in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set(), "RESOURCE-role crash must request shutdown"


async def test_app_role_failed_event_does_not_reach_restart_service(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """An APP-role FAILED event never reaches restart_service.

    restart_service resolves a Service child by (name, role); for an app it resolves nothing and
    bails out before touching a restart budget, so the only observable difference between "the
    filter worked" and "the handler ran and found nothing" is whether the handler ran at all.
    A pass-through spy installed before registration records that directly.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        received: list[HassetteServiceEvent] = []
        real_restart_service = watcher.restart_service

        async def spy(event: HassetteServiceEvent) -> None:
            received.append(event)
            await real_restart_service(event)

        watcher.restart_service = spy  # pyright: ignore[reportAttributeAccessIssue]
        await watcher.register_internal_event_listeners()

        failed_event = HassetteServiceEvent.from_service_status(
            resource_name=PLACEHOLDER_APP_NAME,
            role=ResourceRole.APP,
            status=ResourceStatus.FAILED,
            exception=RuntimeError("app init blew up"),
        )
        await dispatch_and_wait(watcher, failed_event)

        assert not received, "APP-role failure must not reach restart_service"
