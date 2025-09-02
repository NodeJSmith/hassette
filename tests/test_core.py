import pytest

from hassette.core.core import Hassette


@pytest.mark.requires_ha
async def test_run_sync_raises_inside_loop(hassette_core: Hassette) -> None:
    async def coro():
        return 42

    with pytest.raises(RuntimeError):
        hassette_core.run_sync(coro())
