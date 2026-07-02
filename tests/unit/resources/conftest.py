"""Shared fixtures for unit/resources tests."""

from unittest.mock import Mock

from hassette.resources.base import Resource
from hassette.test_utils.mock_hassette import make_mock_hassette


class ConcreteResource(Resource):
    """Minimal concrete Resource subclass for testing."""

    async def on_initialize(self) -> None:
        pass


def build_hassette(**overrides):
    """make_mock_hassette() with _should_skip_dependency_check pinned to a sync Mock.

    _should_skip_dependency_check is a sync method on real Hassette, but make_mock_hassette's
    AsyncMock leaves it as an unconfigured AsyncMock attribute — calling it without awaiting
    returns a truthy coroutine, which short-circuits _auto_wait_dependencies() before it
    reaches the branches under test.
    """
    hassette = make_mock_hassette(sealed=False, **overrides)
    hassette._should_skip_dependency_check = Mock(return_value=False)
    return hassette
