"""``build_harness`` — a Tier 1 async context manager, not a pytest fixture.

Split out from ``fixtures.py`` so importing this symbol (or any other Tier 1
symbol via ``hassette.testing``) doesn't require ``pytest`` to be installed.
Only ``dummy_cache`` and ``event_capture`` are actual ``@pytest.fixture``
functions and need the ``pytest`` import.
"""

import contextlib
from typing import TYPE_CHECKING

from hassette.testing._harness import HassetteHarness

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@contextlib.asynccontextmanager
async def build_harness(harness: HassetteHarness) -> "AsyncIterator[HassetteHarness]":
    """Start and stop a HassetteHarness, reloading config on exit.

    Safe to use directly inside a test body (see e.g. ``tests/integration/test_apps_env.py``)
    because ``__aexit__`` then runs inline in the test's own already-running Task rather than
    being resumed later by pytest-asyncio. It is NOT safe to drive a ``yield``-based *fixture*
    from this context manager -- see ``tests/support/harness.py`` and
    ``tests/integration/conftest.py::hassette_instance`` for why.
    """
    try:
        await harness.start()
        yield harness
    finally:
        await harness.stop()
        harness.config.reload()
