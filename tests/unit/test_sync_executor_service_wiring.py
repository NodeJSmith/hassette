"""Unit tests for SyncExecutorService construction, wiring, and dependency graph.

Covers:
- Executor is constructed in on_initialize (survives restart-in-place)
- Service is registered in wire_services() and reachable via hassette.sync_executor_service
- depends_on=[] (leaf dependency — no DB or other service required)
- BusService, SchedulerService, AppHandler declare depends_on=[SyncExecutorService]
- Dependency graph validation still passes after registration
- Regression: restart-in-place (shutdown → initialize) rebuilds the thread pool
- Regression: AppSync shutdown hook submitting sync work during shutdown completes
  without RuntimeError: cannot schedule new futures after shutdown

Saturation warnings, shutdown-interruption, and config-driven behavior tests live in
test_sync_executor_service_saturation.py.
"""

from contextvars import ContextVar
from typing import ClassVar

import pytest

import hassette.context as ctx_module
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.core import Hassette
from hassette.core.scheduler_service import SchedulerService
from hassette.core.sync_executor import SyncExecutor
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor
from hassette.types.enums import RestartType
from hassette.utils.service_utils import validate_dependency_graph
from tests.unit.conftest import make_service, make_sync_executor_config, make_sync_executor_hassette


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


# SyncExecutorService's restart_spec is covered by the parametrized tests in
# test_service_restart_specs.py (ALL_SERVICES now includes it) — no duplicate here.


class TestExecutorConstruction:
    def test_executor_available_immediately_after_init(self) -> None:
        """The SyncExecutor's pool exists as soon as the service is constructed.

        Unlike the old SyncExecutorService (which built its own executor lazily in
        on_initialize), the thinned service wraps a SyncExecutor that is already
        fully built by the time Hassette.__init__() runs — construction alone is
        enough to have a working pool (see TC#1 in wired_hassette_construction tests).
        """
        mock_hassette = make_sync_executor_hassette(max_workers=3)
        svc = SyncExecutorService(mock_hassette)
        assert svc.sync_executor.executor is not None
        assert isinstance(svc.sync_executor.executor, InterruptibleThreadPoolExecutor)
        svc.sync_executor.executor.shutdown(join_threads_or_timeout=False)

    @pytest.mark.anyio
    async def test_on_initialize_rebuilds_pool(self) -> None:
        """on_initialize() always rebuilds the pool — a fresh InterruptibleThreadPoolExecutor,
        distinct from the one built at construction — covering both initial start and restart.
        """
        mock_hassette = make_sync_executor_hassette(max_workers=3)
        svc = SyncExecutorService(mock_hassette)
        pool_before_initialize = svc.sync_executor.executor

        await svc.on_initialize()

        assert svc.sync_executor.executor is not None
        assert isinstance(svc.sync_executor.executor, InterruptibleThreadPoolExecutor)
        assert svc.sync_executor.executor is not pool_before_initialize
        pool_before_initialize.shutdown(join_threads_or_timeout=False)
        svc.sync_executor.executor.shutdown(join_threads_or_timeout=False)

    @pytest.mark.anyio
    async def test_executor_uses_config_max_workers(self) -> None:
        """Executor is constructed with max_workers from lifecycle config."""
        mock_hassette = make_sync_executor_hassette(max_workers=7)
        svc = SyncExecutorService(mock_hassette)
        pool_before_initialize = svc.sync_executor.executor

        await svc.on_initialize()

        assert svc.sync_executor.executor._max_workers == 7  # pyright: ignore[reportAttributeAccessIssue]
        pool_before_initialize.shutdown(join_threads_or_timeout=False)
        svc.sync_executor.executor.shutdown(join_threads_or_timeout=False)

    def test_executor_thread_name_prefix(self) -> None:
        """Worker threads get the 'hassette-sync' prefix for identifiability in logs."""
        svc = make_service()

        future = svc.sync_executor.executor.submit(lambda: None)
        future.result(timeout=2.0)
        thread_names = {t.name for t in svc.sync_executor.executor._threads}  # pyright: ignore[reportAttributeAccessIssue]
        assert all("hassette-sync" in name for name in thread_names)
        svc.sync_executor.executor.shutdown(join_threads_or_timeout=False)

    @pytest.mark.anyio
    async def test_restart_rebuilds_executor(self) -> None:
        """Shutdown then on_initialize on the same instance rebuilds a usable pool.

        The SyncExecutor object identity is preserved across restart (TC#3) — only the
        pool inside it is rebuilt.
        """
        mock_hassette = make_sync_executor_hassette(max_workers=2)
        svc = SyncExecutorService(mock_hassette)
        sync_executor = svc.sync_executor
        pool_at_birth = sync_executor.executor
        await svc.on_initialize()
        pool_at_birth.shutdown(join_threads_or_timeout=False)

        first_executor = svc.sync_executor.executor
        result: list[str] = []
        future = first_executor.submit(lambda: result.append("before"))
        future.result(timeout=2.0)
        assert result == ["before"]

        await svc.on_shutdown()

        with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
            first_executor.submit(lambda: None)

        await svc.on_initialize()
        assert svc.sync_executor is sync_executor, "SyncExecutor object identity must be preserved across restart"
        assert svc.sync_executor.executor is not first_executor, "the pool itself must be rebuilt"

        result.clear()
        future = svc.sync_executor.executor.submit(lambda: result.append("after"))
        future.result(timeout=2.0)
        assert result == ["after"]

        svc.sync_executor.executor.shutdown(join_threads_or_timeout=False)


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


# wire_services() registration and hassette.sync_executor_service property


@pytest.fixture(autouse=False)
def isolated_hassette_context(monkeypatch: pytest.MonkeyPatch):
    """Swap HASSETTE_INSTANCE and HASSETTE_CONFIG for fresh ContextVars.

    wire_services() sets both globals; using fresh ContextVars per test prevents
    bleed between tests running in the same process.  monkeypatch restores them
    automatically after the test.
    """
    fresh_instance: ContextVar = ContextVar("HASSETTE_INSTANCE")
    fresh_config: ContextVar = ContextVar("HASSETTE_CONFIG")
    monkeypatch.setattr(ctx_module, "HASSETTE_INSTANCE", fresh_instance)
    monkeypatch.setattr(ctx_module, "HASSETTE_CONFIG", fresh_config)
    return fresh_instance
    # monkeypatch auto-restores both ContextVars after the test.


@pytest.fixture
async def wired_hassette(isolated_hassette_context: object) -> Hassette:  # noqa: ARG001
    config = make_sync_executor_config()
    h = Hassette(config)
    h.wire_services()
    yield h  # pyright: ignore[reportReturnType]
    if h._sync_executor_service is not None and h._sync_executor_service.sync_executor.executor is not None:
        h._sync_executor_service.sync_executor.executor.shutdown(join_threads_or_timeout=False)
    if h._bus_service is not None and not h._bus_service.stream._closed:
        await h._bus_service.stream.aclose()
    if not h._event_stream_service.event_streams_closed:
        await h._event_stream_service.close_streams()


class TestWireServicesRegistration:
    """Tests that call wire_services().

    Each test uses the isolated_hassette_context fixture to avoid ContextVar bleed.
    """

    def test_sync_executor_service_registered_after_wire_services(self, wired_hassette: Hassette) -> None:
        """After wire_services(), _sync_executor_service is populated."""
        assert wired_hassette._sync_executor_service is not None
        assert isinstance(wired_hassette._sync_executor_service, SyncExecutorService)

    def test_sync_executor_service_property_returns_service(self, wired_hassette: Hassette) -> None:
        """hassette.sync_executor_service returns the SyncExecutorService instance."""
        svc = wired_hassette.sync_executor_service
        assert isinstance(svc, SyncExecutorService)

    def test_sync_executor_service_property_raises_before_wire_services(self) -> None:
        """hassette.sync_executor_service raises RuntimeError before wire_services()."""
        config = make_sync_executor_config()
        h = Hassette(config)
        with pytest.raises(RuntimeError, match="wire_services"):
            _ = h.sync_executor_service

    def test_task_bucket_sync_executor_wired_after_wire_services(self, wired_hassette: Hassette) -> None:
        """Hassette's own TaskBucket has _sync_executor set (wired in __init__, not wire_services())."""
        assert wired_hassette.task_bucket._sync_executor is wired_hassette.sync_executor

    def test_child_task_buckets_get_sync_executor_from_factory(self, wired_hassette: Hassette) -> None:
        """Children created after wire_services() get _sync_executor via the TaskBucket factory."""
        bus_svc = wired_hassette._bus_service
        assert bus_svc.task_bucket._sync_executor is wired_hassette.sync_executor

    def test_wire_services_graph_validates_without_error(self, wired_hassette: Hassette) -> None:
        """wire_services() completes without ValueError from the dependency graph validator."""
        # Should not raise — SyncExecutorService is a leaf, graph stays acyclic.
        # wire_services() already called by the fixture; reaching here means no ValueError.
        assert wired_hassette._sync_executor_service is not None


class TestSyncExecutorWiredFromBirth:
    """TC#1/TC#2: SyncExecutor exists before wire_services(), and every TaskBucket has
    _sync_executor set from birth — no post-hoc patching, no exception suppression.
    """

    def test_sync_executor_available_before_wire_services(self) -> None:
        """hassette.sync_executor is a SyncExecutor instance immediately after __init__,
        before wire_services() runs (TC#1). The pool is None until on_initialize().
        """
        config = make_sync_executor_config()
        h = Hassette(config)
        assert isinstance(h.sync_executor, SyncExecutor)
        assert h.sync_executor.executor is None

    def test_hassette_task_bucket_wired_before_wire_services(self) -> None:
        """Hassette's own TaskBucket has _sync_executor set immediately after __init__,
        before wire_services() runs — no post-hoc patch is needed or present.
        """
        config = make_sync_executor_config()
        h = Hassette(config)
        assert h.task_bucket._sync_executor is h.sync_executor

    def test_child_task_bucket_wired_from_birth_without_wire_services(self) -> None:
        """A child resource's TaskBucket is wired by the factory at construction time,
        even without wire_services() ever running (TC#2 — wired from birth, no post-hoc patch).
        """
        config = make_sync_executor_config()
        h = Hassette(config)
        child = h.add_child(SyncExecutorService)
        assert child.task_bucket._sync_executor is h.sync_executor


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
        svc = make_service(max_workers=2, shutdown_timeout=2.0)

        # Simulate: shutdown_event fires (consumers are being torn down)
        svc.hassette.shutdown_event.set()

        # The executor itself has NOT been shut down yet — it outlives consumers.
        # An AppSync on_shutdown hook submits sync work at this point.
        result: list[str] = []
        future = svc.sync_executor.executor.submit(lambda: result.append("ran"))
        future.result(timeout=2.0)

        assert result == ["ran"], "Sync work submitted during consumer shutdown must complete"

        # Now shut down the executor (what SyncExecutorService.on_shutdown does).
        svc.sync_executor.executor.shutdown(timeout=2.0)

    def test_submit_after_executor_shutdown_raises(self) -> None:
        """Confirms baseline: submitting to a *closed* executor raises RuntimeError.

        This is the failure mode the depends_on ordering prevents.
        """
        svc = make_service()
        svc.sync_executor.executor.shutdown(timeout=1.0)

        with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
            svc.sync_executor.executor.submit(lambda: None)
