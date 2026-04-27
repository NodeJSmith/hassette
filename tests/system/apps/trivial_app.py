"""Trivial app fixture for system tests."""

from hassette import App


class TrivialApp(App):
    """Minimal app with a no-op on_initialize — used to verify app lifecycle."""

    async def on_initialize(self) -> None:
        pass
