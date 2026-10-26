"""Unit tests for ``wait_for_wave``: a startup wave joins its members' initialization attempts and readiness.

A wave is done when every attempt has finished and every member is ready, or is an optional service whose serve
task has ended (spec 134 D7). A failed attempt fails the wave at once, even when its resource already marked itself
ready (spec 134 D1). Shutdown wins over every other outcome.
"""

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from hassette_wire import ResourceStatus

from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.resources.service import Service
from hassette.testing import wait_for
from hassette.utils.service_utils import (
    WaveOutcome,
    WaveResult,
    awaiting_location,
    describe_error,
    describe_wave_failure,
    describe_wave_members,
    wait_for_wave,
)
from tests.support.mock_hassette import make_mock_hassette

if TYPE_CHECKING:
    from collections.abc import Mapping

WAIT_TIMEOUT = 5.0
"""Wave budget for waits expected to finish on their own; far above how long any of them take."""

SHORT_TIMEOUT = 0.05
"""Wave budget for the wait that is expected to time out."""


class WaveMember(Resource):
    """Resource standing in for a wave member; tests drive its readiness and attempt directly."""


def make_members(count: int) -> list[WaveMember]:
    hassette = make_mock_hassette(sealed=False)
    return [WaveMember(hassette) for _ in range(count)]


async def finish() -> None:
    return None


async def fail(message: str) -> None:
    raise RuntimeError(message)


async def hang() -> None:
    await asyncio.Event().wait()


@pytest.fixture
async def hung():
    """An attempt that never finishes, cancelled at teardown even when the test fails."""
    task = asyncio.create_task(hang())
    yield task
    task.cancel()


async def run_wave(
    attempts: "Mapping[Resource, asyncio.Task[Any] | None]", shutdown: asyncio.Event, timeout: float = WAIT_TIMEOUT
):
    return await asyncio.wait_for(
        wait_for_wave(attempts, timeout=timeout, shutdown_event=shutdown), timeout=WAIT_TIMEOUT * 2
    )


async def test_ok_when_attempts_finish_and_members_ready():
    a, b = make_members(2)
    mark_ready(a)
    mark_ready(b)

    result = await run_wave({a: asyncio.create_task(finish()), b: asyncio.create_task(finish())}, asyncio.Event())

    assert result.outcome is WaveOutcome.OK
    assert result.resources == ()


async def test_waits_for_readiness_after_attempt_finishes():
    (a,) = make_members(1)
    attempt = asyncio.create_task(finish())
    waiting = asyncio.create_task(run_wave({a: attempt}, asyncio.Event()))
    await attempt
    assert not waiting.done(), "a finished attempt is not readiness"

    mark_ready(a)
    result = await waiting

    assert result.outcome is WaveOutcome.OK


async def test_failed_attempt_fails_wave_even_when_member_already_ready(hung: asyncio.Task[None]):
    a, b = make_members(2)
    mark_ready(a)  # marked ready inside on_initialize, before a child failed

    result = await run_wave({a: asyncio.create_task(fail("child failed")), b: hung}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
    assert result.resources == (a,)
    (error,) = result.errors
    assert isinstance(error, RuntimeError)
    assert str(error) == "child failed"


async def test_failure_names_every_member_failed_by_then():
    a, b = make_members(2)
    attempt_a = asyncio.create_task(fail("a"))
    attempt_b = asyncio.create_task(fail("b"))
    await asyncio.wait({attempt_a, attempt_b})

    result = await run_wave({a: attempt_a, b: attempt_b}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
    assert set(result.resources) == {a, b}


async def test_shutdown_does_not_wait_for_hung_attempt(hung: asyncio.Task[None]):
    (a,) = make_members(1)
    shutdown = asyncio.Event()
    waiting = asyncio.create_task(run_wave({a: hung}, shutdown))

    shutdown.set()
    result = await waiting

    assert result.outcome is WaveOutcome.SHUTDOWN
    assert not hung.done(), "the wave must not cancel or wait for the attempt itself"


async def test_cancelled_attempt_during_shutdown_is_shutdown():
    (a,) = make_members(1)
    attempt = asyncio.create_task(hang())
    shutdown = asyncio.Event()
    shutdown.set()
    attempt.cancel()

    result = await run_wave({a: attempt}, shutdown)

    assert result.outcome is WaveOutcome.SHUTDOWN


async def test_cancelled_attempt_without_shutdown_is_failure():
    (a,) = make_members(1)
    attempt = asyncio.create_task(hang())
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    result = await run_wave({a: attempt}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
    assert result.resources == (a,)
    assert result.errors == (None,)


async def test_timeout_names_unfinished_members(hung: asyncio.Task[None]):
    a, b = make_members(2)
    mark_ready(a)

    result = await run_wave({a: asyncio.create_task(finish()), b: hung}, asyncio.Event(), timeout=SHORT_TIMEOUT)

    assert result.outcome is WaveOutcome.TIMEOUT
    assert result.resources == (b,)


async def test_member_without_attempt_only_needs_readiness():
    (a,) = make_members(1)
    mark_ready(a)

    result = await run_wave({a: None}, asyncio.Event())

    assert result.outcome is WaveOutcome.OK


class StuckChild(Resource):
    """Child a test leaves in STARTING, standing in for one whose initialization hangs."""


async def test_description_names_the_child_still_starting():
    (parent,) = make_members(1)
    child = parent.add_child(StuckChild)
    child._status = ResourceStatus.STARTING

    description = describe_wave_members([parent])

    assert "WaveMember: status=not_started" in description
    assert "StuckChild(starting)" in description


class CountingMember(Resource):
    """Wave member that counts how often the wave starts waiting for its readiness."""

    wait_calls: int = 0

    async def wait_ready(self, timeout: float | None = None) -> None:
        self.wait_calls += 1
        await super().wait_ready(timeout)


async def test_member_that_loses_readiness_mid_wave_is_awaited_again():
    """Readiness is read live: a member that goes ready, then not ready, must become ready again."""
    hassette = make_mock_hassette(sealed=False)
    a, b = CountingMember(hassette), CountingMember(hassette)
    mark_ready(b)
    gate = asyncio.Event()
    gated = asyncio.create_task(gate.wait())
    waiting = asyncio.create_task(run_wave({a: asyncio.create_task(finish()), b: gated}, asyncio.Event()))
    await wait_for(lambda: a.wait_calls == 1, desc="wave waiting for a's readiness")

    mark_ready(a)
    mark_not_ready(a, "serve() failed")  # the waker fired, but a is not ready any more
    gate.set()  # the last attempt finishes, leaving only a's readiness to wait for
    await wait_for(lambda: a.wait_calls == 2, desc="wave waiting for a's readiness again")

    mark_ready(a)
    result = await waiting

    assert result.outcome is WaveOutcome.OK


async def test_awaiting_location_names_the_waiting_code_not_asyncio(hung: asyncio.Task[None]):
    coro: Any = hung.get_coro()
    await wait_for(lambda: coro.cr_await is not None, desc="hang() suspended")

    location = awaiting_location(hung)

    assert "test_wait_for_wave.py" in location
    assert location.endswith("in hang")


def test_describe_error():
    assert describe_error(RuntimeError("boom")) == "RuntimeError: boom"
    assert describe_error(TimeoutError()) == "TimeoutError"
    assert describe_error(None) == "cancelled"


def test_describe_wave_failure_names_each_failed_member_and_cause():
    first, second = make_members(2)
    result = WaveResult(WaveOutcome.FAILED, (first, second), (RuntimeError("boom"), None))

    assert describe_wave_failure(result, timeout=30.0) == (
        "startup failure: failed to initialize: WaveMember (RuntimeError: boom), WaveMember (cancelled)"
    )


def test_describe_wave_failure_names_each_unfinished_member_and_the_timeout():
    [member] = make_members(1)
    result = WaveResult(WaveOutcome.TIMEOUT, (member,))

    assert describe_wave_failure(result, timeout=30.0) == (
        "startup failure: did not finish starting within 30.0s: WaveMember"
    )


class OptionalWatcher(Service):
    """Optional service that, like the file watchers, would mark ready inside serve()."""

    required: ClassVar[bool] = False

    async def serve(self) -> None:
        await self.shutdown_event.wait()


class RequiredLoop(Service):
    required: ClassVar[bool] = True

    async def serve(self) -> None:
        await self.shutdown_event.wait()


async def test_optional_member_whose_serve_ends_before_ready_settles_the_wave_promptly():
    """An optional watcher whose serve() fails before marking ready doesn't hold boot to the timeout (spec 134 D7)."""
    member = OptionalWatcher(make_mock_hassette(sealed=False))
    serve_ended = asyncio.Event()

    async def serve_until_released() -> None:
        await serve_ended.wait()
        raise RuntimeError("watcher failed")

    member._serve_task = asyncio.create_task(serve_until_released())
    wave = asyncio.create_task(run_wave({member: asyncio.create_task(finish())}, asyncio.Event()))
    await asyncio.sleep(0)
    assert not wave.done(), "the wave waits while the optional member's serve task is still running"

    serve_ended.set()
    result = await asyncio.wait_for(wave, timeout=1.0)

    assert result.outcome is WaveOutcome.OK
    assert member._serve_task.done()


async def test_required_member_whose_serve_ends_before_ready_still_holds_the_wave():
    """Only an optional member settles without readiness; a required one's serve failure is a fatal report instead."""
    member = RequiredLoop(make_mock_hassette(sealed=False))
    member._serve_task = asyncio.create_task(finish())

    result = await run_wave({member: asyncio.create_task(finish())}, asyncio.Event(), timeout=SHORT_TIMEOUT)

    assert result.outcome is WaveOutcome.TIMEOUT
    assert result.resources == (member,)


async def test_failed_attempt_of_optional_member_still_fails_the_wave():
    """A boot-time start failure stays fatal for every member (spec 134 D1)."""
    member = OptionalWatcher(make_mock_hassette(sealed=False))

    result = await run_wave({member: asyncio.create_task(fail("init broke"))}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
