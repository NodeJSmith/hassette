"""Shared fixtures for ServiceWatcher integration tests."""

import asyncio

import pytest

from hassette import context
from hassette.core.service_watcher import ServiceWatcher
from hassette.testing._reset import reset_hassette_lifecycle
from tests.support.harness import preserve_config


@pytest.fixture
async def watcher(hassette_with_bus, request: pytest.FixtureRequest) -> ServiceWatcher:
    """Return a fresh service watcher for each test.

    Deliberately a *plain* async fixture (no ``yield``) with cleanup registered via
    ``request.addfinalizer()`` as a *synchronous* callback, mirroring
    ``tests/integration/conftest.py::hassette_instance`` (see its docstring for the full
    mechanism). This file specifically exercises restart-budget exhaustion, which calls
    ``hassette.shutdown()`` and seals the shared ``hassette_with_bus`` harness's root
    TaskBucket mid-test. If teardown were a ``yield``-based async generator, pytest-asyncio's
    resumption of it would need to create a brand-new Task via the loop's task factory --
    which, while that factory still routes through the now-sealed bucket, raises immediately,
    before this fixture's own cleanup (``watcher.shutdown()`` /
    ``reset_hassette_lifecycle()``) ever runs, and leaves the loop poisoned for the rest of
    the pytest-xdist worker's session.

    Also sets context.PROTECT_TASK, so this test's own top-level task is never tracked by any
    TaskBucket in the first place (see hassette.context.PROTECT_TASK for the full mechanism).
    Restart-budget exhaustion drives a real hassette.shutdown(), whose cancel_all() would
    otherwise cancel this test's own task as a side effect purely because pytest-asyncio's task
    creation for it happened to be routed through the same loop's factory with no other bucket
    claimed -- the same "no active scope" signal a genuinely rogue task also produces, and the
    only thing that distinguishes them is this deliberate opt-in. A bare `.set()` (not a scoped
    context manager) is required: this fixture's own task finishes before the test body's task
    is even created, and pytest-asyncio's own contextvar-propagation machinery is what carries
    the value forward from here into that later task -- see PROTECT_TASK's docstring.
    """
    context.PROTECT_TASK.set(True)
    hassette = hassette_with_bus.hassette
    watcher = ServiceWatcher(hassette, parent=hassette)
    original_children = list(hassette.children)
    config_cm = preserve_config(hassette.config)
    config_cm.__enter__()

    loop = asyncio.get_running_loop()
    safe_task_factory = hassette_with_bus._previous_task_factory

    def _teardown() -> None:
        # Order matters: restore a safe (non-bucket-routed) task factory *before* anything
        # that might create a new Task, including run_until_complete()'s own
        # ensure_future() call. Only swap away from the currently-active factory when the
        # root TaskBucket it routes to is actually sealed (e.g. this test triggered a full
        # hassette.shutdown()) -- most tests never seal it, and unconditionally swapping to
        # the harness's pre-install factory would needlessly drop bucket routing for the
        # cleanup calls below.
        was_sealed = hassette.task_bucket.is_sealed
        if was_sealed:
            loop.set_task_factory(safe_task_factory)
        try:
            # Clean up bus listeners registered by this watcher via propagation
            loop.run_until_complete(watcher.shutdown())
            # reset_hassette_lifecycle() only clears a shutdown *request* that hasn't started
            # a teardown attempt yet -- it explicitly refuses (RuntimeError) to touch an
            # instance with an active shutdown task or a stored teardown report, and refuses
            # a fortiori once event streams are closed by a completed shutdown (see its
            # docstring and `_reject_if_active_or_reported()` in
            # `hassette.testing._reset`). A test that lets a PERMANENT service exhaust its
            # restart budget (e.g. test_always_failing_service_stops_after_max_attempts)
            # causes ServiceWatcher to trigger a real, completed `hassette.shutdown()` --
            # reset is not possible in that case, and the shared `hassette_with_bus` harness
            # is genuinely no longer reusable for the rest of this module regardless.
            already_shut_down = (
                hassette.event_streams_closed
                or hassette._shutdown_task is not None
                or hassette._teardown_report is not None
            )
            if not already_shut_down:
                loop.run_until_complete(reset_hassette_lifecycle(hassette, original_children=original_children))
        finally:
            config_cm.__exit__(None, None, None)
            # Do NOT restore active_task_factory here: it routes through hassette.task_bucket,
            # which -- once was_sealed is true -- is permanently sealed for the rest of this
            # module's shared hassette_with_bus harness (a real, completed shutdown is not
            # reversible; see the already_shut_down branch above). Restoring it anyway would
            # route the *next* test's own setup (constructing its ServiceWatcher, etc.) back
            # through the dead bucket, which immediately rejects that work with "TaskBucket(...)
            # is sealed and rejected new work: setup" -- breaking the next test before its body
            # even starts. Leaving safe_task_factory in place is correct for the rest of the
            # module: nothing legitimate can route through the sealed bucket again regardless.

    # PT021: request.addfinalizer() instead of `yield` is deliberate here -- see the
    # docstring above for why a `yield`-based async-generator fixture deadlocks here.
    request.addfinalizer(_teardown)  # noqa: PT021
    return watcher
