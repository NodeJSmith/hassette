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
import contextlib
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from hassette.exceptions import FatalError, RestartRefusedError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import start
from hassette.resources.operations import restart
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.resources.teardown import TeardownCause
from hassette.test_utils import make_mock_hassette, wait_for
from hassette.test_utils.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from hassette.types.enums import ResourceStatus
from tests.unit.resources.lifecycle.conftest import SimpleService

from .conftest import build_hassette, wait_for_running


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


class ResistantService(Service):
    """Service whose serve() swallows CancelledError and stays pending indefinitely.

    Simulates a cancellation-resistant ``serve()`` task (design Edge Cases: "serve() catches
    cancellation and remains pending"). ``release()`` lets a test unblock the task afterward so
    it never leaks past the end of the test — call it, then cancel and await the raw task.
    """

    restart_spec = RestartSpec()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._release = asyncio.Event()

    async def serve(self) -> None:
        while not self._release.is_set():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.Event().wait()

    def release(self) -> None:
        self._release.set()


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
        await wait_for_running(svc)

        calls: list[str] = []

        async def _spy_on_shutdown() -> None:
            calls.append("called")

        svc.on_shutdown = _spy_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await svc.shutdown()
        await svc.shutdown()  # second call — must be a no-op

        assert calls == ["called"], f"on_shutdown must run exactly once, ran {len(calls)} times"

    async def test_concurrent_shutdown_joins_in_flight_attempt(self) -> None:
        """A second shutdown() call while one is already in flight joins that same attempt
        instead of running hooks a second time.

        Superseded by the coordinator design: shutdown() is no longer a same-instance
        no-op while shutting down — every concurrent caller shields and awaits the one
        resource-owned ``_shutdown_task`` attempt, and both receive the same stored report.
        """
        hassette = make_mock_hassette(sealed=False)
        svc = SimpleService(hassette)
        await svc.initialize()
        await wait_for_running(svc)

        calls: list[str] = []
        entered = asyncio.Event()
        release = asyncio.Event()

        async def _gated_before_shutdown() -> None:
            calls.append("called")
            entered.set()
            await release.wait()

        svc.before_shutdown = _gated_before_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        first = asyncio.create_task(svc.shutdown())
        await asyncio.wait_for(entered.wait(), timeout=1)

        second = asyncio.create_task(svc.shutdown())

        release.set()
        report1 = await first
        report2 = await second

        assert calls == ["called"], "before_shutdown must run exactly once — both calls share one attempt"
        assert report1 == report2


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
        await wait_for_running(svc)
        assert svc.is_running() is True, "serve task spawned and not done"

        await svc.shutdown()
        assert svc.is_running() is False, "serve task cancelled and completed"


class TestServiceShutdownBodyServeTaskPending:
    """``Service._shutdown_body()`` observes a cancellation-resistant ``serve()`` task with a
    bounded ``asyncio.wait()`` rather than treating ``cancel()`` as termination proof. Called
    directly (bypassing the shutdown coordinator's own whole-body deadline, which shares the
    same config value and would otherwise race this inner bound and obscure which stage
    produced the evidence — see ``test_add_child_and_restart.py``'s ``_make_unsafe_parent`` for
    the same race explained for children).
    """

    async def test_resistant_serve_task_adds_serve_task_pending_within_budget(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
        # The resistant serve() task is TaskBucket-owned too, so the post-hook shutdown stage's
        # own TaskBucket.cancel_all() bounds its wait by task_cancellation_timeout_seconds, not
        # resource_shutdown_timeout_seconds. Keep both short so the outer asyncio.wait_for below
        # proves the whole body stays within a bounded budget rather than racing the 5s default.
        hassette.config.lifecycle.task_cancellation_timeout_seconds = 0.1

        svc = ResistantService(hassette)
        await svc.initialize()
        await wait_for_running(svc)

        old_task = svc._serve_task
        assert old_task is not None

        try:
            # Generous headroom over the 0.1s config bounds above (see CLAUDE.md's guidance on
            # config-driven real-clock timeouts) — this proves boundedness, not tightness.
            report = await asyncio.wait_for(svc._shutdown_body(), timeout=5)

            assert report.is_restart_safe is False
            assert TeardownCause.SERVE_TASK_PENDING in report.causes
            assert old_task.get_name() in report.pending_tasks
            assert not old_task.done(), "resistant task must remain pending, not be treated as terminated"
        finally:
            svc.release()
            old_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await old_task


class TestServiceResistantServeNeverReplaced:
    """A restart-unsafe report from a resistant ``serve()`` task must refuse every same-instance
    initialization path and never spawn a replacement ``serve()`` task.
    """

    async def test_shutdown_refuses_restart_and_never_spawns_replacement(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
        hassette.config.lifecycle.task_cancellation_timeout_seconds = 0.1

        svc = ResistantService(hassette)
        await svc.initialize()
        await wait_for_running(svc)

        old_task = svc._serve_task
        assert old_task is not None

        try:
            report = await asyncio.wait_for(svc.shutdown(), timeout=5)
            assert report.is_restart_safe is False
            assert svc.teardown_report is report

            with pytest.raises(RestartRefusedError):
                await restart(svc)

            with pytest.raises(RestartRefusedError):
                start(svc)

            with pytest.raises(RestartRefusedError):
                await svc.initialize()

            assert svc._serve_task is old_task, "no replacement serve() task may ever be created after refusal"
        finally:
            svc.release()
            old_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await old_task
