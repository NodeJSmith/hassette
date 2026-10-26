"""Unit tests for ``wait_for_wave``: a startup wave joins its members' initialization attempts and readiness.

A wave is done when every attempt has finished and every member is ready. A failed attempt fails the wave at
once, even when its resource already marked itself ready (spec 134 D1). Shutdown wins over every other outcome.
"""

import asyncio

import pytest

from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.utils.service_utils import WaveOutcome, wait_for_wave
from tests.support.mock_hassette import make_mock_hassette

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


async def wave(
    attempts: "dict[Resource, asyncio.Task[None] | None]", shutdown: asyncio.Event, timeout: float = WAIT_TIMEOUT
):
    return await asyncio.wait_for(
        wait_for_wave(attempts, timeout=timeout, shutdown_event=shutdown), timeout=WAIT_TIMEOUT * 2
    )


async def test_ok_when_attempts_finish_and_members_ready():
    a, b = make_members(2)
    mark_ready(a)
    mark_ready(b)

    result = await wave({a: asyncio.create_task(finish()), b: asyncio.create_task(finish())}, asyncio.Event())

    assert result.outcome is WaveOutcome.OK
    assert result.resources == ()


async def test_waits_for_readiness_after_attempt_finishes():
    (a,) = make_members(1)
    attempt = asyncio.create_task(finish())
    waiting = asyncio.create_task(wave({a: attempt}, asyncio.Event()))
    await attempt
    assert not waiting.done(), "a finished attempt is not readiness"

    mark_ready(a)
    result = await waiting

    assert result.outcome is WaveOutcome.OK


async def test_failed_attempt_fails_wave_even_when_member_already_ready():
    a, b = make_members(2)
    mark_ready(a)  # marked ready inside on_initialize, before a child failed
    hung = asyncio.create_task(hang())

    result = await wave({a: asyncio.create_task(fail("child failed")), b: hung}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
    assert result.resources == (a,)
    hung.cancel()


async def test_failure_names_every_member_failed_by_then():
    a, b = make_members(2)
    attempt_a = asyncio.create_task(fail("a"))
    attempt_b = asyncio.create_task(fail("b"))
    await asyncio.wait({attempt_a, attempt_b})

    result = await wave({a: attempt_a, b: attempt_b}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
    assert set(result.resources) == {a, b}


async def test_shutdown_does_not_wait_for_hung_attempt():
    (a,) = make_members(1)
    hung = asyncio.create_task(hang())
    shutdown = asyncio.Event()
    waiting = asyncio.create_task(wave({a: hung}, shutdown))

    shutdown.set()
    result = await waiting

    assert result.outcome is WaveOutcome.SHUTDOWN
    assert not hung.done(), "the wave must not cancel or wait for the attempt itself"
    hung.cancel()


async def test_cancelled_attempt_during_shutdown_is_shutdown():
    (a,) = make_members(1)
    attempt = asyncio.create_task(hang())
    shutdown = asyncio.Event()
    shutdown.set()
    attempt.cancel()

    result = await wave({a: attempt}, shutdown)

    assert result.outcome is WaveOutcome.SHUTDOWN


async def test_cancelled_attempt_without_shutdown_is_failure():
    (a,) = make_members(1)
    attempt = asyncio.create_task(hang())
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    result = await wave({a: attempt}, asyncio.Event())

    assert result.outcome is WaveOutcome.FAILED
    assert result.resources == (a,)


async def test_timeout_names_unfinished_members():
    a, b = make_members(2)
    mark_ready(a)
    hung = asyncio.create_task(hang())

    result = await wave({a: asyncio.create_task(finish()), b: hung}, asyncio.Event(), timeout=SHORT_TIMEOUT)

    assert result.outcome is WaveOutcome.TIMEOUT
    assert result.resources == (b,)
    hung.cancel()


async def test_member_without_attempt_only_needs_readiness():
    (a,) = make_members(1)
    mark_ready(a)

    result = await wave({a: None}, asyncio.Event())

    assert result.outcome is WaveOutcome.OK
