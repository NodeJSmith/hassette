import asyncio

import pytest

from hassette.core.classes import Service
from hassette.core.enums import ResourceStatus
from hassette.core.events import ServiceStatusPayload
from hassette.core.service_watcher import _ServiceWatcher


@pytest.fixture
def get_service_watcher_mock(hassette_with_bus):
    return _ServiceWatcher(hassette_with_bus)


def get_dummy_service(called: dict[str, int], hassette) -> Service:
    class _Dummy(Service):
        """Does nothing, just tracks calls."""

        async def run_forever(self):
            pass

        def cancel(self):
            called["cancel"] += 1

        def start(self):
            called["start"] += 1

    return _Dummy(hassette)


async def test_restart_service_cancels_then_starts(get_service_watcher_mock: _ServiceWatcher):
    called = {"cancel": 0, "start": 0}

    get_service_watcher_mock.hassette._resources["_Dummy"] = svc = get_dummy_service(
        called, get_service_watcher_mock.hassette
    )

    event = ServiceStatusPayload.create_event(
        resource_name=svc.class_name,
        role=svc.role,
        status=ResourceStatus.FAILED,
        exc=Exception("test"),
    )

    await get_service_watcher_mock.restart_service(event)
    await asyncio.sleep(0.1)  # allow restart to run

    assert called == {"cancel": 1, "start": 1}, f"Expected cancel and start to be called once each, got {called}"
