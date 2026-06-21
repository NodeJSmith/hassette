import asyncio
import contextlib
import inspect
import itertools
import logging
import threading
import traceback
import typing
from collections.abc import Awaitable, Callable, Generator
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from aiohttp import web
from yarl import URL

from hassette import HassetteConfig, context
from hassette.api import Api
from hassette.bus import Bus
from hassette.bus.error_context import BusErrorContext
from hassette.commands import ExecuteJob, InvokeHandler
from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.core import Hassette
from hassette.core.event_stream_service import EventStreamService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.loop_watchdog import LoopWatchdog
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.core.websocket_service import WebsocketService
from hassette.resources.base import Resource
from hassette.scheduler import Scheduler
from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.test_utils.config import TEST_TOKEN
from hassette.test_utils.reset import reset_app_handler, reset_bus, reset_mock_api, reset_scheduler, reset_state_proxy
from hassette.test_utils.test_server import SimpleTestServer
from hassette.types.enums import ResourceStatus

if typing.TYPE_CHECKING:
    from hassette.config.classes import AppManifest
    from hassette.events import Event, HassStateDict

#
# Do not use raw floats in harness code — reference these constants instead so
# any future re-tuning is a single-site edit.


class Timeouts:
    """Centralised timeout constants for the test harness.

    All values are in seconds. Rationale for each value is documented below.
    Changing a value here propagates everywhere the constant is used.
    """

    # How long HassetteHarness.start() waits for all children to become ready.
    # 5 s gives enough headroom for slow CI machines without masking real hangs.
    WAIT_FOR_READY: float = 5.0

    # How long seed_state() waits to acquire the StateProxy write lock.
    # Under test conditions the lock should never be contended for long; 5 s is
    # a generous upper bound that catches genuine deadlocks without false-positive
    # failures on slow machines.
    STATE_SEED_LOCK: float = 5.0


async def wait_for(
    predicate: Callable[[], bool] | Callable[[], typing.Awaitable[bool]],
    *,
    timeout: float = 3.0,
    interval: float = 0.02,
    desc: str = "condition",
) -> None:
    is_async = inspect.iscoroutinefunction(predicate)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        result = (await predicate()) if is_async else predicate()  # pyright: ignore[reportGeneralIssues]
        if result:
            return
        if loop.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {desc}")
        await asyncio.sleep(interval)


async def shutdown_resource(res: Resource) -> None:
    await res.shutdown()


async def _harness_dispatch(
    invoke_fn: Callable[[], Awaitable[None]],
    error_handler: Callable[..., Any] | None,
    make_error_context: Callable[[Exception], Any],
    log_label: str,
) -> None:
    """Shared dispatch logic for bus and scheduler harness stubs.

    The harness does NOT test timeout enforcement, task spawn isolation, or
    failure counter — those are covered by integration tests via real CommandExecutor.
    """
    if error_handler is None:
        await invoke_fn()
        return
    try:
        await invoke_fn()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        ctx = make_error_context(exc)
        try:
            result = error_handler(ctx)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logging.getLogger("hassette.test_utils.harness").warning(
                "Error handler raised during harness dispatch (%s)", log_label, exc_info=True
            )


class _HarnessEventStreamService(EventStreamService):
    """EventStreamService variant that suppresses close_streams() for test harness reuse.

    Module-scoped fixtures share a single _TestableHassette across many tests.  Some
    test scenarios (e.g., ServiceWatcher max-restart exceeded) trigger
    ``hassette.shutdown()``, which normally closes the anyio memory streams inside
    ``EventStreamService``.  Closed streams cannot be reopened, so subsequent tests
    in the same module would receive ``ClosedResourceError`` on every ``send_event``
    call.

    By making ``close_streams()`` a no-op here, the streams remain open for the
    lifetime of the harness.  Explicit stream teardown is handled by
    ``HassetteHarness.stop()``, which calls ``_close_streams_now()`` directly —
    the only code path that should close streams in test context.
    """

    async def close_streams(self) -> None:
        """No-op in test context — streams are closed by HassetteHarness.stop() instead."""

    async def _close_streams_now(self) -> None:
        """Close streams unconditionally — bypasses the no-op override above."""
        await super().close_streams()


class _TestableHassette(Hassette):
    """Thin Hassette subclass for use in the test harness.

    Overrides exactly two methods to make the harness lifecycle work:
    - _should_skip_dependency_check: prevents startup from blocking on unmet deps.
    - wait_for_ready: returns True immediately so services do not deadlock during
      harness-controlled startup.
    """

    def _should_skip_dependency_check(self) -> bool:
        return True

    async def wait_for_ready(self, resources: list[Resource] | Resource, timeout: float | None = None) -> bool:
        """Immediately return True (no-op stub).

        In the test harness, services call ``self.hassette.wait_for_ready()``
        during ``on_initialize()``.  The harness controls the lifecycle
        explicitly (``HassetteHarness.start()`` waits on real children via
        the utility function), so dependency waits inside individual services
        must be no-ops — allowing them to block would deadlock the startup
        sequence.

        Note: This no-op stub is NOT the right tool for testing startup
        races (e.g., "what happens when a dependency is not yet ready?").
        For startup race tests, use ``asyncio.Event`` as a gate and inject a
        custom ``wait_for_ready`` side-effect. See ``CLAUDE.md`` → "Bug
        Investigation Workflow" for the recommended pattern using
        ``AsyncMock(side_effect=lambda _: gate.wait())``.
        """
        return True


@contextlib.contextmanager
def preserve_config(config: HassetteConfig) -> Generator[None, None, None]:
    """Snapshot and restore config values around a test.

    Enables module-scoped hassette reuse when tests mutate config.
    """
    original = config.model_dump()
    try:
        yield
    finally:
        for key, value in original.items():
            field_info = type(config).model_fields.get(key)
            if (
                field_info
                and field_info.annotation is not None
                and isinstance(value, dict)
                and hasattr(field_info.annotation, "model_validate")
            ):
                setattr(config, key, field_info.annotation.model_validate(value))
            else:
                setattr(config, key, value)


def sort_harness_graph(graph: dict[str, set[str]]) -> list[str]:
    """Return node names from *graph* in valid initialization order (deps before dependents).

    Uses iterative DFS with three-color (white/gray/black) marking.  Only nodes
    present as keys in *graph* are included in the output; dependency references
    to nodes not in *graph* are silently ignored.

    Args:
        graph: Adjacency map of node name → set of dependency names.

    Returns:
        A list of all node names ordered so that every dependency appears before
        the nodes that depend on it.

    Raises:
        ValueError: If a cycle is detected.
    """
    if not graph:
        return []

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {node: white for node in graph}
    result: list[str] = []

    for start in graph:
        if color[start] != white:
            continue

        stack: list[tuple[str, typing.Iterator[str]]] = []
        path: list[str] = []

        color[start] = gray
        path.append(start)
        stack.append((start, iter(dep for dep in graph[start] if dep in graph)))

        while stack:
            node, deps = stack[-1]
            try:
                dep = next(deps)
            except StopIteration:
                stack.pop()
                path.pop()
                color[node] = black
                result.append(node)
                continue

            if color.get(dep, black) == gray:
                cycle_start = path.index(dep)
                cycle_path = [*path[cycle_start:], dep]
                raise ValueError("Cycle detected: " + " → ".join(cycle_path))

            if color.get(dep, black) == white:
                color[dep] = gray
                path.append(dep)
                stack.append((dep, iter(d for d in graph[dep] if d in graph)))

    return result


DEPENDENCIES: dict[str, set[str]] = {
    "sync_executor": set(),
    "bus": {"sync_executor"},
    "scheduler": {"sync_executor"},
    "file_watcher": set(),
    "api_mock": set(),
    "app_handler": {"bus", "scheduler", "state_proxy", "sync_executor"},
    "state_proxy": {"bus", "scheduler"},
    "state_registry": set(),
    # service_watcher removed: ServiceWatcher is a real framework service but has no
    # harness starter — the harness does not instantiate it.  Removing it eliminates
    # the ghost entry that caused STARTUP_ORDER to include a component with no starter.
}

# Startup order derived from the dependency graph — no manual maintenance required.
STARTUP_ORDER: list[str] = sort_harness_graph(DEPENDENCIES)

# Maps harness component names to the corresponding real framework service class.
# Used by the harness consistency test to verify DEPENDENCIES stays in sync with
# real service depends_on declarations.
#
# Omitted entries:
#   "api_mock"       — harness-specific: wraps ApiResource with URL/header patches and
#                      a local HTTP mock server; there is no single real class equivalent.
#   "file_watcher"   — FileWatcherService has no depends_on (empty list), so consistency
#                      checks would be vacuous.  Omitting avoids false-positive drift.
#   "state_registry" — StateRegistry is not a Resource subclass; it is a plain dataclass
#                      registry with no depends_on concept.
#   "service_watcher"— Removed: ServiceWatcher has no harness starter; including it in
#                      this map without a matching _starters entry created a ghost entry
#                      that made the structural test impossible to satisfy.
COMPONENT_CLASS_MAP: dict[str, type[Resource]] = {
    "sync_executor": SyncExecutorService,
    "bus": BusService,
    "scheduler": SchedulerService,
    "app_handler": AppHandler,
    "state_proxy": StateProxy,
}


class HassetteHarness:
    """Test harness for Hassette with fluent configuration API.

    Use builder methods (`with_bus()`, `with_scheduler()`, etc.) to declare
    which components the test needs.  Dependencies are resolved automatically
    at startup — e.g. `with_state_proxy()` will pull in `bus` without the
    caller having to add it explicitly.
    """

    def __init__(self, config: HassetteConfig, *, unused_tcp_port: int = 0, skip_global_set: bool = False) -> None:
        self.config = config
        self.unused_tcp_port = unused_tcp_port
        self._components: set[str] = set()

        if not config.strict_lifecycle:
            config.strict_lifecycle = True

        self.logger = logging.getLogger("hassette")
        # _TestableHassette.__init__ calls enable_basic_logging() which sets propagate=False and clears handlers.
        # We restore propagate=True afterwards so pytest's caplog fixture can capture hassette log records.
        self.hassette = _TestableHassette(config=self.config)
        logging.getLogger("hassette").propagate = True
        self._exit_stack = contextlib.AsyncExitStack()  # canonical cleanup registry for background-task starters
        self.api_mock: SimpleTestServer | None = None
        self.api_base_url = URL.build(scheme="http", host="127.0.0.1", port=self.unused_tcp_port, path="/api/")

        self._previous_task_factory: typing.Any = None
        self._hassette_ctx_token: typing.Any = None  # Token[Hassette] | None
        self._original_app_manifests: dict[str, AppManifest] | None = None

        if not skip_global_set:
            self._hassette_ctx_token = context.set_global_hassette(self.hassette)
        self.config.set_validated_app_manifests()

    @property
    def state_proxy(self) -> "StateProxy":
        """The StateProxy instance managed by this harness."""
        sp = self.hassette._state_proxy
        if sp is None:
            raise RuntimeError("StateProxy is not available — ensure with_state_proxy() was called")
        return sp

    @property
    def bus_service(self) -> "BusService":
        """The BusService instance managed by this harness."""
        bs = self.hassette._bus_service
        if bs is None:
            raise RuntimeError("BusService is not available — ensure with_bus() was called")
        return bs

    @property
    def scheduler_service(self) -> "SchedulerService":
        """The SchedulerService instance managed by this harness."""
        ss = self.hassette._scheduler_service
        if ss is None:
            raise RuntimeError("SchedulerService is not available — ensure with_scheduler() was called")
        return ss

    @property
    def bus(self) -> "Bus":
        """The Bus instance managed by this harness."""
        b = self.hassette._bus
        if b is None:
            raise RuntimeError("Bus is not available — ensure with_bus() was called")
        return b

    @property
    def scheduler(self) -> "Scheduler":
        """The Scheduler instance managed by this harness."""
        s = self.hassette._scheduler
        if s is None:
            raise RuntimeError("Scheduler is not available — ensure with_scheduler() was called")
        return s

    @property
    def app_handler(self) -> "AppHandler":
        """The AppHandler instance managed by this harness."""
        ah = self.hassette._app_handler
        if ah is None:
            raise RuntimeError("AppHandler is not available — ensure with_app_handler() was called")
        return ah

    @property
    def file_watcher(self) -> "FileWatcherService":
        """The FileWatcherService instance managed by this harness."""
        fw = self.hassette._file_watcher
        if fw is None:
            raise RuntimeError("FileWatcherService is not available — ensure with_file_watcher() was called")
        return fw

    @property
    def task_bucket(self) -> "TaskBucket":
        """The TaskBucket instance managed by this harness."""
        return self.hassette.task_bucket

    @property
    def shutdown_event(self) -> asyncio.Event:
        """The shutdown asyncio.Event from the underlying Hassette instance."""
        return self.hassette.shutdown_event

    @property
    def api(self) -> "Api":
        """The Api instance managed by this harness."""
        a = self.hassette._api
        if a is None:
            raise RuntimeError("Api is not available — harness has not been started")
        return a

    @property
    def states(self) -> "StateManager":
        """The StateManager instance managed by this harness."""
        s = self.hassette._states
        if s is None:
            raise RuntimeError("StateManager is not available — harness has not been started")
        return s

    async def send_event(self, event: "Event[Any]") -> None:
        """Delegate send_event to the underlying Hassette instance."""
        await self.hassette.send_event(event)

    async def reset(self) -> None:
        """Reset all active components to a clean state for the next test.

        Each component is reset independently — Bus and Scheduler are siblings of
        StateProxy under the harness, not children of it. Resetting StateProxy does
        not clear bus listeners or scheduler jobs; each must be reset explicitly.

        Components are only reset when active (``has_component()`` guard or non-None
        check). The cost is negligible per test — one ``remove_all_listeners()`` and
        one ``_remove_all_jobs()`` call at most.
        """
        # app_handler resets first: re-bootstrap registers fresh listeners/jobs,
        # then bus/scheduler resets clear any stale test-added ones.
        if self.has_component("app_handler") and self._original_app_manifests is not None:
            await reset_app_handler(self.app_handler, self._original_app_manifests)
        if self.has_component("state_proxy"):
            await reset_state_proxy(self.state_proxy)
        if self.has_component("bus"):
            await reset_bus(self.bus)
        if self.has_component("scheduler"):
            await reset_scheduler(self.scheduler)
        if self.api_mock is not None:
            reset_mock_api(self.api_mock)

    async def seed_state(self, entity_id: str, state_dict: "HassStateDict") -> None:
        """Seed an entity's state directly into the StateProxy cache.

        Acquires the write lock under asyncio.timeout with a timeout and inserts
        state_dict under entity_id. Does not call mark_ready() — lifecycle management
        is the harness's responsibility.

        Args:
            entity_id: The entity ID to seed (e.g., "light.kitchen").
            state_dict: The raw state dictionary to insert.

        Raises:
            RuntimeError: If StateProxy is not available (with_state_proxy() not called).
            TimeoutError: If the lock cannot be acquired within the timeout.
        """
        proxy = self.state_proxy
        lock = proxy.lock
        try:
            async with asyncio.timeout(Timeouts.STATE_SEED_LOCK):
                await lock.acquire()
        except TimeoutError as exc:
            msg = (
                f"seed_state: could not acquire StateProxy lock "
                f"within {Timeouts.STATE_SEED_LOCK}s for entity {entity_id!r}"
            )
            raise TimeoutError(msg) from exc
        try:
            proxy.states[entity_id] = state_dict
        finally:
            lock.release()

    def with_sync_executor(self) -> "HassetteHarness":
        self._components.add("sync_executor")
        return self

    def with_bus(self) -> "HassetteHarness":
        self._components.add("bus")
        return self

    def with_scheduler(self) -> "HassetteHarness":
        self._components.add("scheduler")
        return self

    def with_api_mock(self) -> "HassetteHarness":
        self._components.add("api_mock")
        return self

    def with_state_proxy(self) -> "HassetteHarness":
        self._components.add("state_proxy")
        return self

    def with_state_registry(self) -> "HassetteHarness":
        self._components.add("state_registry")
        return self

    def with_file_watcher(self) -> "HassetteHarness":
        self._components.add("file_watcher")
        return self

    def with_app_handler(self) -> "HassetteHarness":
        self._components.add("app_handler")
        return self

    def has_component(self, component: str) -> bool:
        """Check whether a component is active (includes transitive deps after start())."""
        return component in self._components

    def _resolve_dependencies(self) -> None:
        """Add implicit dependencies."""
        changed = True
        while changed:
            changed = False
            for component in list(self._components):
                deps = DEPENDENCIES.get(component, set())
                new_deps = deps - self._components
                if new_deps:
                    self._components |= new_deps
                    changed = True

    async def __aenter__(self) -> "HassetteHarness":
        await self.start()

        assert self.hassette._loop is not None, "Event loop is not running"
        assert self.hassette._loop.is_running(), "Event loop is not running"
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.stop()

    async def start(self) -> "HassetteHarness":
        self._resolve_dependencies()

        # Emulate run_forever() on the real Hassette: populate the backing slots that the
        # public loop / loop_thread_id accessors read. These are read-only properties with no
        # setter, so the harness writes the private slots directly — the same way run_forever
        # does — rather than reaching through a public accessor.
        self.hassette._loop = asyncio.get_running_loop()
        self._previous_task_factory = self.hassette._loop.get_task_factory()
        self.hassette._loop_thread_id = threading.get_ident()
        self.hassette.task_bucket = TaskBucket(cast("Hassette", self.hassette), parent=self.hassette)  # pyright: ignore[reportArgumentType]
        self.hassette._loop.set_task_factory(make_task_factory(self.hassette.task_bucket))  # pyright: ignore[reportArgumentType]

        # Install Tier 1 loop-responsiveness watchdog when a real CommandExecutor is present.
        # The harness uses mock executors by default; the watchdog only activates when the
        # executor has a live current_execution attribute (i.e., it is a real CommandExecutor).
        executor = getattr(self.hassette, "_command_executor", None)
        if (
            executor is not None
            and isinstance(executor, CommandExecutor)
            and self.hassette.config.blocking_io.watchdog_enabled
        ):
            _loop = self.hassette._loop
            self.hassette._loop_watchdog = LoopWatchdog(
                self.hassette,
                loop=_loop,
                loop_thread_id=self.hassette._loop_thread_id,
                executor=executor,
                # Mirror core.py: marshal record_blocking_event onto the loop thread so integration
                # tests exercise the same Tier 1 persistence path as production. Without on_stall the
                # watchdog warns but drops telemetry. Gate on is_running() like core does.
                on_stall=lambda ev: (
                    _loop.call_soon_threadsafe(executor.record_blocking_event, ev) if _loop.is_running() else None
                ),
            )
            self.hassette._loop_watchdog.start()

        # Start components in dependency order
        for component in STARTUP_ORDER:
            if not self.has_component(component):
                continue
            starter = self._starters.get(component)
            if starter:
                await starter(self)

        # Set up API and websocket mocks if not provided by a real component
        if not self.hassette._api_service:
            self.hassette._api_service = AsyncMock()
            self.hassette._api_service.ready_event = asyncio.Event()
            self.hassette._api_service.ready_event.set()

        if not self.hassette._websocket_service:
            self.hassette._websocket_service = Mock()
            self.hassette._websocket_service.ready_event = asyncio.Event()
            self.hassette._websocket_service.ready_event.set()

        if not self.hassette._api:
            self.hassette._api = AsyncMock()
            self.hassette._api.sync = Mock()
            self.hassette._api.get_states_raw = AsyncMock(return_value=[])

        self.hassette._states = self.hassette.add_child(StateManager)

        if not self.has_component("bus"):
            self.hassette.send_event = AsyncMock()

        self.hassette.ready_event.set()
        await self.hassette.start_children_and_wait(timeout=Timeouts.WAIT_FOR_READY)

        if self.has_component("app_handler"):
            self._original_app_manifests = {
                k: v.model_copy(deep=True) for k, v in self.app_handler.registry.manifests.items()
            }

        return self

    async def stop(self) -> None:
        self.hassette.shutdown_event.set()
        shutdown_errors: list[Exception] = []

        try:
            # Stop the loop watchdog before shutting down children — avoids spurious stall
            # warnings during teardown and ensures no daemon thread outlives the test. A failed
            # stop() can leave a daemon thread alive across tests, so surface it like the rest.
            if self.hassette._loop_watchdog is not None:
                try:
                    self.hassette._loop_watchdog.stop()
                except Exception as exc:
                    shutdown_errors.append(exc)
                self.hassette._loop_watchdog = None

            # Shut down in reverse order so dependents stop before their dependencies.
            for resource in reversed(self.hassette.children):
                try:
                    await shutdown_resource(resource)
                except Exception as exc:
                    shutdown_errors.append(exc)

            # Close event streams after all children have stopped — children send
            # STOPPED status events during shutdown, so streams must stay open until then.
            # Use _close_streams_now() to bypass the no-op override on _HarnessEventStreamService,
            # which prevents test-initiated hassette.shutdown() calls from closing streams prematurely.
            try:
                ess = self.hassette._event_stream_service
                if isinstance(ess, _HarnessEventStreamService) and not ess.event_streams_closed:
                    await ess._close_streams_now()
            except Exception as exc:
                shutdown_errors.append(exc)

            try:
                await self._exit_stack.aclose()
            except Exception as exc:
                shutdown_errors.append(exc)

            # Assert clean AFTER all other cleanup so assertion errors are not masked.
            try:
                if self.api_mock is not None:
                    self.api_mock.assert_clean()
            except AssertionError as exc:
                shutdown_errors.append(exc)
        finally:
            # Reset the global singleton unconditionally, ahead of the loop teardown below so a
            # failure restoring the loop can't skip it. If any statement above escapes the
            # collected-error net — observed on Python 3.11, where a late teardown exception
            # finalizes before this point — skipping the reset leaks HASSETTE_INSTANCE and poisons
            # every subsequent test on the worker with "already set" errors.
            if self._hassette_ctx_token is not None:
                context.HASSETTE_INSTANCE.reset(self._hassette_ctx_token)

            if self.hassette._loop is not None:
                self.hassette._loop.set_task_factory(self._previous_task_factory)
            self.hassette._loop = None
            self.hassette._loop_thread_id = None

        if shutdown_errors:
            raise ExceptionGroup("errors during harness teardown", shutdown_errors)

    async def _start_sync_executor(self) -> None:
        self.hassette._sync_executor_service = self.hassette.add_child(SyncExecutorService)

    async def _start_bus(self) -> None:
        # Use _HarnessEventStreamService so that test-initiated hassette.shutdown() calls
        # (e.g., ServiceWatcher max-restart exceeded) do not close the anyio streams and
        # break subsequent tests sharing this module-scoped fixture.
        self.hassette._event_stream_service = self.hassette.add_child(_HarnessEventStreamService)

        async def _stub_execute(cmd: Any) -> None:
            if isinstance(cmd, InvokeHandler):
                await _harness_dispatch(
                    invoke_fn=lambda: cmd.listener.invoker.invoke(cmd.event),
                    error_handler=cmd.listener.invoker.error_handler or cmd.app_level_error_handler,
                    make_error_context=lambda exc: BusErrorContext(
                        exception=exc,
                        traceback="".join(traceback.format_exception(exc)),
                        topic=cmd.topic,
                        listener_name=repr(cmd.listener),
                        event=cmd.event,
                    ),
                    log_label=f"topic={cmd.topic}",
                )

        listener_id_counter = itertools.count(1)

        async def _register_listener_stub(*_args: Any, **_kwargs: Any) -> int:
            return next(listener_id_counter)

        mock_executor = AsyncMock(spec=CommandExecutor)
        mock_executor.execute = AsyncMock(side_effect=_stub_execute)
        mock_executor.register_listener = AsyncMock(side_effect=_register_listener_stub)
        mock_executor.reconcile_registrations = AsyncMock()
        self.hassette._bus_service = self.hassette.add_child(
            BusService, stream=self.hassette._event_stream_service.receive_stream.clone(), executor=mock_executor
        )
        self.hassette._bus = self.hassette.add_child(Bus)

    async def _start_scheduler(self) -> None:
        async def _stub_execute(cmd: Any) -> None:
            if isinstance(cmd, ExecuteJob):
                await _harness_dispatch(
                    invoke_fn=cmd.callable,
                    error_handler=cmd.job.error_handler or cmd.app_level_error_handler,
                    make_error_context=lambda exc: SchedulerErrorContext(
                        exception=exc,
                        traceback="".join(traceback.format_exception(exc)),
                        job_name=cmd.job.name,
                        job_group=cmd.job.group,
                        args=cmd.job.args,
                        kwargs=dict(cmd.job.kwargs),
                    ),
                    log_label=f"job={cmd.job.name}",
                )

        job_id_counter = itertools.count(1)

        async def _register_job_stub(*_args: Any, **_kwargs: Any) -> int:
            return next(job_id_counter)

        mock_executor = AsyncMock(spec=CommandExecutor)
        mock_executor.execute = AsyncMock(side_effect=_stub_execute)
        mock_executor.register_job = AsyncMock(side_effect=_register_job_stub)
        self.hassette._scheduler_service = self.hassette.add_child(SchedulerService, executor=mock_executor)
        self.hassette._scheduler = self.hassette.add_child(Scheduler)

    async def _start_file_watcher(self) -> None:
        if not self.hassette.config:
            raise RuntimeError("File watcher requires a config")

        self.hassette._file_watcher = self.hassette.add_child(FileWatcherService)

    async def _start_app_handler(self) -> None:
        self.hassette._command_executor = Mock(spec=CommandExecutor)
        self.hassette._command_executor.reconcile_registrations = AsyncMock()
        self.hassette._app_handler = self.hassette.add_child(AppHandler)
        self.hassette._websocket_service = Mock()
        self.hassette._websocket_service._status = ResourceStatus.RUNNING

    async def _start_api_mock(self) -> None:
        if not self.api_base_url:
            raise RuntimeError("API harness requires api_base_url")
        mock_server = SimpleTestServer()
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", mock_server.handle_request)

        runner = web.AppRunner(app)
        await runner.setup()
        self._exit_stack.push_async_callback(runner.cleanup)

        site = web.TCPSite(runner, self.api_base_url.host or "127.0.0.1", self.api_base_url.port or 80)
        await site.start()
        self._exit_stack.push_async_callback(site.stop)

        self.hassette._websocket_service = Mock(spec=WebsocketService)
        self.hassette._websocket_service.ready_event = asyncio.Event()
        self.hassette._websocket_service.ready_event.set()

        self.hassette._api_service = self.hassette.add_child(
            ApiResource,
            rest_url=str(self.api_base_url),
            headers_factory=lambda: {"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        self.hassette._api = self.hassette.add_child(Api)

        self.api_mock = mock_server

    async def _start_state_proxy(self) -> None:
        self.hassette._state_proxy = self.hassette.add_child(StateProxy)

    async def _start_state_registry(self) -> None:
        self.hassette._state_registry = STATE_REGISTRY
        self.hassette._type_registry = TYPE_REGISTRY

    # Dispatch table: component name → starter method
    _starters: typing.ClassVar[dict[str, Callable[["HassetteHarness"], typing.Awaitable[None]]]] = {
        "sync_executor": _start_sync_executor,
        "bus": _start_bus,
        "scheduler": _start_scheduler,
        "file_watcher": _start_file_watcher,
        "api_mock": _start_api_mock,
        "app_handler": _start_app_handler,
        "state_proxy": _start_state_proxy,
        "state_registry": _start_state_registry,
    }
