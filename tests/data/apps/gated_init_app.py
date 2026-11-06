"""Test app whose startup waits on a module-level gate, so a test can act while it is mid-startup.

The events are process-wide: call ``reset()`` before starting the app, or a gate left set by an earlier test
lets ``on_initialize`` through at once.
"""

import asyncio

from hassette import App, AppConfig

ENTERED = asyncio.Event()
"""Set by ``on_initialize`` just before it waits on ``GATE``."""

GATE = asyncio.Event()
"""Set by the test to let ``on_initialize`` finish."""


def reset() -> None:
    """Clear both events, so the next ``on_initialize`` blocks again."""
    ENTERED.clear()
    GATE.clear()


class GatedInitApp(App[AppConfig]):
    """App that stays in ``on_initialize`` until ``GATE`` is set."""

    async def on_initialize(self) -> None:
        ENTERED.set()
        await GATE.wait()
