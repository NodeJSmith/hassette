"""Integration tests: a dead event bus ends the process without hanging its shutdown (spec 134 D3, D9).

Each test boots a real Hassette (no Home Assistant, see ``wire_hassette_without_ha``) and fills the
event channel at the moment the bus dies, so nothing drains it. Any send that then blocks would hold
teardown until a shutdown deadline force-terminates it. A clean bus-death exit therefore raises
``FatalError`` with nothing force-terminated and every resource STOPPED.
"""

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from anyio import WouldBlock

from hassette import Hassette
from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.testing import wait_for
from hassette.types.enums import ResourceStatus
from tests.support.bare_hassette import WEBAPI_READY_TIMEOUT, teardown_bare_hassette, wire_hassette_without_ha
from tests.support.factories import make_hassette_event

EXIT_TIMEOUT_SECONDS = 90.0
"""Outer bound on the whole exit; well past the default 45s total shutdown, so a force-terminated exit still ends."""


def walk_resources(root: Resource) -> Iterator[Resource]:
    for child in root.children:
        yield child
        yield from walk_resources(child)


def fill_event_channel(hassette: Hassette) -> None:
    """Queue events until the channel's buffer is full, without waiting for a receiver."""
    send_stream = hassette.event_stream_service._send_stream  # coordinator-internal
    while True:
        try:
            send_stream.send_nowait(make_hassette_event())
        except WouldBlock:
            return


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
        loop = asyncio.get_running_loop()
        previous_task_factory = loop.get_task_factory()
        hassette, never_connects, instance_token = wire_hassette_without_ha(tmp_path, unused_tcp_port_factory())
        run_task = asyncio.create_task(hassette.run_forever())
        try:
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
        finally:
            never_connects.set()
            await teardown_bare_hassette(
                hassette, run_task, loop, previous_task_factory=previous_task_factory, instance_token=instance_token
            )

        assert_clean_fatal_teardown(hassette)


class TestBusDeathAtBoot:
    @pytest.mark.parametrize("failure", ["raises", "hangs"])
    async def test_bus_init_failure_exits_without_hanging(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int], failure: str
    ) -> None:
        """A bus that never reaches serve() at boot (init raised, or timed out) still tears down cleanly."""
        loop = asyncio.get_running_loop()
        previous_task_factory = loop.get_task_factory()
        hassette, never_connects, instance_token = wire_hassette_without_ha(
            tmp_path, unused_tcp_port_factory(), config_overrides={"lifecycle": {"startup_timeout_seconds": 1}}
        )
        never_ready = asyncio.Event()

        async def failing_before_initialize() -> None:
            fill_event_channel(hassette)
            if failure == "raises":
                raise RuntimeError("bus init failed in test")
            await never_ready.wait()

        hassette.bus_service.before_initialize = failing_before_initialize  # pyright: ignore[reportAttributeAccessIssue]
        run_task = asyncio.create_task(hassette.run_forever())
        try:
            await run_until_fatal(run_task)
        finally:
            never_ready.set()
            never_connects.set()
            await teardown_bare_hassette(
                hassette, run_task, loop, previous_task_factory=previous_task_factory, instance_token=instance_token
            )

        assert_clean_fatal_teardown(hassette)
