import asyncio
import contextlib
import inspect
import itertools
import logging
import threading
import traceback
import typing
from collections.abc import Callable, Generator
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from aiohttp import web
from yarl import URL

from hassette import HassetteConfig, context
from hassette.api import Api
from hassette.bus import Bus
from hassette.bus.error_context import BusErrorContext
from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY, StateRegistry, TypeRegistry
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.event_stream_service import EventStreamService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy
from hassette.core.websocket_service import WebsocketService
from hassette.events import Event
from hassette.resources.base import Resource
from hassette.scheduler import Scheduler
from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.test_utils.test_server import SimpleTestServer
from hassette.types.enums import ResourceStatus
from hassette.utils.service_utils import wait_for_ready
from hassette.utils.url_utils import build_rest_url, build_ws_url

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict


# ---------------------------------------------------------------------------
# Timeout constants — centralised here so rationale is documented in one place
# ---------------------------------------------------------------------------
#
# Do not use raw floats in harness code — reference these constants instead so
# any future re-tuning is a single-site edit.


class TIMEOUTS:
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

    # How long HassetteHarness.stop() allows for a resource to shut down cleanly.
    # Resources should shut down near-instantly in tests; 5 s covers pathological
    # cases (e.g., a resource waiting on a background task before cancelling).
    SHUTDOWN: float = 5.0


async def wait_for(
    predicate: Callable[[], bool], *, timeout: float = 3.0, interval: float = 0.02, desc: str = "condition"
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if predicate():
            return
        if loop.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {desc}")
        await asyncio.sleep(interval)


async def shutdown_resource(res: Resource) -> None:
    logger = logging.getLogger("hassette.test_utils.harness")
    try:
        await res.shutdown()
    except Exception:
        logger.warning("Error shutting down resource %r", res, exc_info=True)
        raise


class _HassetteMock(Resource):
    task_bucket: TaskBucket

    def _should_skip_dependency_check(self) -> bool:
        return True

    def __init__(self, *, config: HassetteConfig) -> None:
        self.config = config
        super().__init__(cast("Hassette", self))

        self.ready_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.children: list[Resource] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._event_stream_service: EventStreamService | None = None

        self._api_service: ApiResource | None = None
        self.api: Api | None = None
        self._bus_service: BusService | None = None
        self._bus: Bus | None = None
        self._scheduler_service: SchedulerService | None = None
        self._scheduler: Scheduler | None = None
        self._file_watcher: FileWatcherService | None = None
        self._app_handler: AppHandler | None = None
        self._command_executor: Any | None = None
        self._websocket_service: WebsocketService | None = None
        self._state_proxy: StateProxy | None = None
        self._states: StateManager | None = None
        self.state_registry: StateRegistry | None = None
        self.type_registry: TypeRegistry | None = None

    @property
    def command_executor(self) -> Any:
        """Mock command executor for telemetry recording."""
        return self._command_executor

    @property
    def ws_url(self) -> str:
        """Construct the WebSocket URL for Home Assistant."""
        return build_ws_url(self.config)

    @property
    def rest_url(self) -> str:
        """Construct the REST API URL for Home Assistant."""
        return build_rest_url(self.config)

    async def send_event(self, topic: str, event: Event[Any]) -> None:
        if not self._event_stream_service:
            raise RuntimeError("Bus is not enabled on this harness")
        await self._event_stream_service.send_event(topic, event)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            raise RuntimeError("Event loop is not running")
        return self._loop

    async def wait_for_ready(self, resources: "list[Resource] | Resource", timeout: float | None = None) -> bool:
        """Immediately return True (no-op stub).

        In the test harness, services call ``self.hassette.wait_for_ready()``
        during ``on_initialize()``.  The harness controls the lifecycle
        explicitly (``HassetteHarness.start()`` waits on real children via
        the utility function), so dependency waits inside individual services
        must be no-ops — allowing them to block would deadlock the startup
        sequence.

        The old polling implementation returned True accidentally
        (``Mock.is_ready()`` is truthy); this makes the intent explicit.

        Note: This no-op stub is NOT the right tool for testing startup
        races (e.g., "what happens when a dependency is not yet ready?").
        For startup race tests, use ``asyncio.Event`` as a gate and inject a
        custom ``wait_for_ready`` side-effect. See ``CLAUDE.md`` → "Bug
        Investigation Workflow" for the recommended pattern using
        ``AsyncMock(side_effect=lambda _: gate.wait())``.
        """
        return True

    def get_app(self, name: str, index: int = 0) -> Any:
        if not self._app_handler:
            raise RuntimeError("App handler is not enabled on this harness")
        return self._app_handler.get(name, index=index)

    @property
    def event_streams_closed(self) -> bool:
        """Check if the event streams are closed."""
        if not self._event_stream_service:
            return True
        return self._event_stream_service.event_streams_closed


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
            setattr(config, key, value)


# ---------------------------------------------------------------------------
# Dependency graph and startup ordering for HassetteHarness components
# ---------------------------------------------------------------------------


def _topological_sort(graph: dict[str, set[str]]) -> list[str]:
    """Return node names from *graph* in valid initialization order (deps before dependents).

    Uses iterative DFS with three-color (_white/_gray/_black) marking.  Only nodes
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

    _white, _gray, _black = 0, 1, 2
    color: dict[str, int] = {node: _white for node in graph}
    result: list[str] = []

    for start in graph:
        if color[start] != _white:
            continue

        stack: list[tuple[str, typing.Iterator[str]]] = []
        path: list[str] = []

        color[start] = _gray
        path.append(start)
        stack.append((start, iter(dep for dep in graph[start] if dep in graph)))

        while stack:
            node, deps = stack[-1]
            try:
                dep = next(deps)
            except StopIteration:
                stack.pop()
                path.pop()
                color[node] = _black
                result.append(node)
                continue

            if color.get(dep, _black) == _gray:
                cycle_start = path.index(dep)
                cycle_path = [*path[cycle_start:], dep]
                raise ValueError("Cycle detected: " + " → ".join(cycle_path))

            if color.get(dep, _black) == _white:
                color[dep] = _gray
                path.append(dep)
                stack.append((dep, iter(d for d in graph[dep] if d in graph)))

    return result


_DEPENDENCIES: dict[str, set[str]] = {
    "bus": set(),
    "scheduler": set(),
    "file_watcher": set(),
    "api_mock": set(),
    "app_handler": {"bus", "scheduler", "state_proxy"},
    "state_proxy": {"bus", "scheduler"},
    "state_registry": set(),
    # service_watcher removed: ServiceWatcher is a real framework service but has no
    # harness starter — the harness does not instantiate it.  Removing it eliminates
    # the ghost entry that caused _STARTUP_ORDER to include a component with no starter.
}

_CONFLICTS: list[tuple[str, str]] = []

# Startup order derived from the dependency graph — no manual maintenance required.
_STARTUP_ORDER: list[str] = _topological_sort(_DEPENDENCIES)

# Maps harness component names to the corresponding real framework service class.
# Used by the harness consistency test to verify _DEPENDENCIES stays in sync with
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
_COMPONENT_CLASS_MAP: dict[str, type[Resource]] = {
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

        # need this for caplog to work properly
        logging.getLogger("hassette").propagate = True

        self.logger = logging.getLogger("hassette")
        self.hassette = _HassetteMock(config=self.config)
        self._exit_stack = contextlib.AsyncExitStack()  # canonical cleanup registry for background-task starters
        self.api_mock: SimpleTestServer | None = None
        self.api_base_url = URL.build(scheme="http", host="127.0.0.1", port=self.unused_tcp_port, path="/api/")

        self._previous_task_factory: typing.Any = None
        self._hassette_ctx_token: typing.Any = None  # Token[Hassette] | None

        if not skip_global_set:
            self._hassette_ctx_token = context.set_global_hassette(cast("Hassette", self.hassette))
        self.config.set_validated_app_manifests()

    # --- Public accessor properties ---

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

    # --- State seeding helper ---

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
            async with asyncio.timeout(TIMEOUTS.STATE_SEED_LOCK):
                await lock.acquire()
        except TimeoutError as exc:
            msg = (
                f"seed_state: could not acquire StateProxy lock "
                f"within {TIMEOUTS.STATE_SEED_LOCK}s for entity {entity_id!r}"
            )
            raise TimeoutError(msg) from exc
        try:
            proxy.states[entity_id] = state_dict
        finally:
            lock.release()

    # --- Builder methods (return self for chaining) ---

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

    # --- Convenience query ---

    def _has(self, component: str) -> bool:
        return component in self._components

    # --- Dependency resolution ---

    def _resolve_dependencies(self) -> None:
        """Add implicit dependencies and validate conflicts."""
        changed = True
        while changed:
            changed = False
            for component in list(self._components):
                deps = _DEPENDENCIES.get(component, set())
                new_deps = deps - self._components
                if new_deps:
                    self._components |= new_deps
                    changed = True

        for a, b in _CONFLICTS:
            if a in self._components and b in self._components:
                raise ValueError(f"Cannot use both {a} and {b}")

    # --- Lifecycle ---

    async def __aenter__(self) -> "HassetteHarness":
        await self.start()

        assert self.hassette._loop is not None, "Event loop is not running"
        assert self.hassette._loop.is_running(), "Event loop is not running"
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.stop()

    async def start(self) -> "HassetteHarness":
        self._resolve_dependencies()

        self.hassette._loop = asyncio.get_running_loop()
        self._previous_task_factory = self.hassette._loop.get_task_factory()
        self.hassette._loop_thread_id = threading.get_ident()
        self.hassette.task_bucket = TaskBucket(cast("Hassette", self.hassette), parent=self.hassette)  # pyright: ignore[reportArgumentType]
        self.hassette._loop.set_task_factory(make_task_factory(self.hassette.task_bucket))  # pyright: ignore[reportArgumentType]

        # Start components in dependency order
        for component in _STARTUP_ORDER:
            if not self._has(component):
                continue
            starter = self._starters.get(component)
            if starter:
                await starter(self)

        # Set up API and websocket mocks if not provided by a real component
        if not self.hassette._api_service:
            self.hassette._api_service = Mock()
            self.hassette._api_service.ready_event = asyncio.Event()
            self.hassette._api_service.ready_event.set()

        if not self.hassette._websocket_service:
            self.hassette._websocket_service = Mock()
            self.hassette._websocket_service.ready_event = asyncio.Event()
            self.hassette._websocket_service.ready_event.set()

        if not self.hassette.api:
            self.hassette.api = AsyncMock()
            self.hassette.api.sync = Mock()
            self.hassette.api.get_states_raw = AsyncMock(return_value=[])

        self.hassette._states = self.hassette.add_child(StateManager)

        if not self._has("bus"):
            self.hassette.send_event = AsyncMock()

        for resource in self.hassette.children:
            resource.start()

        self.hassette.ready_event.set()
        ready = await wait_for_ready(
            [x for x in self.hassette.children],
            timeout=TIMEOUTS.WAIT_FOR_READY,
            shutdown_event=self.hassette.shutdown_event,
        )
        if not ready:
            not_ready = [r for r in self.hassette.children if not getattr(r, "is_ready", lambda: True)()]
            names = [type(r).__name__ for r in not_ready] or ["unknown"]
            raise TimeoutError(
                f"HassetteHarness: components did not become ready within {TIMEOUTS.WAIT_FOR_READY}s: {names}"
            )

        return self

    async def stop(self) -> None:
        self.hassette.shutdown_event.set()

        # Shut down in reverse order so dependents stop before their dependencies.
        shutdown_errors: list[Exception] = []
        for resource in reversed(self.hassette.children):
            try:
                await shutdown_resource(resource)
            except Exception as exc:
                shutdown_errors.append(exc)

        # Close event streams after all children have stopped — children send
        # STOPPED status events during shutdown, so streams must stay open until then.
        try:
            if self.hassette._event_stream_service and not self.hassette._event_stream_service.event_streams_closed:
                await self.hassette._event_stream_service.close_streams()
        except Exception as exc:
            shutdown_errors.append(exc)

        try:
            await self._exit_stack.aclose()
        except Exception as exc:
            shutdown_errors.append(exc)

        if self.hassette._loop is not None:
            self.hassette._loop.set_task_factory(self._previous_task_factory)
        self.hassette._loop = None
        self.hassette._loop_thread_id = None

        if self._hassette_ctx_token is not None:
            context.HASSETTE_INSTANCE.reset(self._hassette_ctx_token)

        # Assert clean AFTER all other cleanup so assertion errors are not masked.
        try:
            if self.api_mock is not None:
                self.api_mock.assert_clean()
        except AssertionError as exc:
            shutdown_errors.append(exc)

        if shutdown_errors:
            raise ExceptionGroup("errors during harness teardown", shutdown_errors)

    # --- Component starters ---

    async def _start_bus(self) -> None:
        self.hassette._event_stream_service = self.hassette.add_child(EventStreamService)

        async def _stub_execute(cmd: Any) -> None:
            if isinstance(cmd, InvokeHandler):
                error_handler = cmd.listener.error_handler or cmd.app_level_error_handler
                if error_handler is None:
                    await cmd.listener.invoke(cmd.event)
                    return

                try:
                    await cmd.listener.invoke(cmd.event)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    ctx = BusErrorContext(
                        exception=exc,
                        traceback="".join(traceback.format_exception(exc)),
                        topic=cmd.topic,
                        listener_name=repr(cmd.listener),
                        event=cmd.event,
                    )
                    # NOTE: the harness does NOT test timeout enforcement,
                    # task spawn isolation, or failure counter — those are
                    # covered by integration tests via real CommandExecutor.
                    try:
                        result = error_handler(ctx)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        logging.getLogger("hassette.test_utils.harness").warning(
                            "Bus error handler raised during harness dispatch (topic=%s)",
                            cmd.topic,
                            exc_info=True,
                        )

        _listener_id_counter = itertools.count(1)

        async def _register_listener_stub(*_args: Any, **_kwargs: Any) -> int:
            return next(_listener_id_counter)

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
                error_handler = cmd.job.error_handler or cmd.app_level_error_handler
                if error_handler is None:
                    await cmd.callable()
                    return

                try:
                    await cmd.callable()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    ctx = SchedulerErrorContext(
                        exception=exc,
                        traceback="".join(traceback.format_exception(exc)),
                        job_name=cmd.job.name,
                        job_group=cmd.job.group,
                        args=cmd.job.args,
                        kwargs=dict(cmd.job.kwargs),
                    )
                    # NOTE: the harness does NOT test timeout enforcement,
                    # task spawn isolation, or failure counter — those are
                    # covered by integration tests via real CommandExecutor.
                    try:
                        result = error_handler(ctx)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        logging.getLogger("hassette.test_utils.harness").warning(
                            "Scheduler error handler raised during harness dispatch (job=%s)",
                            cmd.job.name,
                            exc_info=True,
                        )

        _job_id_counter = itertools.count(1)

        async def _register_job_stub(*_args: Any, **_kwargs: Any) -> int:
            return next(_job_id_counter)

        mock_executor = AsyncMock()
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
        self.hassette._websocket_service.status = ResourceStatus.RUNNING

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
            headers_factory=lambda: {"Authorization": "Bearer test_token"},
        )
        self.hassette.api = self.hassette.add_child(Api)

        self.api_mock = mock_server

    async def _start_state_proxy(self) -> None:
        self.hassette._state_proxy = self.hassette.add_child(StateProxy)

    async def _start_state_registry(self) -> None:
        self.hassette.state_registry = STATE_REGISTRY
        self.hassette.type_registry = TYPE_REGISTRY

    # Dispatch table: component name → starter method
    _starters: typing.ClassVar[dict[str, Callable[["HassetteHarness"], typing.Awaitable[None]]]] = {
        "bus": _start_bus,
        "scheduler": _start_scheduler,
        "file_watcher": _start_file_watcher,
        "api_mock": _start_api_mock,
        "app_handler": _start_app_handler,
        "state_proxy": _start_state_proxy,
        "state_registry": _start_state_registry,
    }
