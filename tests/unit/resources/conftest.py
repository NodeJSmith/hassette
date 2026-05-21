"""Shared fixtures for unit/resources tests."""

from hassette.resources.base import Resource


class ConcreteResource(Resource):
    """Minimal concrete Resource subclass for testing."""

    async def on_initialize(self) -> None:
        pass
