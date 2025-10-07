import asyncio

import pytest

from hassette.core.resources import Service
from hassette.enums import ResourceStatus


class _HoldService(Service):
    """Waits forever until shutdown is called."""

    status = ResourceStatus.RUNNING

    async def run_forever(self):
        # park forever until cancelled by shutdown()
        self._evt = asyncio.Event()
        await self._evt.wait()

    async def shutdown(self, *a, **k):
        # wake run_forever() and finish
        if hasattr(self, "_evt"):
            self._evt.set()
        await super().shutdown(*a, **k)


async def test_service_start_twice_and_shutdown(hassette_with_bus):
    svc = _HoldService(hassette_with_bus)
    svc.start()
    await asyncio.sleep(0.1)  # allow start to run

    assert svc.is_running(), "Expected service to be running after start()"

    with pytest.raises(RuntimeError):
        svc.start()

    await svc.shutdown()
    await asyncio.sleep(0.1)  # allow shutdown to run

    assert not svc.is_running(), "Expected service to not be running after shutdown()"
