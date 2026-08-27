"""Tests for hassette.resources.operations.run_hooks() error-handling branches.

run_hooks() is the shared hook-runner behind both initialize() (continue_on_error=False)
and shutdown() (continue_on_error=True). Verifies:
- A generic Exception with continue_on_error=False marks the resource FAILED and re-raises,
  stopping the loop before later hooks run.
- A generic Exception with continue_on_error=True marks the resource FAILED but does NOT
  re-raise, and the loop continues to the next hook.
- asyncio.CancelledError always marks the resource FAILED and re-raises, regardless of
  continue_on_error — and always stops the loop (unlike a generic Exception under
  continue_on_error=True).
"""

import asyncio

import pytest

from hassette.resources.operations import run_hooks
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus

from .conftest import ConcreteResource


async def make_starting_resource() -> ConcreteResource:
    """A resource in STARTING status — the real predecessor state when run_hooks() runs."""
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)
    resource._status = ResourceStatus.STARTING
    return resource


class TestGenericExceptionContinueOnErrorFalse:
    async def test_reraises_and_stops_the_loop(self) -> None:
        resource = await make_starting_resource()
        calls: list[str] = []

        async def boom() -> None:
            calls.append("boom")
            raise RuntimeError("hook boom")

        async def never_runs() -> None:
            calls.append("never_runs")

        with pytest.raises(RuntimeError, match="hook boom"):
            await run_hooks(resource, [boom, never_runs], continue_on_error=False)

        assert calls == ["boom"], "the loop must stop after the raising hook"
        assert resource.status == ResourceStatus.FAILED

    async def test_returns_empty_tuple_when_every_hook_succeeds(self) -> None:
        resource = await make_starting_resource()

        async def fine() -> None:
            return None

        handled = await run_hooks(resource, [fine, fine], continue_on_error=False)

        assert handled == (), "raise-on-first-error mode never collects failures — it re-raises them"


class TestGenericExceptionContinueOnErrorTrue:
    async def test_does_not_reraise_and_continues_the_loop(self) -> None:
        resource = await make_starting_resource()
        calls: list[str] = []

        async def boom() -> None:
            calls.append("boom")
            raise RuntimeError("hook boom")

        async def after() -> None:
            calls.append("after")

        handled = await run_hooks(resource, [boom, after], continue_on_error=True)

        assert calls == ["boom", "after"], "the loop must continue past the raising hook"
        assert resource.status == ResourceStatus.FAILED
        assert len(handled) == 1
        assert isinstance(handled[0], RuntimeError)
        assert str(handled[0]) == "hook boom"

    async def test_collects_every_handled_failure_in_order(self) -> None:
        """Every failing hook's exception is returned, not just the first one."""
        resource = await make_starting_resource()

        first_error = RuntimeError("first boom")
        second_error = ValueError("second boom")

        async def boom_one() -> None:
            raise first_error

        async def fine() -> None:
            return None

        async def boom_two() -> None:
            raise second_error

        handled = await run_hooks(resource, [boom_one, fine, boom_two], continue_on_error=True)

        assert handled == (first_error, second_error), "handled failures must be returned in occurrence order"

    async def test_returns_empty_tuple_when_no_hook_fails(self) -> None:
        resource = await make_starting_resource()
        calls: list[str] = []

        async def fine_one() -> None:
            calls.append("fine_one")

        async def fine_two() -> None:
            calls.append("fine_two")

        handled = await run_hooks(resource, [fine_one, fine_two], continue_on_error=True)

        assert calls == ["fine_one", "fine_two"]
        assert handled == ()


class TestCancelledErrorAlwaysPropagates:
    async def test_continue_on_error_false_reraises_and_fails(self) -> None:
        resource = await make_starting_resource()

        async def cancel_me() -> None:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await run_hooks(resource, [cancel_me], continue_on_error=False)

        assert resource.status == ResourceStatus.FAILED

    async def test_continue_on_error_true_still_reraises_and_stops_the_loop(self) -> None:
        """Unlike a generic Exception under continue_on_error=True, CancelledError always
        stops the loop and propagates — the shutdown-hook runner does not swallow it.
        """
        resource = await make_starting_resource()
        calls: list[str] = []

        async def cancel_me() -> None:
            calls.append("cancelled_hook")
            raise asyncio.CancelledError()

        async def never_runs() -> None:
            calls.append("never_runs")

        with pytest.raises(asyncio.CancelledError):
            await run_hooks(resource, [cancel_me, never_runs], continue_on_error=True)

        assert calls == ["cancelled_hook"]
        assert resource.status == ResourceStatus.FAILED
