import pytest

from hassette.core.core import Hassette


async def test_run_sync_raises_inside_loop(hassette_with_bus: Hassette) -> None:
    """run_sync rejects being invoked inside the running event loop."""

    async def sample_coroutine():
        return 42

    with pytest.raises(RuntimeError):
        hassette_with_bus.task_bucket.run_sync(sample_coroutine())
