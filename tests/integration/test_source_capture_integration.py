"""Integration tests for source capture on Bus and Scheduler registrations.

Verifies that source_location and registration_source are captured from user code
(the call site in this test file) rather than asyncio internals or hassette internals.
"""

import typing
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.scheduler.triggers import Every

if typing.TYPE_CHECKING:
    from hassette.bus import Bus
    from hassette.scheduler import Scheduler
    from hassette.test_utils.harness import HassetteHarness


THIS_FILE = str(Path(__file__).resolve())


@pytest.fixture
def bus(hassette_with_scheduler: "HassetteHarness") -> "Bus":
    return hassette_with_scheduler.bus


@pytest.fixture
def scheduler(hassette_with_scheduler: "HassetteHarness") -> "Scheduler":
    return hassette_with_scheduler.scheduler


async def test_bus_on_state_change_captures_test_file_source(bus: "Bus") -> None:
    """Bus.on_state_change() should capture this test file as source_location, not asyncio internals."""

    async def my_handler(event) -> None:
        pass

    add_listener_mock = AsyncMock()
    original_service = bus.bus_service
    bus.bus_service = Mock(add_listener=add_listener_mock)

    try:
        await bus.on_state_change("light.kitchen", handler=my_handler, name="source_capture_test")

        add_listener_mock.assert_called_once()
        listener = add_listener_mock.call_args.args[0]

        assert listener.identity.source_location, "source_location should not be empty"
        assert THIS_FILE in listener.identity.source_location, (
            f"source_location should point to this test file, got: {listener.identity.source_location}"
        )
        assert "asyncio" not in listener.identity.source_location, (
            f"source_location should not contain asyncio internals, got: {listener.identity.source_location}"
        )
        assert listener.identity.registration_source, "registration_source should not be empty"
        assert "on_state_change" in listener.identity.registration_source, (
            f"registration_source should contain the method call, got: {listener.identity.registration_source}"
        )
    finally:
        bus.bus_service = original_service


async def test_bus_on_captures_test_file_source(bus: "Bus") -> None:
    """Bus.on() should capture this test file as source_location."""

    async def my_handler(event) -> None:
        pass

    add_listener_mock = AsyncMock()
    original_service = bus.bus_service
    bus.bus_service = Mock(add_listener=add_listener_mock)

    try:
        await bus.on(topic="test.topic", handler=my_handler, name="bus_on_source_test")

        add_listener_mock.assert_called_once()
        listener = add_listener_mock.call_args.args[0]

        assert listener.identity.source_location, "source_location should not be empty"
        assert THIS_FILE in listener.identity.source_location, (
            f"source_location should point to this test file, got: {listener.identity.source_location}"
        )
    finally:
        bus.bus_service = original_service


async def test_scheduler_schedule_captures_test_file_source(scheduler: "Scheduler") -> None:
    """Scheduler.schedule() should capture this test file as source_location."""

    async def my_job() -> None:
        pass

    add_job_mock = AsyncMock(return_value=None)
    original_service = scheduler.scheduler_service
    scheduler.scheduler_service = Mock(add_job=add_job_mock)

    try:
        trigger = Every(hours=1)
        job = await scheduler.schedule(my_job, trigger, name="test_job")

        assert job.source_location, "source_location should not be empty"
        assert THIS_FILE in job.source_location, (
            f"source_location should point to this test file, got: {job.source_location}"
        )
        assert "asyncio" not in job.source_location, (
            f"source_location should not contain asyncio internals, got: {job.source_location}"
        )
        assert job.registration_source, "registration_source should not be empty"
    finally:
        scheduler.scheduler_service = original_service
