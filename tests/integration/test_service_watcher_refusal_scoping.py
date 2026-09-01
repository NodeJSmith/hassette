"""Integration tests for the confirmed-quiescence restart-refusal degrade path.

Covers the scoped-degrade acceptance criteria of design/specs/106-scope-restart-refusal-escalation:
a timeout-only RestartRefusedError waits up to half of resource_shutdown_timeout_seconds for
confirmed quiescence before deciding between a scoped EXHAUSTED_DEAD degrade and the unchanged
root-shutdown escalation. See test_service_watcher.py for the general restart-refusal escalation
tests this file's scenarios were split out from (design.md's "Test placement" section).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import ClassVar
from unittest.mock import AsyncMock, patch

from hassette import HassetteConfig
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.web_api_service import WebApiService
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import RestartRefusedError
from hassette.resources.restart import CORE_PERMANENT_RESTART, RestartSpec
from hassette.resources.service import Service
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.test_utils import EventCapture, HassetteHarness, build_harness, make_service_failed_event
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import RestartType
from tests.integration.test_service_watcher import restart_and_await

# Short so the confirmation-wait tests run fast: half of this becomes the confirmation-wait
# bound (0.5s), which comfortably fits several monkeypatched poll intervals below.
FAST_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS = 1

# Fast enough to keep the confirmation-wait tests quick without racing the wait bound above.
_FAST_POLL_SECONDS = 0.05

# Name for the single pending task these tests spawn to keep a service's task_bucket non-empty.
_PENDING_TASK_NAME = "test:pending"


def make_fast_spec(**overrides: object) -> RestartSpec:
    """RestartSpec with zero backoff for test speed. Override any field via kwargs."""
    defaults: dict[str, object] = {"backoff_base_seconds": 0}
    defaults.update(overrides)
    return RestartSpec(**defaults)  # pyright: ignore[reportCallIssue]


# Repeated across most tests in this file: a TRANSIENT spec fast enough for the confirmation-wait
# bound, with a low restart budget since none of these tests actually exhaust it.
TRANSIENT_FAST_SPEC = make_fast_spec(restart_type=RestartType.TRANSIENT, budget_intensity=5)


def make_dummy_service(hassette, *, restart_spec: RestartSpec | None = None) -> Service:
    """A Service that never completes serve() on its own -- restart() is mocked in these tests."""
    spec = restart_spec if restart_spec is not None else RestartSpec()

    class _Dummy(Service):
        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            await asyncio.Event().wait()

    return _Dummy(hassette)


def make_timeout_only_refusal(
    causes: tuple[TeardownCause, ...] = (TeardownCause.TASKS_PENDING,),
):
    """Build a restart() replacement that drives status to STOPPED (matching what a real
    restart()'s internal shutdown() call always does before RestartRefusedError is ever raised --
    see design.md's "Status transition correctness") and then raises a timeout-only refusal.
    """

    async def _refusing_restart(service: Service) -> None:
        service._status = ResourceStatus.STOPPED
        raise RestartRefusedError(service.class_name, TeardownReport(causes=causes))

    return _refusing_restart


def fire_once_on_first_sleep(
    original_sleep: "Callable[[float], Awaitable[bool]]", on_first_call: "Callable[[], object]"
) -> "Callable[[float], Awaitable[bool]]":
    """Wrap a shutdown_safe_sleep replacement that calls on_first_call() exactly once, on its
    first invocation, before delegating to the real sleep -- the event-gated way these tests
    release a pending task or trigger a bystander shutdown at the exact moment the confirmation
    wait actually starts sleeping, rather than racing it in real time.
    """
    released = asyncio.Event()

    async def _wrapped(duration: float) -> bool:
        if not released.is_set():
            released.set()
            on_first_call()
        return await original_sleep(duration)

    return _wrapped


@contextlib.asynccontextmanager
async def isolated_watcher(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
) -> AsyncIterator[ServiceWatcher]:
    """Build a fresh, private Hassette instance for a single test and yield its ServiceWatcher.

    Mirrors test_service_watcher.py's isolated_watcher() -- these tests drive a real, complete
    hassette root-shutdown request in the unconfirmed/escalation scenarios, so each test needs
    its own private Hassette instance rather than sharing a module-scoped harness. Deliberately a
    ``@contextlib.asynccontextmanager`` invoked inline in each test body (not a pytest
    yield-fixture): tests here drive a real, complete ``hassette.shutdown()``, and its
    ``__aexit__`` must run inline in the test's own already-running Task rather than be resumed
    as a *new* Task by pytest-asyncio's yield-fixture teardown machinery after that harness's own
    task factory has sealed shut. See that sibling function's docstring for the full rationale.

    resource_shutdown_timeout_seconds is set low (FAST_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS) so the
    confirmation wait this file exercises stays fast without needing to patch the config lookup
    itself.
    """
    config = test_config_class(
        web_api={"port": unused_tcp_port_factory()},
        lifecycle={
            "startup_timeout_seconds": 3,
            "run_sync_timeout_seconds": 2,
            "task_cancellation_timeout_seconds": 0.5,
            "resource_shutdown_timeout_seconds": FAST_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS,
        },
    )
    harness = HassetteHarness(config, unused_tcp_port=unused_tcp_port_factory(), skip_global_set=True)
    async with build_harness(harness.with_bus()) as harness:
        hassette = harness.hassette
        watcher = ServiceWatcher(hassette, parent=hassette)
        try:
            yield watcher
        finally:
            await watcher.shutdown()


async def test_unconfirmed_quiescence_still_escalates(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]", monkeypatch
):
    """A TRANSIENT service whose tracked task never finishes within the confirmation-wait bound
    still results in root-wide shutdown -- unchanged from today.
    """
    monkeypatch.setattr("hassette.core.service_watcher._DEATH_CONFIRMATION_POLL_SECONDS", _FAST_POLL_SECONDS)

    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        spec = TRANSIENT_FAST_SPEC
        service = make_dummy_service(hassette, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        # A task that never completes -- quiescence is never confirmed within the wait bound.
        never_release = asyncio.Event()
        service.task_bucket.spawn(never_release.wait(), name=_PENDING_TASK_NAME)

        assert hassette.fatal_shutdown_reason is None

        with (
            patch(
                "hassette.core.service_watcher.restart",
                new_callable=AsyncMock,
                side_effect=make_timeout_only_refusal(),
            ),
            EventCapture.capturing(hassette) as capture,
        ):
            await restart_and_await(watcher, failed_event)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()

        crashed = [
            e
            for e in capture.events
            if e.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS and e.payload.data.status == ResourceStatus.CRASHED
        ]
        assert len(crashed) == 1
        assert crashed[0].payload.data.resource_name == service.class_name

        never_release.set()  # let the pending task finish so teardown doesn't have to cancel it


async def test_confirmed_quiescence_degrades_only_that_service(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]", monkeypatch
):
    """A TRANSIENT service whose tracked task finishes shortly after the confirmation wait begins
    ends with only that service at EXHAUSTED_DEAD -- a sibling service stays RUNNING, and no
    fatal reason is recorded.
    """
    monkeypatch.setattr("hassette.core.service_watcher._DEATH_CONFIRMATION_POLL_SECONDS", _FAST_POLL_SECONDS)

    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        spec = TRANSIENT_FAST_SPEC
        service = make_dummy_service(hassette, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        sibling = make_dummy_service(hassette, restart_spec=make_fast_spec())
        sibling._status = ResourceStatus.RUNNING
        hassette.children.append(sibling)

        pending_gate = asyncio.Event()
        service.task_bucket.spawn(pending_gate.wait(), name=_PENDING_TASK_NAME)

        # Release the pending task the moment the confirmation wait actually starts sleeping --
        # event-gated, not a real-time race: the wait's own first poll sleep is the signal.
        sleep_and_release = fire_once_on_first_sleep(watcher.shutdown_safe_sleep, pending_gate.set)

        assert hassette.fatal_shutdown_reason is None

        with (
            patch(
                "hassette.core.service_watcher.restart",
                new_callable=AsyncMock,
                side_effect=make_timeout_only_refusal(),
            ),
            patch.object(watcher, "shutdown_safe_sleep", side_effect=sleep_and_release),
            EventCapture.capturing(hassette) as capture,
        ):
            await restart_and_await(watcher, failed_event)

        assert service.status == ResourceStatus.EXHAUSTED_DEAD
        assert sibling.status == ResourceStatus.RUNNING
        assert hassette.fatal_shutdown_reason is None
        assert not hassette.shutdown_event.is_set()

        dead_events = [
            e
            for e in capture.events
            if e.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS and e.payload.data.status == ResourceStatus.EXHAUSTED_DEAD
        ]
        assert len(dead_events) == 1
        assert dead_events[0].payload.data.resource_name == service.class_name
        # Diagnostic payload note (design.md): the confirmed-dead event must carry exception fields.
        assert dead_events[0].payload.data.exception_type == "RestartRefusedError"
        assert dead_events[0].payload.data.exception is not None


async def test_permanent_service_still_escalates_even_when_confirmed_dead(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]", monkeypatch
):
    """A PERMANENT-restart-type service's timeout-only refusal still escalates to root shutdown
    even when its task is confirmed dead within the bound -- degrade_on_confirmed_quiescent_refusal,
    not restart_type, gates the new path, but CORE_PERMANENT_RESTART sets both.
    """
    monkeypatch.setattr("hassette.core.service_watcher._DEATH_CONFIRMATION_POLL_SECONDS", _FAST_POLL_SECONDS)

    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        assert CORE_PERMANENT_RESTART.degrade_on_confirmed_quiescent_refusal is False

        service = make_dummy_service(hassette, restart_spec=CORE_PERMANENT_RESTART)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        # Already-quiescent before the refusal is even raised -- proves that even a confirmed-dead
        # PERMANENT service still escalates, because the opt-out field, not confirmation, gates it.

        assert hassette.fatal_shutdown_reason is None

        with patch(
            "hassette.core.service_watcher.restart",
            new_callable=AsyncMock,
            side_effect=make_timeout_only_refusal(),
        ):
            await restart_and_await(watcher, failed_event)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()
        assert service.status != ResourceStatus.EXHAUSTED_DEAD


def test_websocket_service_opts_out_of_confirmed_quiescent_degrade():
    """WebsocketService.restart_spec has the opt-out field set, independent of restart_type (it
    stays TRANSIENT for ordinary budget/backoff/cooldown behavior).
    """
    assert WebsocketService.restart_spec.restart_type == RestartType.TRANSIENT
    assert WebsocketService.restart_spec.degrade_on_confirmed_quiescent_refusal is False


def test_web_api_service_opts_out_of_confirmed_quiescent_degrade():
    """Ship-time challenge finding (spec 106): WebApiService is the framework's sole human-facing
    interface (dashboard, REST API, health endpoints) and meets the same "no path back for a
    human to notice or intervene" criterion the design already applies to WebsocketService, so it
    must opt out of the new degrade path the same way -- silently degrading it to EXHAUSTED_DEAD
    would leave no process exit for a supervisor and no way for an operator to notice short of
    trying to load the dashboard.
    """
    assert WebApiService.restart_spec.restart_type == RestartType.TRANSIENT
    assert WebApiService.restart_spec.degrade_on_confirmed_quiescent_refusal is False


async def test_websocket_service_still_escalates_even_when_confirmed_dead(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]", monkeypatch
):
    """A real WebsocketService instance's timeout-only refusal still escalates to root shutdown
    even when confirmed dead within the bound -- proving the opt-out field, not restart_type
    (WebsocketService is TRANSIENT, not PERMANENT), is what the guard in
    cooldown_and_retry()/execute_restart() actually checks.
    """
    monkeypatch.setattr("hassette.core.service_watcher._DEATH_CONFIRMATION_POLL_SECONDS", _FAST_POLL_SECONDS)

    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        service = WebsocketService(hassette, parent=hassette)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        assert hassette.fatal_shutdown_reason is None

        with patch(
            "hassette.core.service_watcher.restart",
            new_callable=AsyncMock,
            side_effect=make_timeout_only_refusal(),
        ):
            await restart_and_await(watcher, failed_event)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()
        assert service.status != ResourceStatus.EXHAUSTED_DEAD


async def test_bystander_guard_skips_redundant_crashed_event(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]", monkeypatch
):
    """Bystander guard (Finding 9 of the sketch-time challenge): when the confirmation wait
    aborts because shutdown_event was already set by an unrelated fatal failure,
    handle_timeout_only_refusal() must not fall through to handle_restart_refused() -- that
    would dispatch a second, misattributed CRASHED event for a service whose only real issue
    was a plain timeout.
    """
    monkeypatch.setattr("hassette.core.service_watcher._DEATH_CONFIRMATION_POLL_SECONDS", _FAST_POLL_SECONDS)

    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        spec = TRANSIENT_FAST_SPEC
        service = make_dummy_service(hassette, restart_spec=spec)
        hassette.children.append(service)

        error = RestartRefusedError(service.class_name, TeardownReport(causes=(TeardownCause.TASKS_PENDING,)))
        service._status = ResourceStatus.STOPPED

        never_release = asyncio.Event()
        service.task_bucket.spawn(never_release.wait(), name=_PENDING_TASK_NAME)

        # Simulate an unrelated fatal failure already in progress elsewhere -- captured by
        # handle_timeout_only_refusal() at entry (already_shutting_down), before the wait even
        # begins, distinguishing "this service caused it" from "shutdown was already happening".
        hassette.shutdown_event.set()

        with (
            patch.object(watcher, "handle_restart_refused", new_callable=AsyncMock) as mock_handle_refused,
            EventCapture.capturing(hassette) as capture,
        ):
            await watcher.handle_timeout_only_refusal(service.class_name, service.role, service, error)

        mock_handle_refused.assert_not_awaited()
        assert capture.events == []
        assert service.status != ResourceStatus.EXHAUSTED_DEAD

        never_release.set()


async def test_bystander_guard_skips_redundant_dead_event_on_confirmed_quiescence(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """Ship-time challenge finding (spec 106): the confirmed-quiescent success branch had no
    bystander guard, unlike the escalation branch just below it. A service that confirms
    quiescent while an unrelated fatal shutdown is already in progress must not dispatch a
    misleading "confirmed dead, degraded independently" EXHAUSTED_DEAD event -- same
    misattribution concern as test_bystander_guard_skips_redundant_crashed_event, just on the
    success path instead of the escalation path.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        spec = TRANSIENT_FAST_SPEC
        service = make_dummy_service(hassette, restart_spec=spec)
        hassette.children.append(service)

        error = RestartRefusedError(service.class_name, TeardownReport(causes=(TeardownCause.TASKS_PENDING,)))
        service._status = ResourceStatus.STOPPED

        # No pending task at all -- is_teardown_confirmed_quiescent() reports True on the very
        # first check, so wait_for_teardown_confirmation() returns True without ever sleeping,
        # landing in the success branch this guard covers.
        hassette.shutdown_event.set()

        with EventCapture.capturing(hassette) as capture:
            await watcher.handle_timeout_only_refusal(service.class_name, service.role, service, error)

        assert capture.events == []
        assert service.status != ResourceStatus.EXHAUSTED_DEAD


async def test_bystander_guard_skips_redundant_crashed_event_when_shutdown_starts_mid_wait(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]", monkeypatch
):
    """Mid-wait counterpart to test_bystander_guard_skips_redundant_crashed_event: if an unrelated
    fatal failure sets hassette.shutdown_event *during* wait_for_teardown_confirmation (rather than
    before handle_timeout_only_refusal() is even entered), the guard must still catch it. Without
    the post-wait re-check, already_shutting_down would still read False from the entry snapshot
    and fall through to handle_restart_refused(), dispatching a second, misattributed CRASHED
    event -- the same failure mode the pre-wait guard exists to prevent, just triggered mid-wait.
    """
    monkeypatch.setattr("hassette.core.service_watcher._DEATH_CONFIRMATION_POLL_SECONDS", _FAST_POLL_SECONDS)

    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        spec = TRANSIENT_FAST_SPEC
        service = make_dummy_service(hassette, restart_spec=spec)
        hassette.children.append(service)

        error = RestartRefusedError(service.class_name, TeardownReport(causes=(TeardownCause.TASKS_PENDING,)))
        service._status = ResourceStatus.STOPPED

        never_release = asyncio.Event()
        service.task_bucket.spawn(never_release.wait(), name=_PENDING_TASK_NAME)

        # shutdown_event is NOT set before entry -- already_shutting_down snapshots False. Instead,
        # set it from inside the first poll sleep so the wait aborts mid-wait via
        # shutdown_safe_sleep's early-exit path, exactly the window the entry-only snapshot misses.
        sleep_and_trigger_shutdown = fire_once_on_first_sleep(watcher.shutdown_safe_sleep, hassette.shutdown_event.set)

        with (
            patch.object(watcher, "handle_restart_refused", new_callable=AsyncMock) as mock_handle_refused,
            patch.object(watcher, "shutdown_safe_sleep", side_effect=sleep_and_trigger_shutdown),
            EventCapture.capturing(hassette) as capture,
        ):
            await watcher.handle_timeout_only_refusal(service.class_name, service.role, service, error)

        mock_handle_refused.assert_not_awaited()
        assert capture.events == []
        assert service.status != ResourceStatus.EXHAUSTED_DEAD

        never_release.set()
