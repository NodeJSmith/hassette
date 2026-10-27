"""Integration tests: a dead event bus ends the process without hanging its shutdown (spec 134 D3, D9).

Each test boots a real Hassette (no Home Assistant, see ``wire_hassette_without_ha``) and fills the
event channel at the moment the bus dies, so nothing drains it. Any send that then blocks would hold
teardown until a shutdown deadline force-terminates it. A clean bus-death exit therefore raises
``FatalError`` with nothing force-terminated and every resource STOPPED.
"""

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal

import pytest
from hassette_wire import ResourceStatus

from hassette import Hassette
from hassette.config.models import LifecycleConfig
from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.testing import wait_for
from tests.support.bare_hassette import WEBAPI_READY_TIMEOUT, running_bare_hassette
from tests.support.helpers import fill_event_channel

EXIT_TIMEOUT_SECONDS = 90.0
"""Outer bound on the whole exit; well past the default 45s total shutdown, so a force-terminated exit still ends."""


def walk_resources(root: Resource) -> Iterator[Resource]:
    for child in root.children:
        yield child
        yield from walk_resources(child)


def assert_clean_fatal_teardown(hassette: Hassette) -> None:
    assert hassette.fatal_shutdown_reason is not None
    assert "BusService" in hassette.fatal_shutdown_reason
    assert hassette.force_terminated_work == (), "no send may block teardown into a force-termination"
    not_stopped = {r.unique_name: r.status for r in walk_resources(hassette) if r.status != ResourceStatus.STOPPED}
    assert not_stopped == {}, "every resource reaches STOPPED during the fatal teardown"
    assert hassette.status == ResourceStatus.STOPPED


async def run_until_fatal(run_task: asyncio.Task[None]) -> None:
    with pytest.raises(FatalError):
        await asyncio.wait_for(run_task, timeout=EXIT_TIMEOUT_SECONDS)


class TestBusDeathAfterStartup:
    async def test_unrequested_bus_cancel_exits_without_hanging(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
    ) -> None:
        """A bus serve task cancelled without a shutdown request ends the process cleanly."""
        async with running_bare_hassette(tmp_path, unused_tcp_port_factory()) as (hassette, run_task):
            await wait_for(
                lambda: hassette._web_api_service is not None and hassette._web_api_service.is_ready(),
                timeout=WEBAPI_READY_TIMEOUT,
                desc="WebApiService ready",
            )
            serve_task = hassette.bus_service._serve_task  # coordinator-internal
            assert serve_task is not None
            # No await between the cancel and the fill: the bus can't drain anything before it dies.
            serve_task.cancel()
            fill_event_channel(hassette)

            await run_until_fatal(run_task)

        assert_clean_fatal_teardown(hassette)


class TestBusDeathAtBoot:
    @pytest.mark.parametrize("failure", ["raises", "hangs"])
    async def test_bus_init_failure_exits_without_hanging(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int], failure: Literal["raises", "hangs"]
    ) -> None:
        """A bus that never reaches serve() at boot still tears down cleanly.

        With the channel full, both cases exit through the startup wave's timeout: a raising hook's
        FAILED send blocks before the failure reaches the wave, which is an accepted limitation.
        """
        never_ready = asyncio.Event()

        def break_bus_init(hassette: Hassette) -> None:
            async def broken_before_initialize() -> None:
                fill_event_channel(hassette)
                if failure == "raises":
                    raise RuntimeError("bus init failed in test")
                await never_ready.wait()

            hassette.bus_service.before_initialize = broken_before_initialize  # pyright: ignore[reportAttributeAccessIssue]

        async with running_bare_hassette(
            tmp_path,
            unused_tcp_port_factory(),
            prepare=break_bus_init,
            config_overrides={"lifecycle": LifecycleConfig(startup_timeout_seconds=1)},
        ) as (hassette, run_task):
            try:
                await run_until_fatal(run_task)
            finally:
                never_ready.set()

        assert_clean_fatal_teardown(hassette)
