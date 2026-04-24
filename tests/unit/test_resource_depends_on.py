"""Unit tests for Resource.depends_on and _auto_wait_dependencies()."""

import asyncio
import threading
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.resources.base import Resource, Service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hassette_mock(
    *,
    children: list[Resource] | None = None,
    wait_for_ready_return: bool = True,
    shutdown_set: bool = False,
    skip_dependency_check: bool = False,
) -> AsyncMock:
    """Build a minimal hassette stub with configurable behaviour."""
    hassette = AsyncMock()
    hassette.config.log_level = "DEBUG"
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.resource_shutdown_timeout_seconds = 1
    hassette.config.task_cancellation_timeout_seconds = 1
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.dev_mode = False
    hassette.event_streams_closed = False
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_running_loop()
    hassette._scheduler_service.register_removal_callback = Mock()
    hassette._scheduler_service.deregister_removal_callback = Mock()

    # Children list — used by _auto_wait_dependencies
    hassette.children = children or []

    # wait_for_ready return value
    hassette.wait_for_ready = AsyncMock(return_value=wait_for_ready_return)

    # shutdown_event
    hassette.shutdown_event = asyncio.Event()
    if shutdown_set:
        hassette.shutdown_event.set()

    # harness bypass flag
    hassette._should_skip_dependency_check = Mock(return_value=skip_dependency_check)

    return hassette


class _SimpleDepA(Resource):
    """Dependency type A for testing."""

    async def on_initialize(self) -> None:
        pass


class _SimpleDepB(Resource):
    """Dependency type B for testing."""

    async def on_initialize(self) -> None:
        pass


class _SubclassOfA(_SimpleDepA):
    """Subclass of A for subclass-match test."""

    async def on_initialize(self) -> None:
        pass


class _ResourceWithDepA(Resource):
    depends_on: ClassVar[list[type[Resource]]] = [_SimpleDepA]

    async def on_initialize(self) -> None:
        pass


class _ResourceWithDepAB(Resource):
    depends_on: ClassVar[list[type[Resource]]] = [_SimpleDepA, _SimpleDepB]

    async def on_initialize(self) -> None:
        pass


class _ResourceWithNoDeps(Resource):
    async def on_initialize(self) -> None:
        pass


class _ServiceWithDepA(Service):
    depends_on: ClassVar[list[type[Resource]]] = [_SimpleDepA]

    async def serve(self) -> None:
        pass

    async def on_initialize(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Test 1: empty depends_on is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_depends_on_is_noop() -> None:
    """Resource with no depends_on completes _auto_wait_dependencies without calling wait_for_ready."""
    hassette = _make_hassette_mock()
    resource = _ResourceWithNoDeps(hassette=hassette)

    await resource._auto_wait_dependencies()

    hassette.wait_for_ready.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: depends_on waits for matching instance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_waits_for_matching_instance() -> None:
    """When depends_on has a type and a matching child exists, wait_for_ready is called with it."""
    hassette = _make_hassette_mock()
    dep_a = _SimpleDepA(hassette=hassette)
    hassette.children = [dep_a]

    resource = _ResourceWithDepA(hassette=hassette)
    await resource._auto_wait_dependencies()

    hassette.wait_for_ready.assert_called_once_with([dep_a])


# ---------------------------------------------------------------------------
# Test 3: missing type raises RuntimeError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_missing_type_raises() -> None:
    """RuntimeError raised with actionable message when no matching child exists."""
    hassette = _make_hassette_mock(children=[])

    resource = _ResourceWithDepA(hassette=hassette)

    with pytest.raises(RuntimeError, match="_ResourceWithDepA") as exc_info:
        await resource._auto_wait_dependencies()

    assert "_SimpleDepA" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 4: subclass match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_subclass_match() -> None:
    """depends_on=[BaseType] finds a ConcreteSubclass instance in children."""
    hassette = _make_hassette_mock()
    sub = _SubclassOfA(hassette=hassette)
    hassette.children = [sub]

    resource = _ResourceWithDepA(hassette=hassette)
    await resource._auto_wait_dependencies()

    hassette.wait_for_ready.assert_called_once_with([sub])


# ---------------------------------------------------------------------------
# Test 5: multiple dep types — all matching instances waited on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_multiple_matches() -> None:
    """All matching instances for all declared dep types are waited on together."""
    hassette = _make_hassette_mock()
    dep_a = _SimpleDepA(hassette=hassette)
    dep_b = _SimpleDepB(hassette=hassette)
    hassette.children = [dep_a, dep_b]

    resource = _ResourceWithDepAB(hassette=hassette)
    await resource._auto_wait_dependencies()

    hassette.wait_for_ready.assert_called_once_with([dep_a, dep_b])


# ---------------------------------------------------------------------------
# Test 6: timeout raises RuntimeError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_timeout_raises() -> None:
    """RuntimeError raised naming timed-out deps when wait_for_ready returns False and shutdown not set."""
    hassette = _make_hassette_mock(wait_for_ready_return=False, shutdown_set=False)
    dep_a = _SimpleDepA(hassette=hassette)
    hassette.children = [dep_a]

    resource = _ResourceWithDepA(hassette=hassette)

    with pytest.raises(RuntimeError, match="timed out"):
        await resource._auto_wait_dependencies()


# ---------------------------------------------------------------------------
# Test 7: shutdown during wait marks not_ready and returns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_shutdown_marks_not_ready() -> None:
    """When wait_for_ready returns False and shutdown is set, mark_not_ready is called and method returns."""
    hassette = _make_hassette_mock(wait_for_ready_return=False, shutdown_set=True)
    dep_a = _SimpleDepA(hassette=hassette)
    hassette.children = [dep_a]

    resource = _ResourceWithDepA(hassette=hassette)

    # Should NOT raise — shutdown path returns gracefully
    await resource._auto_wait_dependencies()

    assert not resource.is_ready()


# ---------------------------------------------------------------------------
# Test 8: handle_failed called before RuntimeError propagates from initialize()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depends_on_timeout_calls_handle_failed() -> None:
    """handle_failed is called before RuntimeError from _auto_wait_dependencies propagates."""
    hassette = _make_hassette_mock(wait_for_ready_return=False, shutdown_set=False)
    dep_a = _SimpleDepA(hassette=hassette)
    hassette.children = [dep_a]

    resource = _ResourceWithDepA(hassette=hassette)

    handle_failed_calls: list[Exception] = []

    original_handle_failed = resource.handle_failed

    async def _record_handle_failed(exc: Exception) -> None:
        handle_failed_calls.append(exc)
        await original_handle_failed(exc)

    resource.handle_failed = _record_handle_failed  # pyright: ignore[reportAttributeAccessIssue]

    with pytest.raises(RuntimeError, match="timed out"):
        await resource.initialize()

    assert len(handle_failed_calls) == 1


# ---------------------------------------------------------------------------
# Test 9: _should_skip_dependency_check bypasses all logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_dependency_check_bypasses() -> None:
    """When hassette._should_skip_dependency_check() returns True, _auto_wait_dependencies returns immediately."""
    hassette = _make_hassette_mock(
        children=[],  # no children — would raise if not skipped
        skip_dependency_check=True,
    )

    resource = _ResourceWithDepA(hassette=hassette)
    # Should not raise even though no matching child exists
    await resource._auto_wait_dependencies()

    hassette.wait_for_ready.assert_not_called()


# ---------------------------------------------------------------------------
# Test 10: Service.initialize() also runs _auto_wait_dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_auto_wait_dependencies() -> None:
    """Service.initialize() calls _auto_wait_dependencies with the same semantics as Resource."""
    hassette = _make_hassette_mock()
    dep_a = _SimpleDepA(hassette=hassette)
    hassette.children = [dep_a]

    service = _ServiceWithDepA(hassette=hassette)
    await service._auto_wait_dependencies()

    hassette.wait_for_ready.assert_called_once_with([dep_a])
