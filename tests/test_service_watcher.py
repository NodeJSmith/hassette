import asyncio

import pytest

from hassette.core.resources.base import Service
from hassette.core.services.service_watcher import _ServiceWatcher
from hassette.enums import ResourceStatus
from hassette.events import ServiceStatusPayload


@pytest.fixture
def get_service_watcher_mock(hassette_with_bus):
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
    called = {"cancel": 0, "start": 0}

    svc = get_dummy_service(called, get_service_watcher_mock.hassette)
    get_service_watcher_mock.hassette.children.add(svc)

    event = ServiceStatusPayload.create_event(
        resource_name=svc.class_name,
        role=svc.role,
        status=ResourceStatus.FAILED,
        exc=Exception("test"),
    )

    await get_service_watcher_mock.restart_service(event)
    await asyncio.sleep(0.1)  # allow restart to run

    assert called == {"cancel": 1, "start": 1}, f"Expected cancel and start to be called once each, got {called}"
