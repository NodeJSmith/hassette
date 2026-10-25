"""Shared helpers for ServiceWatcher integration tests."""

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar, NamedTuple

from hassette_wire import ResourceStatus

from hassette import HassetteConfig
from hassette.core.service_watcher import ServiceWatcher
from hassette.events import AnyEvent, HassetteServiceEvent
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.testing import HassetteHarness, build_harness, wait_for
from hassette.types import Topic
from tests.support.helpers import (
    make_service_failed_event,
)

AWAIT_TIMEOUT = 5.0

ALWAYS_FAIL = sys.maxsize
"""``fail_times`` value for a dummy service whose ``on_initialize()`` raises on every call."""


def make_call_counts() -> dict[str, int]:
    """Fresh cancel/start counters for get_dummy_service."""
    return {"cancel": 0, "start": 0}


def make_fast_spec(**overrides: Any) -> RestartSpec:
    """RestartSpec with zero backoff for test speed. Override any field via kwargs."""
    defaults: dict[str, Any] = {"backoff_base_seconds": 0}
    defaults.update(overrides)
    return RestartSpec(**defaults)


@contextlib.asynccontextmanager
async def isolated_watcher(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
) -> AsyncIterator[ServiceWatcher]:
    """Build a fresh, private Hassette instance for a single test and yield its ServiceWatcher.

    Some tests in this file drive a real, complete ``hassette.shutdown()`` (restart-budget
    exhaustion or a fatal error). ``reset_hassette_lifecycle()`` correctly refuses to revive an
    instance that has already fully shut down (see the shared module-scoped instance entry in
    ``design/specs/105-teardown-restart-safety/known-issues.md``), so those tests cannot share
    the module-scoped ``watcher`` fixture's ``hassette_with_bus`` instance with the rest of this
    file -- running the file in its normal order left one dead shared instance behind for every
    test that followed the first one to trigger shutdown.

    Builds its own ``HassetteConfig`` instance (via the ``test_config_class`` factory, the same
    ``TestConfig`` subclass ``test_config`` itself is built from) rather than reusing the
    session-scoped ``test_config`` object that ``hassette_with_bus`` is already live on for the
    rest of this file. ``build_harness()``'s own teardown calls ``config.reload()``, which fully
    re-runs the config's ``__init__`` in place -- sharing an object with a harness that is still
    alive for the rest of the module would reset that harness's live config out from under it
    mid-file. Constructs ``HassetteHarness`` directly (not via the module-scoped
    ``hassette_harness`` factory fixture) with ``skip_global_set=True``: the module-scoped
    ``hassette_with_bus`` harness has already claimed the process-global "current Hassette"
    contextvar for the whole file, and only one harness may hold it at a time.

    Uses ``build_harness()`` directly inside the test body (not as a ``yield``-based pytest
    fixture), per its own docstring: ``__aexit__`` then runs inline in the test's own
    already-running Task, so there's no risk of pytest-asyncio resuming teardown as a *new* Task
    on the loop after this harness's own task factory has sealed shut -- see
    ``_start_module_harness()``'s docstring in ``tests.support.fixtures`` for why that
    matters specifically for ``yield``-based *fixtures* shared across a session-scoped loop.

    Unlike the shared ``watcher`` fixture, no ``context.PROTECT_TASK`` is needed here:
    ``build_harness()`` installs its task factory from *inside* this test's own already-running
    task -- i.e., strictly after that task was created -- so the factory can never retroactively
    claim it. ``make_task_factory()`` only ever registers tasks it is asked to *create*
    (``hassette.task_bucket.task_bucket.make_task_factory``); it has no path back to a task that
    already existed before the factory was installed. So even a real ``hassette.shutdown()`` ->
    ``cancel_all()`` here can never reach this test's own task.
    """
    config = test_config_class(web_api={"port": unused_tcp_port_factory()})
    harness = HassetteHarness(config, unused_tcp_port=unused_tcp_port_factory(), skip_global_set=True)
    async with build_harness(harness.with_bus()) as harness:
        hassette = harness.hassette
        watcher = ServiceWatcher(hassette, parent=hassette)
        try:
            yield watcher
        finally:
            await watcher.shutdown()


def mark_failed(service: Service) -> None:
    """Put `service` in FAILED status, as a real failure does before its FAILED event is sent.

    restart_service() drops a FAILED event for a service that is no longer FAILED as stale, so a
    test that drives it with a synthetic event must put the service in the state that event
    describes. Bypasses the lifecycle (``_status``) on purpose: this is fixture setup.
    """
    service._status = ResourceStatus.FAILED


async def restart_once(watcher: ServiceWatcher, event: HassetteServiceEvent) -> None:
    """Mark the event's service FAILED and deliver the event to restart_service, without waiting.

    Returns once restart_service does: exhaustion and drop decisions have been made, but a
    spawned restart episode may still be running (see restart_and_await).
    """
    service = watcher.get_service(event.payload.data.resource_name, event.payload.data.role)
    assert service is not None, f"No service registered for {event.payload.data.resource_name}"
    mark_failed(service)
    await watcher.restart_service(event)


async def restart_and_await(watcher: ServiceWatcher, event: HassetteServiceEvent) -> None:
    """Like restart_once, then wait for any restart episode it spawned to end.

    restart_service spawns the backoff+restart episode as a detached task and returns
    immediately. Tests that call restart_service sequentially need to wait for the
    in-restart flag to clear before the next call.
    """
    key = watcher.service_key(event.payload.data.resource_name, event.payload.data.role)
    was_restarting = key in watcher._restarting
    await restart_once(watcher, event)
    if not was_restarting and key in watcher._restarting:
        await wait_for(
            lambda: key not in watcher._restarting,
            desc=f"execute_restart for {key} completed",
            timeout=AWAIT_TIMEOUT,
        )


def get_dummy_service(
    called: dict[str, int],
    hassette,
    *,
    fail_times: int = 0,
    restart_spec: RestartSpec | None = None,
) -> Service:
    """Build a dummy Service whose first ``fail_times`` ``on_initialize()`` calls raise.

    Pass ``ALWAYS_FAIL`` for a service that never initializes successfully.
    """
    spec = restart_spec if restart_spec is not None else RestartSpec()

    class _Dummy(Service):
        """Does nothing, just tracks calls."""

        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            await asyncio.Event().wait()

        async def on_shutdown(self):
            called["cancel"] += 1

        async def on_initialize(self):
            called["start"] += 1
            if called["start"] <= fail_times:
                raise RuntimeError("initialize failed")

    return _Dummy(hassette)


class DummyServiceSetup(NamedTuple):
    """Everything a ServiceWatcher test needs to drive one dummy service."""

    service: Service
    calls: dict[str, int]
    spec: RestartSpec
    key: str
    failed_event: HassetteServiceEvent


def register_dummy_service(
    watcher: ServiceWatcher, *, fail_times: int = 0, **spec_overrides: object
) -> DummyServiceSetup:
    """Attach a FAILED dummy service to `watcher`'s hassette and pre-build what tests assert against."""
    calls = make_call_counts()
    spec = make_fast_spec(**spec_overrides)
    service = get_dummy_service(calls, watcher.hassette, fail_times=fail_times, restart_spec=spec)
    mark_failed(service)
    watcher.hassette.children.append(service)
    return DummyServiceSetup(
        service=service,
        calls=calls,
        spec=spec,
        key=watcher.service_key(service.class_name, service.role),
        failed_event=make_service_failed_event(service),
    )


def budget_entries(watcher: ServiceWatcher, key: str) -> int:
    """Count the live (non-expired) restart-budget entries recorded for `key`."""
    budget = watcher._budgets.get(key)
    assert budget is not None, f"No restart budget recorded for {key}"
    budget.evict_expired()
    return len(budget._timestamps)


def crashed_events(events: "list[AnyEvent]") -> "list[AnyEvent]":
    """Filter EventCapture output down to CRASHED service-status events."""
    return [
        e
        for e in events
        if e.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS and e.payload.data.status == ResourceStatus.CRASHED
    ]
