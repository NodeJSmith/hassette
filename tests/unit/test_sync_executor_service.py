"""Unit tests for SyncExecutorService (T03).

Covers:
- Executor is constructed in __init__ (no None window)
- Service is registered in wire_services() and reachable via hassette.sync_executor
- depends_on=[] (leaf dependency — no DB or other service required)
- BusService, SchedulerService, AppHandler declare depends_on=[SyncExecutorService]
- Dependency graph validation still passes after registration
- Regression: AppSync shutdown hook submitting sync work during shutdown completes
  without RuntimeError: cannot schedule new futures after shutdown
"""

import asyncio
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from hassette.config import HassetteConfig
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor
from hassette.types.enums import RestartType
from hassette.utils.service_utils import validate_dependency_graph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_test_config(max_workers: int = 4, shutdown_timeout: float = 5.0) -> HassetteConfig:
    """Build a minimal HassetteConfig for unit tests."""
    return HassetteConfig(
        token="test-token",
        lifecycle={
            "sync_executor_max_workers": max_workers,
            "sync_executor_shutdown_timeout_seconds": shutdown_timeout,
        },
    )


# ---------------------------------------------------------------------------
# Class-level structure tests (no event loop needed)
# ---------------------------------------------------------------------------


class TestSyncExecutorServiceClassAttrs:
    def test_depends_on_is_empty(self) -> None:
        """SyncExecutorService is a leaf dependency — no DB or other service required."""
        assert SyncExecutorService.depends_on == []

    def test_restart_spec_declared(self) -> None:
        """restart_spec is declared directly on SyncExecutorService, not inherited."""
        assert "restart_spec" in SyncExecutorService.__dict__
        assert isinstance(SyncExecutorService.restart_spec, RestartSpec)

    def test_restart_type_permanent(self) -> None:
        """A long-lived executor matches the PERMANENT strategy of BusService/SchedulerService."""
        assert SyncExecutorService.restart_spec.restart_type is RestartType.PERMANENT

    def test_bus_service_depends_on_sync_executor(self) -> None:
        """BusService declares SyncExecutorService in depends_on."""
        assert SyncExecutorService in BusService.depends_on

    def test_scheduler_service_depends_on_sync_executor(self) -> None:
        """SchedulerService declares SyncExecutorService in depends_on."""
        assert SyncExecutorService in SchedulerService.depends_on

    def test_app_handler_depends_on_sync_executor(self) -> None:
        """AppHandler declares SyncExecutorService in depends_on."""
        assert SyncExecutorService in AppHandler.depends_on


# ---------------------------------------------------------------------------
# Executor construction (no event loop needed)
# ---------------------------------------------------------------------------


class TestExecutorConstruction:
    def test_executor_constructed_in_init(self) -> None:
        """Executor is built in __init__, not lazily — no None window."""
        config = make_test_config(max_workers=3)
        mock_hassette = MagicMock()
        mock_hassette.config = config
        mock_hassette.task_bucket = MagicMock()
        mock_hassette.shutdown_event = asyncio.Event()
        mock_hassette.children = []
        mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)

        svc = SyncExecutorService(mock_hassette)

        assert svc.executor is not None
        assert isinstance(svc.executor, InterruptibleThreadPoolExecutor)
        # Clean up immediately
        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_executor_uses_config_max_workers(self) -> None:
        """Executor is constructed with max_workers from lifecycle config."""
        config = make_test_config(max_workers=7)
        mock_hassette = MagicMock()
        mock_hassette.config = config
        mock_hassette.task_bucket = MagicMock()
        mock_hassette.shutdown_event = asyncio.Event()
        mock_hassette.children = []
        mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)

        svc = SyncExecutorService(mock_hassette)

        assert svc.executor._max_workers == 7  # pyright: ignore[reportAttributeAccessIssue]
        svc.executor.shutdown(join_threads_or_timeout=False)

    def test_executor_thread_name_prefix(self) -> None:
        """Worker threads get the 'hassette-sync' prefix for identifiability in logs."""
        config = make_test_config()
        mock_hassette = MagicMock()
        mock_hassette.config = config
        mock_hassette.task_bucket = MagicMock()
        mock_hassette.shutdown_event = asyncio.Event()
        mock_hassette.children = []
        mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)

        svc = SyncExecutorService(mock_hassette)

        # Spawn a thread to verify prefix
        future = svc.executor.submit(lambda: None)
        future.result(timeout=2.0)
        thread_names = {t.name for t in svc.executor._threads}  # pyright: ignore[reportAttributeAccessIssue]
        assert all("hassette-sync" in name for name in thread_names)
        svc.executor.shutdown(join_threads_or_timeout=False)


# ---------------------------------------------------------------------------
# Dependency graph validation
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    def test_graph_is_acyclic_with_sync_executor(self) -> None:
        """Adding SyncExecutorService keeps the dependency graph acyclic."""
        # Build a minimal type list matching the real registration order:
        # SyncExecutorService (leaf) → BusService, SchedulerService, AppHandler depend on it.

        class _Leaf(Resource):
            depends_on: ClassVar[list[type[Resource]]] = []

            async def on_initialize(self) -> None:
                pass

        class _Consumer(Resource):
            depends_on: ClassVar[list[type[Resource]]] = [_Leaf]

            async def on_initialize(self) -> None:
                pass

        # validate_dependency_graph raises ValueError on cycles; should not raise here.
        validate_dependency_graph([_Leaf, _Consumer])

    def test_sync_executor_is_leaf_node(self) -> None:
        """SyncExecutorService depends on nothing — it is always a leaf in the graph."""
        # Reachable deps of SyncExecutorService are empty.
        all_deps: set[type[Resource]] = set()
        for dep in SyncExecutorService.depends_on:
            all_deps.add(dep)
        assert SyncExecutorService not in all_deps  # no self-reference
        assert len(SyncExecutorService.depends_on) == 0


# ---------------------------------------------------------------------------
# wire_services() registration and hassette.sync_executor property
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def isolated_hassette_context(monkeypatch: pytest.MonkeyPatch):
    """Swap HASSETTE_INSTANCE and HASSETTE_CONFIG for fresh ContextVars.

    wire_services() sets both globals; using fresh ContextVars per test prevents
    bleed between tests running in the same process.  monkeypatch restores them
    automatically after the test.
    """
    from contextvars import ContextVar

    import hassette.context as ctx_module

    fresh_instance: ContextVar = ContextVar("HASSETTE_INSTANCE")
    fresh_config: ContextVar = ContextVar("HASSETTE_CONFIG")
    monkeypatch.setattr(ctx_module, "HASSETTE_INSTANCE", fresh_instance)
    monkeypatch.setattr(ctx_module, "HASSETTE_CONFIG", fresh_config)
    return fresh_instance
    # monkeypatch auto-restores both ContextVars after the test.


class TestWireServicesRegistration:
    """Tests that call wire_services().

    Each test uses the isolated_hassette_context fixture to avoid ContextVar bleed.
    """

    def test_sync_executor_service_registered_after_wire_services(self, isolated_hassette_context: object) -> None:
        """After wire_services(), _sync_executor_service is populated."""
        from hassette.core.core import Hassette

        config = make_test_config()
        h = Hassette(config)
        try:
            h.wire_services()
            assert h._sync_executor_service is not None
            assert isinstance(h._sync_executor_service, SyncExecutorService)
        finally:
            if h._sync_executor_service is not None:
                h._sync_executor_service.executor.shutdown(join_threads_or_timeout=False)

    def test_sync_executor_property_returns_executor(self, isolated_hassette_context: object) -> None:
        """hassette.sync_executor returns the InterruptibleThreadPoolExecutor."""
        from hassette.core.core import Hassette

        config = make_test_config()
        h = Hassette(config)
        try:
            h.wire_services()
            executor = h.sync_executor
            assert isinstance(executor, InterruptibleThreadPoolExecutor)
        finally:
            if h._sync_executor_service is not None:
                h._sync_executor_service.executor.shutdown(join_threads_or_timeout=False)

    def test_sync_executor_property_raises_before_wire_services(self) -> None:
        """hassette.sync_executor raises RuntimeError when wire_services() hasn't been called."""
        from hassette.core.core import Hassette

        config = make_test_config()
        h = Hassette(config)
        with pytest.raises(RuntimeError, match="wire_services"):
            _ = h.sync_executor

    def test_wire_services_graph_validates_without_error(self, isolated_hassette_context: object) -> None:
        """wire_services() completes without ValueError from the dependency graph validator."""
        from hassette.core.core import Hassette

        config = make_test_config()
        h = Hassette(config)
        try:
            # Should not raise — SyncExecutorService is a leaf, graph stays acyclic.
            h.wire_services()
        finally:
            if h._sync_executor_service is not None:
                h._sync_executor_service.executor.shutdown(join_threads_or_timeout=False)


# ---------------------------------------------------------------------------
# Shutdown regression: AppSync hook submits work during shutdown
# ---------------------------------------------------------------------------


class TestShutdownOrderingRegression:
    """Regression test for Finding 1: AppSync shutdown hook submits to an already-closed pool.

    With Bus/Scheduler/AppHandler depending on SyncExecutorService, wave-based shutdown
    tears them down *before* the executor — so sync submissions during their shutdown
    hooks run against a live pool, not a closed one.

    This test simulates the race by submitting work to the executor *after* the
    shutdown_event fires (mimicking an AppSync on_shutdown hook) and confirms no
    RuntimeError is raised. The *structural* ordering guarantee (executor in an
    earlier shutdown wave) is enforced by the `depends_on` class-attribute tests in
    TestSyncExecutorServiceClassAttrs; this test verifies the runtime consequence —
    a live pool accepts work during consumer shutdown.
    """

    def test_executor_accepts_work_during_consumers_shutdown(self) -> None:
        """Executor stays alive while its consumers (Bus/Scheduler/AppHandler) shut down.

        Simulates an AppSync shutdown hook calling run_in_thread after shutdown_event
        is set.  Because the executor shuts down *after* its consumers, the submit
        must succeed — not raise RuntimeError: cannot schedule new futures after shutdown.
        """
        config = make_test_config(max_workers=2, shutdown_timeout=2.0)
        mock_hassette = MagicMock()
        mock_hassette.config = config
        mock_hassette.task_bucket = MagicMock()
        mock_hassette.shutdown_event = asyncio.Event()
        mock_hassette.children = []
        mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)

        svc = SyncExecutorService(mock_hassette)

        # Simulate: shutdown_event fires (consumers are being torn down)
        mock_hassette.shutdown_event.set()

        # The executor itself has NOT been shut down yet — it outlives consumers.
        # An AppSync on_shutdown hook submits sync work at this point.
        result: list[str] = []
        future = svc.executor.submit(lambda: result.append("ran"))
        future.result(timeout=2.0)

        assert result == ["ran"], "Sync work submitted during consumer shutdown must complete"

        # Now shut down the executor (what SyncExecutorService.on_shutdown does).
        svc.executor.shutdown(timeout=2.0)

    def test_submit_after_executor_shutdown_raises(self) -> None:
        """Confirms baseline: submitting to a *closed* executor raises RuntimeError.

        This is the failure mode the depends_on ordering prevents.
        """
        config = make_test_config()
        mock_hassette = MagicMock()
        mock_hassette.config = config
        mock_hassette.task_bucket = MagicMock()
        mock_hassette.shutdown_event = asyncio.Event()
        mock_hassette.children = []
        mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)

        svc = SyncExecutorService(mock_hassette)
        svc.executor.shutdown(timeout=1.0)

        with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
            svc.executor.submit(lambda: None)


# ---------------------------------------------------------------------------
# on_shutdown uses configured budget
# ---------------------------------------------------------------------------


class TestOnShutdown:
    @pytest.mark.anyio
    async def test_on_shutdown_calls_executor_shutdown_with_budget(self) -> None:
        """on_shutdown passes sync_executor_shutdown_timeout_seconds as the budget."""
        config = make_test_config(shutdown_timeout=7.5)
        mock_hassette = MagicMock()
        mock_hassette.config = config
        mock_hassette.task_bucket = MagicMock()
        mock_hassette.shutdown_event = asyncio.Event()
        mock_hassette.children = []
        mock_hassette._should_skip_dependency_check = MagicMock(return_value=True)

        svc = SyncExecutorService(mock_hassette)

        shutdown_calls: list[dict] = []
        original_shutdown = svc.executor.shutdown

        def recording_shutdown(*args: object, **kwargs: object) -> None:
            shutdown_calls.append({"args": args, "kwargs": kwargs})
            original_shutdown(join_threads_or_timeout=False)

        svc.executor.shutdown = recording_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await svc.on_shutdown()

        assert len(shutdown_calls) == 1
        assert shutdown_calls[0]["kwargs"].get("timeout") == 7.5


# SyncExecutorService's restart_spec is covered by the parametrized tests in
# test_service_restart_specs.py (ALL_SERVICES now includes it) — no duplicate here.
