"""Tests for shutdown coordinator timeouts, hook bounds, cancellation, re-entry, and failure handling."""

import asyncio
import contextlib

import pytest
from hassette_wire import ResourceStatus

from hassette.exceptions import LifecycleReentryError, RestartRefusedError
from hassette.resources import lifecycle
from hassette.resources.base import Resource
from hassette.resources.shutdown_deadline import deadline_in
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette

from .conftest import (
    HangingChild,
    ShutdownCounter,
    SimpleParent,
    make_initialized_shutdown_counter,
)


async def test_hanging_child_hook_times_out_and_parent_completes():
    """A child whose hook hangs is cut off at its own bound; the parent and its other children still finish."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = SimpleParent(hassette)
    hanging = parent.add_child(HangingChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    await parent.shutdown()

    assert parent.shutdown_completed is True
    assert hanging.shutdown_completed is True
    assert hanging.shutting_down is False
    hanging_outcome = hanging.shutdown_outcome
    assert hanging_outcome is not None
    assert hanging_outcome.result is ShutdownResult.TIMED_OUT
    assert normal.shutdown_completed is True


async def test_hanging_hook_is_cut_off_by_its_own_bound_and_recorded_as_timed_out():
    """A hook that outlives ``shutdown_timeout_seconds`` is cancelled and recorded as timed out, not
    raised, and the body carries on through its later stages without being force-terminated.
    """
    resource, outcome = await shut_down_with_short_hook_bound(HangingChild)

    assert outcome.result is ShutdownResult.TIMED_OUT
    assert resource.status == ResourceStatus.STOPPED


class CancelSwallowingChild(Resource):
    """Resource whose ``on_shutdown()`` catches its cancellation and returns normally."""

    async def on_shutdown(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(1000)


async def test_hook_that_swallows_its_cancellation_and_returns_is_recorded_as_timed_out():
    """A hook cut off by its bound times out even when it catches the cancellation and returns."""
    _, outcome = await shut_down_with_short_hook_bound(CancelSwallowingChild)

    assert outcome.result is ShutdownResult.TIMED_OUT


class TimeoutRaisingChild(Resource):
    """Resource whose ``on_shutdown()`` raises ``TimeoutError`` itself, well inside its bound."""

    async def on_shutdown(self) -> None:
        raise TimeoutError("the hook's own operation timed out")


async def test_hook_raising_timeout_error_is_recorded_as_failed_not_timed_out():
    """A hook that raises ``TimeoutError`` on its own raised; only a hook its bound cut off timed out."""
    hassette = make_mock_hassette(sealed=False)
    resource = TimeoutRaisingChild(hassette)
    await resource.initialize()

    outcome = await resource.shutdown()

    assert outcome.result is ShutdownResult.FAILED


async def test_hook_bound_is_clamped_to_the_shutdown_deadline():
    """A hanging hook gets ``shutdown_timeout_seconds`` shortened to what is left of the deadline."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = 30.0

    resource = HangingChild(hassette)
    await resource.initialize()
    resource._shutdown_deadline = deadline_in(0.2)

    loop = asyncio.get_running_loop()
    start_time = loop.time()
    outcome = await asyncio.wait_for(resource.shutdown(), timeout=10)
    elapsed = loop.time() - start_time

    assert elapsed < 3.0, f"the hook ran past the 0.2s deadline toward its 30s cap ({elapsed:.2f}s)"
    assert outcome.result is ShutdownResult.TIMED_OUT


async def test_accepted_initialization_clears_the_previous_shutdown_deadline():
    """A deadline belongs to one shutdown attempt; re-initializing after a clean stop clears it."""
    resource = await make_initialized_shutdown_counter()
    resource._shutdown_deadline = deadline_in(5.0)

    outcome = await resource.shutdown()
    assert outcome.is_restart_safe is True

    await resource.initialize()

    assert resource._shutdown_deadline is None


async def test_cancelling_one_shutdown_awaiter_does_not_cancel_shared_attempt():
    """Cancelling one caller's own wrapping task around ``shutdown()`` must not cancel the
    shared ``_shutdown_task`` attempt -- the other concurrent caller still receives a normal
    completed outcome and the shared task/body are left running to completion.

    ``coordinate_shutdown()`` shields the shared task from each individual awaiter
    (``await asyncio.shield(task)``); cancelling one caller's outer wrapping task only
    interrupts that caller's own await, not the shielded shared task underneath it.
    """
    resource = await make_initialized_shutdown_counter()

    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _gated_on_shutdown() -> None:
        calls.append("called")
        entered.set()
        await release.wait()
        resource.shutdown_count += 1

    resource.on_shutdown = _gated_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    first = asyncio.create_task(resource.shutdown())
    await asyncio.wait_for(entered.wait(), timeout=1)

    second = asyncio.create_task(resource.shutdown())

    # Cancel only the first caller's own wrapping task.
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    shared_task = resource._shutdown_task
    assert shared_task is not None
    assert not shared_task.done(), "cancelling one awaiter must not cancel the shared attempt"

    # Release the gate; the shared attempt completes normally and the surviving caller gets
    # a real completed outcome, not a CancelledError.
    release.set()
    outcome = await second

    assert shared_task.done()
    assert not shared_task.cancelled()
    assert outcome is resource._shutdown_outcome
    assert outcome.is_restart_safe is True
    assert calls == ["called"], "on_shutdown must have run exactly once despite the cancelled awaiter"


async def test_shutdown_rejects_reentrant_call_from_shutdown_hook():
    """A shutdown hook that calls ``self.shutdown()`` (or another lifecycle front door) on
    itself must be rejected with ``LifecycleReentryError`` before any duplicate task creation
    or state mutation -- the calling task *is* the shutdown coordinator being awaited.
    """
    resource = await make_initialized_shutdown_counter()

    captured: list[BaseException] = []
    calls: list[str] = []

    async def _reentrant_on_shutdown() -> None:
        calls.append("called")
        resource.shutdown_count += 1
        try:
            await resource.shutdown()
        except LifecycleReentryError as exc:
            captured.append(exc)

    resource.on_shutdown = _reentrant_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    outcome = await resource.shutdown()

    assert len(captured) == 1
    assert isinstance(captured[0], LifecycleReentryError)
    assert calls == ["called"], "the re-entrant call must not have re-run shutdown"
    assert resource.shutdown_count == 1
    assert outcome is resource._shutdown_outcome


class TrulyResistantChild(Resource):
    """Resource whose ``on_shutdown()`` catches its own cancellation and re-blocks forever.

    Distinct from ``HangingChild``: a plain ``Event().wait()`` is cut off by its hook bound and
    resolves inside the shutdown body. Swallowing the injected ``CancelledError`` and re-awaiting
    resists that bound too (the timeout context manager only injects cancellation once), so only the
    operation's owner walking away -- ``_force_terminal()`` -- can end its shutdown.
    """

    swallowed: asyncio.Event

    async def on_initialize(self) -> None:
        self.swallowed = asyncio.Event()

    async def on_shutdown(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:  # noqa: ASYNC103 -- deliberately swallowed, this is the point of the test
            self.swallowed.set()
            await asyncio.Event().wait()  # ignore cancellation and hang forever


async def test_resistant_hook_holds_shutdown_until_the_owner_force_terminates():
    """Nothing inside the shutdown walks away from a hook that swallows its cancellation: the attempt
    waits until the owner force-terminates the resource, then every caller gets the forced outcome and
    the body is cancelled rather than left running unobserved.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    resource = TrulyResistantChild(hassette)
    await resource.initialize()

    shutdown = asyncio.create_task(resource.shutdown())
    await asyncio.wait_for(resource.swallowed.wait(), timeout=5)
    assert not shutdown.done(), "an interior node must not walk away from a body that outlives its hooks' bound"

    resource._force_terminal()
    outcome = await asyncio.wait_for(shutdown, timeout=5)

    assert outcome.result is ShutdownResult.INCOMPLETE
    assert outcome.is_restart_safe is False
    body_task = resource._shutdown_body_task
    assert body_task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(body_task, timeout=5)
    assert body_task.cancelled()


class SlowBodyResource(Resource):
    """Resource whose shutdown body itself (not a hook) takes longer than ``shutdown_timeout_seconds``."""

    async def _shutdown_body(self) -> ShutdownOutcome:
        await asyncio.sleep(0.3)
        return await super()._shutdown_body()


async def test_coordinator_waits_for_the_body_without_a_bound_of_its_own():
    """Only leaves bound themselves: a body that outlasts ``shutdown_timeout_seconds`` without any hook
    hanging is waited for and completes restart-safe.
    """
    _, outcome = await shut_down_with_short_hook_bound(SlowBodyResource)

    assert outcome.is_restart_safe is True, f"expected a clean outcome, got {outcome}"


def raise_boom(_resource, _reason=None):
    raise RuntimeError("boom")


async def test_coordinator_failure_records_coordinator_failed_and_blocks_restart(monkeypatch):
    """When something raises inside the coordinator's try body itself (not the shutdown body
    task), the outer ``except Exception`` block stores an ``INCOMPLETE`` outcome, the
    exception propagates out of ``shutdown()``, and a subsequent ``initialize()`` is refused via
    ``RestartRefusedError`` -- the "a completed attempt always produces an outcome" invariant holds
    even when the coordinator fails outside the shutdown body.
    """
    resource = await make_initialized_shutdown_counter()

    # request_shutdown() is called unqualified inside _run_shutdown_coordinator's try body, so
    # patching the module-level name it resolves against is enough to fail the coordinator
    # before it ever creates the shutdown body task.
    monkeypatch.setattr(lifecycle, "request_shutdown", raise_boom)

    with pytest.raises(RuntimeError, match="boom"):
        await resource.shutdown()

    outcome = resource._shutdown_outcome
    assert outcome is not None
    assert outcome.result is ShutdownResult.INCOMPLETE
    assert outcome.is_restart_safe is False

    with pytest.raises(RestartRefusedError):
        await resource.initialize()


async def test_coordinator_failure_merges_with_preexisting_force_terminal_evidence(monkeypatch):
    """A coordinator failure that occurs after a force-terminal outcome was already stored on the
    resource merges into that outcome rather than overwriting it: the stored outcome is merged first, so
    its "was force-terminated" reason is the one kept at ``INCOMPLETE``.
    """
    resource = await make_initialized_shutdown_counter()

    # Simulate force-terminal evidence already having been recorded on this resource before the
    # coordinator's try body raises (e.g. a concurrent _force_terminal() call from a parent's
    # own shutdown body).
    resource._force_terminal()
    existing_outcome = resource._shutdown_outcome
    assert existing_outcome is not None
    assert existing_outcome.result is ShutdownResult.INCOMPLETE

    monkeypatch.setattr(lifecycle, "request_shutdown", raise_boom)

    with pytest.raises(RuntimeError, match="boom"):
        await resource.shutdown()

    outcome = resource._shutdown_outcome
    assert outcome is not None
    assert outcome.result is ShutdownResult.INCOMPLETE
    assert outcome.reason == existing_outcome.reason, "the stored force-terminal reason must win the merge"
    assert outcome.is_restart_safe is False


class ThreeHangingHooksParent(Resource):
    """Resource whose ``before_shutdown``, ``on_shutdown`` and ``after_shutdown`` all hang."""

    async def before_shutdown(self) -> None:
        await asyncio.Event().wait()

    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()

    async def after_shutdown(self) -> None:
        await asyncio.Event().wait()


async def test_each_hanging_hook_gets_its_own_bound_and_the_tail_still_runs():
    """Every hook is bounded on its own, so three hanging hooks cost three bounds, not the whole
    shutdown; task-cancel, cleanup and children still run, and nothing is force-terminated.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = ThreeHangingHooksParent(hassette)
    hanging_child = parent.add_child(HangingChild)
    await parent.initialize()
    await hanging_child.initialize()

    loop = asyncio.get_running_loop()
    start = loop.time()
    outcome = await asyncio.wait_for(parent.shutdown(), timeout=10)
    elapsed = loop.time() - start

    assert outcome.result is ShutdownResult.TIMED_OUT
    child_outcome = hanging_child.shutdown_outcome
    assert child_outcome is not None
    assert child_outcome.result is ShutdownResult.TIMED_OUT
    assert elapsed < 3.0, f"four 0.1s hook bounds took {elapsed:.2f}s"


async def test_hooks_share_the_deadline_once_it_is_closer_than_their_bounds():
    """Once the shutdown deadline is closer than ``shutdown_timeout_seconds``, every later hook gets only
    what is left of it, so the whole shutdown ends near the deadline.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = 30.0

    parent = ThreeHangingHooksParent(hassette)
    await parent.initialize()
    parent._shutdown_deadline = deadline_in(0.3)

    loop = asyncio.get_running_loop()
    start = loop.time()
    outcome = await asyncio.wait_for(parent.shutdown(), timeout=10)
    elapsed = loop.time() - start

    assert outcome.result is ShutdownResult.TIMED_OUT
    assert elapsed < 3.0, f"hooks ran past the 0.3s deadline ({elapsed:.2f}s)"


async def shut_down_with_short_hook_bound(resource_cls: type[Resource]) -> tuple[Resource, ShutdownOutcome]:
    """Initialize a ``resource_cls`` with ``SHORT_SHUTDOWN_TIMEOUT_SECONDS`` as its hook bound, then shut it down."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    resource = resource_cls(hassette)
    await resource.initialize()
    return resource, await resource.shutdown()
