"""Tests for LifecycleMixin status transitions and the shutdown STOPPING path.

Verifies:
- _force_terminal() sets STOPPED directly
- handle_running() idempotency is preserved (already RUNNING → early return, no setter)
- Same-state setter assignment is a no-op
- handle_failed() leaves an already-terminal resource unchanged
- handle_failed() idempotency (already FAILED → early return)
- handle_starting() idempotency (already STARTING → early return)
- handle_crash() idempotency (already CRASHED → early return)
- start() idempotency (task already running → early return)
- start()/cancel() from a worker thread redispatch onto the loop thread
- cancel() cancels a running init task

Shutdown STOPPING path:
- shutdown() sets STOPPING before hooks run (Resource)
- shutdown() sets STOPPING before hooks run (Service)
- Full shutdown sequence: RUNNING → STOPPING → STOPPED
- RUNNING → STOPPED direct assignment applies (natural service completion via _serve_wrapper)
- Any changed status applies through the setter
"""

import asyncio
import contextlib
import threading

import pytest
from hassette_wire import ResourceStatus

from hassette.resources.lifecycle import (
    cancel,
    handle_crash,
    handle_failed,
    handle_running,
    handle_starting,
    start,
)
from tests.support.mock_hassette import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource, wait_for_running
from tests.unit.resources.lifecycle.conftest import make_running_simple_service


def make_running_resource() -> ConcreteResource:
    """Build a `ConcreteResource` with `_status` set directly to RUNNING, bypassing the setter."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)
    resource._status = ResourceStatus.RUNNING
    return resource


async def test_force_terminal_sets_stopped():
    """_force_terminal() on a RUNNING resource leaves it STOPPED."""
    resource = make_running_resource()

    resource._force_terminal()

    assert resource.status == ResourceStatus.STOPPED


async def test_same_state_no_transition():
    """handle_running() when already RUNNING returns early — idempotency preserved, previous_status unchanged."""
    resource = make_running_resource()
    resource._previous_status = ResourceStatus.STARTING

    await handle_running(resource)

    assert resource.status == ResourceStatus.RUNNING
    assert resource._previous_status == ResourceStatus.STARTING


async def test_same_state_setter_no_raise():
    """Direct same-state assignment via setter should not raise or re-validate."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)
    resource._status = ResourceStatus.RUNNING
    resource._previous_status = ResourceStatus.STARTING

    resource.status = ResourceStatus.RUNNING

    assert resource.status == ResourceStatus.RUNNING
    assert resource._previous_status == ResourceStatus.STARTING


async def test_shutdown_sets_stopping_before_hooks():
    """Resource.shutdown() must set STOPPING before on_shutdown hook runs."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    # Set to RUNNING so the transition RUNNING→STOPPING is valid
    resource._status = ResourceStatus.RUNNING

    status_in_hook: list[ResourceStatus] = []

    async def _on_shutdown_spy() -> None:
        status_in_hook.append(resource.status)

    resource.on_shutdown = _on_shutdown_spy  # pyright: ignore[reportAttributeAccessIssue]

    await resource.shutdown()

    assert status_in_hook, "on_shutdown hook was never called"
    assert status_in_hook[0] == ResourceStatus.STOPPING, (
        f"Expected STOPPING during on_shutdown hook, got {status_in_hook[0]}"
    )
    assert resource.status == ResourceStatus.STOPPED, f"Expected STOPPED after shutdown, got {resource.status}"


async def test_service_shutdown_sets_stopping_before_hooks():
    """Service.shutdown() must set STOPPING before before_shutdown hook runs.

    For Service, on_shutdown runs after the serve task completes (which calls
    handle_stop → STOPPING→STOPPED). The observable STOPPING point is before_shutdown,
    which fires before the serve task is cancelled.
    """
    svc = await make_running_simple_service()

    status_in_hook: list[ResourceStatus] = []

    async def _before_shutdown_spy() -> None:
        status_in_hook.append(svc.status)

    svc.before_shutdown = _before_shutdown_spy  # pyright: ignore[reportAttributeAccessIssue]

    await svc.shutdown()

    assert status_in_hook, "before_shutdown hook was never called"
    assert status_in_hook[0] == ResourceStatus.STOPPING, (
        f"Expected STOPPING during before_shutdown hook, got {status_in_hook[0]}"
    )
    assert svc.status == ResourceStatus.STOPPED, f"Expected STOPPED after shutdown, got {svc.status}"


async def test_shutdown_stopping_then_stopped_sequence():
    """Full transition sequence: RUNNING → STOPPING → STOPPED via shutdown()."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    resource._status = ResourceStatus.RUNNING
    seen_statuses: list[ResourceStatus] = []

    # Monkey-patch status setter to capture all transitions
    original_setter = type(resource).status.fset

    def _capturing_setter(self, value: ResourceStatus) -> None:
        seen_statuses.append(value)
        original_setter(self, value)  # pyright: ignore[reportCallIssue]

    type(resource).status = property(type(resource).status.fget, _capturing_setter)  # pyright: ignore[reportAttributeAccessIssue]
    try:
        await resource.shutdown()
    finally:
        # Restore original setter
        type(resource).status = property(type(resource).status.fget, original_setter)  # pyright: ignore[reportAttributeAccessIssue]

    assert ResourceStatus.STOPPING in seen_statuses, f"STOPPING not seen; transitions: {seen_statuses}"
    stopping_idx = seen_statuses.index(ResourceStatus.STOPPING)
    stopped_idx = next((i for i, s in enumerate(seen_statuses) if s == ResourceStatus.STOPPED), None)
    assert stopped_idx is not None, "STOPPED not seen"
    assert stopping_idx < stopped_idx, "STOPPING must precede STOPPED"


async def test_running_to_stopped_direct_is_valid():
    """RUNNING → STOPPED is valid for natural service completion (_serve_wrapper normal return)."""
    resource = make_running_resource()

    resource.status = ResourceStatus.STOPPED
    assert resource.status == ResourceStatus.STOPPED


async def test_setter_applies_any_transition():
    """Any changed status applies through the setter and records the prior status."""
    resource = make_running_resource()

    resource.status = ResourceStatus.NOT_STARTED

    assert resource.status == ResourceStatus.NOT_STARTED
    assert resource._previous_status == ResourceStatus.RUNNING


async def test_handle_failed_on_stopped_resource_is_noop():
    """handle_failed() on an already-stopped resource is a no-op.

    Regression for #1059. A late failure arriving after teardown completed — such as a
    submit-after-shutdown ``RuntimeError("cannot schedule new futures after shutdown")`` — must
    not move a STOPPED resource to FAILED, so handle_failed() leaves the status unchanged.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)
    resource._status = ResourceStatus.STOPPED

    # Must not raise and must not move off the terminal state.
    await handle_failed(resource, RuntimeError("cannot schedule new futures after shutdown"))

    assert resource.status == ResourceStatus.STOPPED


async def test_handle_failed_idempotent_when_already_failed():
    """handle_failed() when already FAILED returns early without re-emitting."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)
    resource._status = ResourceStatus.FAILED

    await handle_failed(resource, RuntimeError("second failure"))

    assert resource.status == ResourceStatus.FAILED
    hassette.send_event.assert_not_called()


async def test_handle_starting_idempotent_when_already_starting():
    """handle_starting() when already STARTING returns early without re-emitting."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)
    resource._status = ResourceStatus.STARTING

    await handle_starting(resource)

    assert resource.status == ResourceStatus.STARTING
    hassette.send_event.assert_not_called()


async def test_handle_crash_idempotent_when_already_crashed():
    """handle_crash() when already CRASHED returns early without re-emitting."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)
    resource._status = ResourceStatus.CRASHED

    await handle_crash(resource, RuntimeError("second crash"))

    assert resource.status == ResourceStatus.CRASHED
    hassette.send_event.assert_not_called()


async def test_start_idempotent_when_task_running():
    """start() when _init_task is already running skips re-spawn.

    start() itself only spawns a joiner that calls the coordinated initialize() front door —
    it no longer assigns _init_task synchronously (see hassette.resources.lifecycle.start()) —
    so this waits for the coordinator to actually create and assign the task before asserting.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _gated_on_initialize() -> None:
        entered.set()
        await release.wait()

    resource.on_initialize = _gated_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    start(resource)
    await asyncio.wait_for(entered.wait(), timeout=1)
    first_task = resource._init_task
    assert first_task is not None
    assert not first_task.done()

    start(resource)
    assert resource._init_task is first_task

    release.set()
    await first_task
    await resource.shutdown()


async def test_start_from_worker_thread_redispatches_onto_loop_thread():
    """start() called off the event-loop thread re-dispatches via call_soon_threadsafe.

    start() is a plain synchronous function (not `async def`) specifically so it can be called
    from a thread other than the event loop's own -- e.g. a sync handler running on the
    dedicated sync-handler thread pool. create_lifecycle_task() calls
    asyncio.get_running_loop(), which raises RuntimeError when there is no running loop on the
    calling thread. Without the cross-thread redispatch, calling start() from a worker thread
    would raise instead of scheduling initialization on the loop thread.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    errors: list[Exception] = []

    def _start_from_worker_thread() -> None:
        try:
            start(resource)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=_start_from_worker_thread)
    thread.start()
    thread.join(timeout=5.0)

    assert not thread.is_alive(), "start() should not hang when called from a worker thread"
    assert not errors, f"start() raised from a worker thread: {errors}"

    await wait_for_running(resource, timeout=3.0)

    await resource.shutdown()


async def test_cancel_from_worker_thread_redispatches_onto_loop_thread():
    """cancel() called off the event-loop thread re-dispatches via call_soon_threadsafe.

    Mirrors start()'s cross-thread redispatch (test_start_from_worker_thread_redispatches_onto_loop_thread)
    so that a sync handler calling start(resource) immediately followed by cancel(resource) --
    both from the same worker thread, with no intervening await -- preserves ordering. Without
    this redispatch, cancel() would run synchronously on the worker thread and see
    _pending_start_task still None (start()'s own redispatch has not been processed by the loop
    yet), report nothing to cancel, and let the queued _start_on_loop_thread callback go on to
    initialize the resource despite the ordered cancellation request.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    initialized = asyncio.Event()

    async def _tracking_on_initialize() -> None:
        initialized.set()

    resource.on_initialize = _tracking_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    errors: list[Exception] = []

    def _start_then_cancel_from_worker_thread() -> None:
        try:
            start(resource)
            cancel(resource)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=_start_then_cancel_from_worker_thread)
    thread.start()
    thread.join(timeout=5.0)

    assert not thread.is_alive(), "start()/cancel() should not hang when called from a worker thread"
    assert not errors, f"start()/cancel() raised from a worker thread: {errors}"

    # Give the loop a few turns to process both redispatched callbacks in order.
    for _ in range(5):
        await asyncio.sleep(0)

    assert not initialized.is_set(), "resource must not have initialized -- cancel() should have won the race"


async def test_start_with_unset_loop_thread_id_does_not_redispatch():
    """Regression: start() must not treat an unset ``loop_thread_id`` (``None``, before
    ``run_forever()`` captures it) as "definitely a different thread." Comparing
    ``threading.get_ident() != loop_thread_id`` directly is true for every real thread ident when
    ``loop_thread_id`` is ``None``, so it would redispatch even when already on the correct
    thread and then crash on ``resource.hassette.loop`` (``RuntimeError: Event loop is not
    running`` -- ``_loop`` and ``_loop_thread_id`` are set together in ``run_forever()``).
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.loop_thread_id = None
    resource = ConcreteResource(hassette)

    start(resource)  # must run synchronously in-place, not redispatch via call_soon_threadsafe

    assert resource._pending_start_task is not None, "start() must have run synchronously, not redispatched"
    await wait_for_running(resource, timeout=3.0)
    await resource.shutdown()


async def test_cancel_cancels_running_task():
    """cancel() requests cancellation of a running init task."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    entered = asyncio.Event()

    async def _gated_on_initialize() -> None:
        entered.set()
        await asyncio.Event().wait()  # block forever until cancelled

    resource.on_initialize = _gated_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    start(resource)
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert resource._init_task is not None
    assert not resource._init_task.done()

    cancel(resource)
    assert resource._init_task.cancelling() > 0

    with contextlib.suppress(asyncio.CancelledError):
        await resource._init_task


async def test_cancel_stops_pending_start_joiner_same_turn():
    """cancel() must stop a queued start() joiner even before it has assigned _init_task.

    start() only assigns _pending_start_task synchronously; _init_task is assigned later, once
    the joiner actually runs coordinate_initialize() (a turn or more later). Calling cancel()
    in the same event-loop turn as start() (no intervening await) must therefore also check
    _pending_start_task -- otherwise cancel() sees _init_task still None, reports nothing to
    cancel, and the queued joiner goes on to initialize the resource despite the cancellation
    request.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette)

    initialized = asyncio.Event()

    async def _tracking_on_initialize() -> None:
        initialized.set()

    resource.on_initialize = _tracking_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    # No await between start() and cancel() -- the joiner has not had an event-loop turn yet,
    # so _init_task is still None at the moment cancel() runs.
    start(resource)
    assert resource._init_task is None
    assert resource._pending_start_task is not None

    cancel(resource)

    # Let the cancelled joiner actually run and settle.
    pending_task = resource._pending_start_task
    if pending_task is not None:
        with pytest.raises(asyncio.CancelledError):
            await pending_task

    await asyncio.sleep(0)

    assert not initialized.is_set()
    assert resource.status != ResourceStatus.RUNNING
    assert resource.status != ResourceStatus.STARTING
