"""A harness whose startup fails partway must restore the process-global state it already changed (#4259).

``HassetteHarness.start()`` swaps the loop's task factory, configures the ``date_utils`` timezone and
(for a bare harness) sets ``HASSETTE_INSTANCE`` before it waits for readiness. When that wait fails,
both ``AppTestHarness`` and a bare ``async with HassetteHarness(...)`` must still undo it, or the leak
breaks later tests on the same worker.

The failure comes from the HA API boundary: the fake API's state fetch raises, so StateProxy never
reaches its initial state capability after every child (bus, scheduler, state proxy) has really
started. That is the partial start the cleanup has to survive. On a loaded runner the shortened
readiness timeout can instead expire while the children are still finishing startup; that is an
equally partial start, so either timeout satisfies the tests.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import hassette.utils.date_utils as date_utils
from hassette import context
from hassette.app import App
from hassette.testing import AppTestHarness, HassetteHarness, make_test_config
from hassette.testing._harness_support import Timeouts

# Long enough for real children to start on a slow CI runner, short enough to keep the test quick.
READINESS_TIMEOUT_SECONDS = 1.0


class _PartialStartApp(App):
    """App whose harness never gets far enough to instantiate it."""


@contextmanager
def _ha_state_fetch_fails() -> Iterator[None]:
    """Make the harness's fake HA API fail every state fetch, so initial-state readiness times out."""
    original = HassetteHarness._install_default_mocks

    def install_failing_api(self: HassetteHarness) -> None:
        original(self)
        self.hassette._api.get_states_raw.side_effect = ConnectionError("Home Assistant unreachable")  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]

    with (
        patch.object(HassetteHarness, "_install_default_mocks", install_failing_api),
        patch.object(Timeouts, "WAIT_FOR_READY", READINESS_TIMEOUT_SECONDS),
        pytest.raises(TimeoutError, match=r"initial state capability|did not become ready"),
    ):
        yield


def _global_state() -> tuple[object, object, object]:
    return (
        asyncio.get_running_loop().get_task_factory(),
        date_utils._configured_tz,
        context.HASSETTE_INSTANCE.get(None),
    )


async def test_app_harness_restores_globals_when_start_fails(tmp_path: Path) -> None:
    before = _global_state()

    with _ha_state_fetch_fails():
        async with AppTestHarness(_PartialStartApp, config={}, tmp_path=tmp_path):
            pytest.fail("harness should not have started")

    assert _global_state() == before


async def test_bare_harness_restores_globals_when_start_fails(tmp_path: Path) -> None:
    before = _global_state()
    harness = (
        HassetteHarness(make_test_config(data_dir=tmp_path, timezone="Pacific/Chatham"))
        .with_bus()
        .with_scheduler()
        .with_state_proxy()
    )

    with _ha_state_fetch_fails():
        async with harness:
            pytest.fail("harness should not have started")

    assert _global_state() == before


async def test_harness_closes_bus_stream_when_bus_never_started(tmp_path: Path) -> None:
    """A start that fails before the bus enters its drain loop must still close the bus's stream clone.

    Only a drain loop closes that clone on its own, so this replaces the child startup wait to fail
    before any child runs: a readiness timeout that lands ahead of the bus is too timing-dependent
    to produce from a boundary.
    """
    harness = HassetteHarness(make_test_config(data_dir=tmp_path)).with_bus()

    async def fail_before_children_start(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("children never became ready")

    with (
        patch("hassette.testing._harness.start_children_and_wait", fail_before_children_start),
        pytest.raises(TimeoutError, match="never became ready"),
    ):
        async with harness:
            pytest.fail("harness should not have started")

    bus_stream = harness.hassette._bus_service.stream  # pyright: ignore[reportOptionalMemberAccess]
    assert bus_stream._closed
