import asyncio

import pytest

from hassette.core.classes import Service
from hassette.core.core import Hassette
from hassette.core.enums import ResourceStatus
from hassette.core.events import create_service_status_event


class _HoldService(Service):
    """Waits forever until shutdown is called."""

    async def run_forever(self):
        # park forever until cancelled by shutdown()
        self._evt = asyncio.Event()
        await self._evt.wait()

    async def shutdown(self, *a, **k):
        # wake run_forever() and finish
        if hasattr(self, "_evt"):
            self._evt.set()
        await super().shutdown(*a, **k)


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


async def test_service_start_twice_and_shutdown(mock_hassette_with_bus):
    svc = _HoldService(mock_hassette_with_bus)
    svc.start()
    await asyncio.sleep(0.1)  # allow start to run

    assert svc.is_running()

    with pytest.raises(RuntimeError):
        svc.start()

    await svc.shutdown()
    await asyncio.sleep(0.1)  # allow shutdown to run

    assert not svc.is_running()


async def test_restart_service_cancels_then_starts(hassette_core_no_ha: Hassette):
    called = {"cancel": 0, "start": 0}

    svc = get_dummy_service(called, hassette_core_no_ha)
    hassette_core_no_ha._resources[svc.class_name] = svc

    event = create_service_status_event(
        resource_name=svc.class_name,
        role=svc.role,
        status=ResourceStatus.FAILED,
        exc=Exception("test"),
    )

    await hassette_core_no_ha.restart_service(event)
    await asyncio.sleep(0.1)  # allow restart to run

    assert called == {"cancel": 1, "start": 1}
