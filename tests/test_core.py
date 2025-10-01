import pytest

from hassette.core.core import Hassette


async def test_run_sync_raises_inside_loop(hassette_with_bus: Hassette) -> None:
    async def coro():
        return 42

    with pytest.raises(RuntimeError):
        hassette_with_bus.run_sync(coro())
