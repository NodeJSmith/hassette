"""Supplementary tests for Resource._auto_wait_dependencies().

Most branches of _auto_wait_dependencies() are covered by
tests/unit/test_resource_depends_on.py. This file closes the two branches that file
does not exercise:

- App-level depends_on raises RuntimeError (not yet supported, see issue #581)
- Dedup-by-instance-identity: a single child instance satisfying two declared dep types
  is only waited on once, not twice
"""

from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.resources.base import Resource
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceRole


def build_hassette(**overrides):
    """make_mock_hassette() plus the harness-bypass stub _auto_wait_dependencies() needs.

    _should_skip_dependency_check is a sync method on real Hassette, but make_mock_hassette's
    plain AsyncMock leaves it as an unconfigured AsyncMock attribute — calling it without
    awaiting returns a truthy coroutine, which short-circuits _auto_wait_dependencies() before
    it ever reaches the branches under test here. Pin it to a real sync Mock.
    """
    hassette = make_mock_hassette(sealed=False, **overrides)
    hassette._should_skip_dependency_check = Mock(return_value=False)
    return hassette


class _DepA(Resource):
    async def on_initialize(self) -> None:
        pass


class _DepB(Resource):
    async def on_initialize(self) -> None:
        pass


class _MultiDep(_DepA, _DepB):
    """A single concrete type that is-a both declared dependency types."""

    async def on_initialize(self) -> None:
        pass


class _AppLikeResource(Resource):
    """Resource with role=APP and a non-empty depends_on — the unsupported combination."""

    role: ClassVar[ResourceRole] = ResourceRole.APP
    depends_on: ClassVar[list[type[Resource]]] = [_DepA]

    async def on_initialize(self) -> None:
        pass


class _ResourceWithDepAB(Resource):
    depends_on: ClassVar[list[type[Resource]]] = [_DepA, _DepB]

    async def on_initialize(self) -> None:
        pass


async def test_app_role_with_depends_on_raises_runtime_error() -> None:
    """App-level depends_on is not yet supported — raises with an actionable message."""
    hassette = build_hassette()
    resource = _AppLikeResource(hassette=hassette)

    with pytest.raises(RuntimeError, match="App-level depends_on is not yet supported"):
        await resource._auto_wait_dependencies()


async def test_single_instance_satisfying_multiple_dep_types_is_deduped() -> None:
    """A dep instance matching two declared dep types is only passed to wait_for_ready once."""
    hassette = build_hassette()
    shared = _MultiDep(hassette=hassette)
    hassette.children = [shared]
    hassette.wait_for_ready = AsyncMock(return_value=True)

    resource = _ResourceWithDepAB(hassette=hassette)
    await resource._auto_wait_dependencies()

    # _DepA and _DepB both match `shared` (isinstance is true for both), but it must
    # appear exactly once in the list passed to wait_for_ready.
    hassette.wait_for_ready.assert_called_once_with([shared])
