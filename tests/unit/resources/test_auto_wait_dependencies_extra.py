"""Supplementary tests for Resource._auto_wait_dependencies().

Most branches of _auto_wait_dependencies() are covered by
tests/unit/test_resource_depends_on.py. This file closes the two branches that file
does not exercise:

- App-level depends_on raises RuntimeError (not yet supported, see issue #581)
- Dedup-by-instance-identity: a single child instance satisfying two declared dep types
  is only waited on once, not twice
"""

from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from hassette.resources.base import Resource
from hassette.types.enums import ResourceRole

from .conftest import build_hassette


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
