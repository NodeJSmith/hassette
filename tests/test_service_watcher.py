import asyncio

import pytest

from hassette.events import ServiceStatusPayload
from hassette.resources.base import Service
from hassette.services.service_watcher import _ServiceWatcher
from hassette.types.enums import ResourceStatus


@pytest.fixture
def get_service_watcher_mock(hassette_with_bus):
    """Return a fresh service watcher for each test."""
    return _ServiceWatcher(hassette_with_bus)


def get_dummy_service(called: dict[str, int], hassette) -> Service:
    class _Dummy(Service):
        """Does nothing, just tracks calls."""

        async def serve(self):
            pass

        async def on_shutdown(self):
            called["cancel"] += 1

        async def on_initialize(self):
            called["start"] += 1

    return _Dummy(hassette)


async def test_restart_service_cancels_then_starts(get_service_watcher_mock: _ServiceWatcher):
    """Restarting a failed service cancels and reinitializes it."""
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(call_counts, get_service_watcher_mock.hassette)
    get_service_watcher_mock.hassette.children.append(dummy_service)

    event = ServiceStatusPayload.create_event(
        resource_name=dummy_service.class_name,
        role=dummy_service.role,
        status=ResourceStatus.FAILED,
        exc=Exception("test"),
    )

    await get_service_watcher_mock.restart_service(event)
    await asyncio.sleep(0.1)  # allow restart to run

    assert call_counts == {"cancel": 1, "start": 1}, (
        f"Expected cancel and start to be called once each, got {call_counts}"
    )
