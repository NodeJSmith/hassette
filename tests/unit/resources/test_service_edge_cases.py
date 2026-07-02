"""Tests for Service branches not exercised by the existing lifecycle test suite.

Verifies:
- Service._force_terminal() when no serve task was ever spawned (never initialized)
- Service.initialize() propagates a dependency-wait failure via handle_failed() and re-raises
- Service.initialize() returns gracefully when shutdown fires during the dependency wait
- Service.initialize() skips children that are already RUNNING/STARTING during propagation
- Service.shutdown() is idempotent (second call after completion is a no-op)
- Service.shutdown() is a no-op when a concurrent shutdown is already in progress
- Service.shutdown() skips the STOPPING transition when status is already terminal
- Service._serve_wrapper() routes a FatalError from serve() to handle_crash()
- Service.is_running() reflects serve-task lifecycle: False before start, True while
  running, False after shutdown
"""

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils import make_mock_hassette, wait_for
from hassette.types.enums import ResourceStatus

from .conftest import build_hassette


class SimpleService(Service):
    restart_spec = RestartSpec()

    async def serve(self) -> None:
        await asyncio.Event().wait()  # block forever until cancelled


class _DepType(Resource):
    async def on_initialize(self) -> None:
        pass


class ServiceWithDep(Service):
    restart_spec = RestartSpec()
    depends_on: ClassVar[list[type[Resource]]] = [_DepType]

    async def serve(self) -> None:
        await asyncio.Event().wait()


class InitCountingChild(Resource):
    init_count: int = 0

    async def on_initialize(self) -> None:
        self.init_count += 1


class FatalErrorService(Service):
    restart_spec = RestartSpec()

    async def serve(self) -> None:
        raise FatalError("fatal boom")


class TestForceTerminalWithoutServeTask:
    async def test_force_terminal_without_active_serve_task_calls_super_cleanly(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)
        assert svc._serve_task is None, "never initialized — no serve task exists yet"

        svc._force_terminal()  # must not raise despite no serve task to cancel

        assert svc.status == ResourceStatus.STOPPED
        assert svc.shutdown_completed is True


class TestServiceInitializeDependencyFailure:
    async def test_missing_dependency_calls_handle_failed_and_reraises(self) -> None:
        hassette = build_hassette()  # hassette.children defaults to []
        svc = ServiceWithDep(hassette)

        with pytest.raises(RuntimeError, match="_DepType"):
            await svc.initialize()

        assert svc.status == ResourceStatus.FAILED

    async def test_shutdown_during_dependency_wait_returns_gracefully(self) -> None:
        hassette = build_hassette()
        hassette.shutdown_event.set()
        dep = _DepType(hassette)
        hassette.children = [dep]
        hassette.wait_for_ready = AsyncMock(return_value=False)

        svc = ServiceWithDep(hassette)

        await svc.initialize()  # must NOT raise — shutdown-during-wait path returns gracefully

        assert not svc.is_ready()
        assert svc._serve_task is None, "serve task must never be spawned on this path"


class TestServiceInitializeChildPropagation:
    async def test_already_running_child_is_not_reinitialized(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)
        child = svc.add_child(InitCountingChild)

        await child.initialize()
        assert child.status == ResourceStatus.RUNNING
        assert child.init_count == 1

        await svc.initialize()
        await wait_for(
            lambda: svc.status == ResourceStatus.STARTING or svc._serve_task is not None,
            desc="service started",
        )

        assert child.init_count == 1, "already-RUNNING child must be skipped during propagation"

        await svc.shutdown()


class TestServiceShutdownIdempotency:
    async def test_second_shutdown_call_is_a_noop(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)
        await svc.initialize()
        await wait_for(lambda: svc.status == ResourceStatus.RUNNING, desc="service RUNNING")

        calls: list[str] = []

        async def _spy_on_shutdown() -> None:
            calls.append("called")

        svc.on_shutdown = _spy_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await svc.shutdown()
        await svc.shutdown()  # second call — must be a no-op

        assert calls == ["called"], f"on_shutdown must run exactly once, ran {len(calls)} times"

    async def test_noop_when_already_shutting_down(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)
        await svc.initialize()
        await wait_for(lambda: svc.status == ResourceStatus.RUNNING, desc="service RUNNING")

        svc.shutting_down = True  # simulate a concurrent shutdown already in progress

        calls: list[str] = []

        async def _spy_before_shutdown() -> None:
            calls.append("called")

        svc.before_shutdown = _spy_before_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await svc.shutdown()

        assert calls == [], "hooks must not run — shutdown() is a no-op while shutting_down is True"

        # Cleanup: reset the flag and shut down for real so the serve task doesn't leak.
        svc.shutting_down = False
        await svc.shutdown()


class TestServiceShutdownSkipsStoppingWhenTerminal:
    async def test_skips_stopping_transition_when_already_terminal(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)
        svc._status = ResourceStatus.STOPPED  # already terminal; never initialized, no serve task

        status_during_hook: list[ResourceStatus] = []

        async def _spy_before_shutdown() -> None:
            status_during_hook.append(svc.status)

        svc.before_shutdown = _spy_before_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await svc.shutdown()

        assert status_during_hook == [ResourceStatus.STOPPED]


class TestServeWrapperFatalError:
    async def test_fatal_error_routes_to_handle_crash(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = FatalErrorService(hassette, parent=hassette)

        await svc._serve_wrapper()

        assert svc.status == ResourceStatus.CRASHED


class TestIsRunning:
    async def test_is_running_reflects_serve_task_lifecycle(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)

        assert svc.is_running() is False, "never started — no serve task"

        await svc.initialize()
        await wait_for(lambda: svc.status == ResourceStatus.RUNNING, desc="service RUNNING")
        assert svc.is_running() is True, "serve task spawned and not done"

        await svc.shutdown()
        assert svc.is_running() is False, "serve task cancelled and completed"
