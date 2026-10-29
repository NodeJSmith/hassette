import asyncio
import threading
import typing
from contextlib import suppress
from typing import Any

from anyio import BrokenResourceError, ClosedResourceError
from hassette_wire import ResourceStatus

import hassette.utils.date_utils as date_utils
from hassette import context, startup_clock
from hassette.api import Api
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.bus import Bus
from hassette.config import HassetteConfig
from hassette.config.models import FOUNDATION_SHUTDOWN_BUDGET_SECONDS, SESSION_FINALIZE_TIMEOUT_SECONDS
from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY, StateRegistry, TypeRegistry, validate_registries
from hassette.exceptions import FatalError
from hassette.logging_ import enable_basic_logging
from hassette.resources.base import Resource
from hassette.resources.lifecycle import create_lifecycle_task, handle_stop, mark_not_ready, start
from hassette.resources.operations import shutdown_batch
from hassette.resources.shutdown_deadline import deadline_in, elapsed_since, tighten_shutdown_deadline
from hassette.resources.shutdown_outcome import ShutdownOutcome, incomplete_outcome, merge_outcomes
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.utils.service_utils import (
    WaveOutcome,
    WaveResult,
    describe_wave_failure,
    describe_wave_members,
    topological_levels,
    topological_sort,
    validate_dependency_graph,
    wait_for_ready,
    wait_for_wave,
)
from hassette.utils.version_utils import get_version

from .api_resource import ApiResource
from .app_bootstrap_coordinator import AppBootstrapCoordinator
from .app_handler import AppHandler
from .block_io_guard import install as install_block_io_guard
from .block_io_guard import uninstall as uninstall_block_io_guard
from .bus_service import BusService
from .command_executor import CommandExecutor
from .database_service import DatabaseService
from .event_stream_service import EventStreamService
from .file_watcher import FileWatcherService
from .hassette_accessors import HassetteAccessorsMixin, service_not_wired_error
from .logging_service import LoggingService
from .loop_watchdog import LoopWatchdog
from .pipeline_counters import PipelineCounters
from .runtime_query_service import RuntimeQueryService
from .scheduler_service import SchedulerService
from .service_failure import route_service_failure
from .session_manager import SessionManager
from .startup_tasks import run_startup_tasks
from .state_proxy import StateProxy
from .sync_executor import SyncExecutor
from .sync_executor_service import SyncExecutorService
from .telemetry.query_service import TelemetryQueryService
from .web_api_service import WebApiService
from .web_ui_watcher import WebUiWatcherService
from .websocket_service import WebsocketService

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from hassette.events import AnyEvent
    from hassette.resources.service import Service

NO_DROP_COUNTERS = (0, 0, 0)
"""The session's drop counters (overflow, exhausted, shutdown) when the command executor can't report them."""


class Hassette(HassetteAccessorsMixin, Resource):
    """Main class for the Hassette application.

    This class initializes the Hassette instance, manages services, and provides access to the API,
    event bus, app handler, and other core components.
    """

    @property
    def unique_name(self) -> str:
        """Fixed name ``"Hassette"``, since only one live coordinator runs per process at a time."""
        return "Hassette"

    def _get_logger_name(self) -> str:
        # The root of the framework's logger tree; children are hassette.<ClassName>.
        return "hassette"

    def should_skip_dependency_check(self) -> bool:
        """Whether resources skip waiting on their declared ``depends_on`` before initializing.

        Always False in production; the test harness overrides it to return True.
        """
        return False

    def __init__(self, config: HassetteConfig) -> None:
        self.config = config

        self._basic_stream_handler = enable_basic_logging(
            self.config.logging.log_level,
            log_format=self.config.logging.log_format,
            extra_loggers=self.config.logging.extra_loggers,
        )

        # SyncExecutor is built before super().__init__() so it exists before the first
        # TaskBucket is constructed (super().__init__() constructs Hassette's own bucket).
        # A plain class (no Resource/Service base) — see hassette.core.sync_executor.
        # The pool is not created here — SyncExecutorService.on_initialize() calls
        # rebuild_pool() on every initialization.
        self._sync_executor = SyncExecutor()
        self.sync_executor = self._sync_executor

        # Process-wide telemetry loss/sample/failure counters (D24.1). Plain thread-safe class, set
        # unconditionally so every component can increment it from construction onward.
        self.pipeline_counters = PipelineCounters()

        super().__init__(
            self, task_bucket=TaskBucket(self, parent=self, sync_executor=self._sync_executor), parent=self
        )

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None

        # The loop's task factory prior to run_forever() installing Hassette's own -- restored
        # in _shutdown_body()'s finally block so an embedded caller whose event loop outlives
        # this Hassette instance doesn't keep routing every later create_task() through a
        # closure over self.task_bucket after that bucket has been permanently sealed.
        self._previous_task_factory: Callable[..., Any] | None = None

        # Service slot declarations — populated by wire_services()
        self._sync_executor_service: SyncExecutorService | None = None
        self._event_stream_service: EventStreamService | None = None
        self._database_service: DatabaseService | None = None
        self._logging_service: LoggingService | None = None
        self._command_executor: CommandExecutor | None = None
        self._bus_service: BusService | None = None
        self._scheduler_service: SchedulerService | None = None
        self._session_manager: SessionManager | None = None
        self._websocket_service: WebsocketService | None = None
        self._file_watcher: FileWatcherService | None = None
        self._web_ui_watcher: WebUiWatcherService | None = None
        self._app_handler: AppHandler | None = None
        self._app_bootstrap_coordinator: AppBootstrapCoordinator | None = None
        self._api_service: ApiResource | None = None
        self._state_proxy: StateProxy | None = None
        self._runtime_query_service: RuntimeQueryService | None = None
        self._telemetry_query_service: TelemetryQueryService | None = None
        self._web_api_service: WebApiService | None = None
        self._bus: Bus | None = None
        self._scheduler: Scheduler | None = None

        # Public instance slots — populated by wire_services()
        self._api: Api | None = None
        self._states: StateManager | None = None
        self._state_registry: StateRegistry | None = None
        self._type_registry: TypeRegistry | None = None

        # Dependency graph — populated by wire_services()
        self._init_order: list[type[Resource]] = []
        self._init_waves: list[list[type[Resource]]] = []

        # Set by escalate_service_failure() or a startup failure; run_forever() then raises FatalError after teardown.
        self._fatal_shutdown_reason: str | None = None

        # Tier 1 loop-responsiveness watchdog — installed in run_forever(), torn down in before_shutdown().
        self._loop_watchdog: LoopWatchdog | None = None

    def wire_services(self) -> None:
        """Register context variables, wire all services, and validate the dependency graph.

        Must be called after construction and before run_forever().
        """
        self.logger.info(
            "Starting Hassette v%s... (%.2fs since hassette import)",
            get_version(),
            startup_clock.seconds_since_import(),
        )

        date_utils.configure(self.config.timezone)
        if self.config.timezone:
            self.logger.info("Using configured timezone: %s", self.config.timezone)

        # set context variables
        context.set_global_hassette(self)
        context.set_global_hassette_config(self.config)

        run_startup_tasks(self.config, self.logger)

        self._sync_executor_service = self.add_child(SyncExecutorService)

        # private background services — EventStreamService FIRST (BusService needs receive_stream at construction)
        self._event_stream_service = self.add_child(EventStreamService)
        self._database_service = self.add_child(DatabaseService)
        self._logging_service = self.add_child(LoggingService, stream_handler=self._basic_stream_handler)
        self._command_executor = self.add_child(CommandExecutor)
        self._bus_service = self.add_child(
            BusService, stream=self._event_stream_service.receive_stream.clone(), executor=self._command_executor
        )
        self._scheduler_service = self.add_child(SchedulerService, executor=self._command_executor)

        # Resources below have Bus/Scheduler children — must come after _bus_service/_scheduler_service
        self._session_manager = self.add_child(SessionManager, database_service=self._database_service)
        self._websocket_service = self.add_child(WebsocketService)
        self._file_watcher = self.add_child(FileWatcherService)
        self._web_ui_watcher = self.add_child(WebUiWatcherService)
        self._api_service = self.add_child(ApiResource)
        self._state_proxy = self.add_child(StateProxy)
        self._app_bootstrap_coordinator = self.add_child(AppBootstrapCoordinator)
        self._app_handler = self.add_child(AppHandler)

        self._runtime_query_service = self.add_child(RuntimeQueryService)
        self._telemetry_query_service = self.add_child(TelemetryQueryService)
        self._web_api_service = self.add_child(WebApiService)

        # internal instances
        self._bus = self.add_child(Bus)
        self._scheduler = self.add_child(Scheduler)

        # public instances
        self._states = self.add_child(StateManager)
        self._api = self.add_child(Api)
        self._state_registry = STATE_REGISTRY
        self._type_registry = TYPE_REGISTRY

        # Validate dependency graph and compute initialization order.
        # Preserve insertion order (deterministic); deduplicate via dict.fromkeys.
        all_types = list(dict.fromkeys(type(c) for c in self.children))

        # Validate: each child type appears exactly once (wave-based shutdown maps type→instance).
        type_counts = {t: sum(1 for c in self.children if type(c) is t) for t in all_types}
        duplicates = {t.__name__: n for t, n in type_counts.items() if n > 1}
        if duplicates:
            raise ValueError(f"Duplicate child types in Hassette: {duplicates}")

        validate_dependency_graph(all_types)

        # Validate: no cycles; compute dependency levels for wave-based startup/shutdown.
        self._init_order = topological_sort(all_types)
        self._init_waves = topological_levels(all_types)

        # Log the dependency graph — only services with non-empty depends_on (root nodes add noise).
        dep_lines = [
            f"  {t.__name__} -> [{', '.join(d.__name__ for d in t.depends_on)}]" for t in all_types if t.depends_on
        ]
        if dep_lines:
            self.logger.debug("Resource dependency graph:\n%s", "\n".join(dep_lines))

        # Validate STATE_REGISTRY and TYPE_REGISTRY after all service children are added
        # (importing service modules may register additional state/type converters).
        validate_registries(STATE_REGISTRY, TYPE_REGISTRY)

        self.logger.debug("All components registered...", stacklevel=2)

    def get_app(self, app_name: str, index: int = 0) -> App[AppConfig] | None:
        """Get a specific app instance if running.

        Args:
            app_name: The name of the app.
            index: The index of the app instance, defaults to 0.

        Returns:
            App[AppConfig] | None: The app instance if found, else None.
        """
        # note: return type left deliberately empty to allow underlying call to define it

        return self.app_handler.get(app_name, index)

    @classmethod
    def get_instance(cls) -> "Hassette":
        """Get the current instance of Hassette."""
        return context.get_hassette()

    async def send_event(self, event: "AnyEvent") -> None:
        """Send an event to the event bus, dropping it once the event streams are closed.

        A send already waiting on a full channel when the streams close is released and dropped too
        (spec 134 D9).
        """
        if self._event_stream_service is None:
            raise service_not_wired_error("EventStreamService")
        if self.event_streams_closed:
            self.logger.debug("send_event dropped: streams closed (topic=%s)", event.topic)
            return
        # the check above can't cover a send that was already waiting on a full channel when the streams closed
        try:
            await self._event_stream_service.send_event(event)
        except (ClosedResourceError, BrokenResourceError):
            self.logger.debug("send_event dropped: streams closed while sending (topic=%s)", event.topic)

    async def wait_for_ready(self, resources: list[Resource] | Resource, timeout: float | None = None) -> bool:
        """Block until all dependent resources are ready or shutdown is requested.

        Args:
            resources: The resource(s) to wait for.
            timeout: The timeout for the wait operation.

        Returns:
            True if all resources are ready, False if shutdown is requested.
        """
        timeout = timeout if timeout is not None else self.config.lifecycle.startup_timeout_seconds

        return await wait_for_ready(resources, timeout=timeout, shutdown_event=self.shutdown_event)

    async def on_initialize(self) -> None:
        """Emit warnings for disabled global timeouts.

        Called once during startup after log infrastructure is running.
        """
        timeout_checks = (
            ("scheduler_job_timeout_seconds", self.config.scheduler.job_timeout_seconds),
            ("event_handler_timeout_seconds", self.config.lifecycle.event_handler_timeout_seconds),
        )
        for field, value in timeout_checks:
            if value is None:
                self.logger.warning(
                    "%s is None — "
                    "execution timeout enforcement is disabled globally — "
                    "framework components are unprotected",
                    field,
                )

    async def run_forever(self) -> None:
        """Start Hassette and run until shutdown signal is received."""
        if not self._init_waves:
            raise RuntimeError("call wire_services() before run_forever()")
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self.loop.set_debug(self.config.asyncio_debug_mode)

        # Preserve whatever factory (if any) the embedding caller already installed, so
        # _shutdown_body() can restore it instead of leaving the loop permanently routing
        # create_task() through a closure over this instance's own task_bucket.
        self._previous_task_factory = self.loop.get_task_factory()
        # pyright ignore is to handle what seems like another 3.11 bug/type issue
        self.loop.set_task_factory(make_task_factory(self.task_bucket))  # pyright: ignore[reportArgumentType]

        # Install Tier 1 loop-responsiveness watchdog after the loop thread id is captured.
        # Gated on watchdog_enabled (default True); executor is required for marker attribution.
        if self.config.blocking_io.watchdog_enabled and self._command_executor is not None:
            _executor = self._command_executor
            _loop = self._loop
            self._loop_watchdog = LoopWatchdog(
                self,
                loop=_loop,
                loop_thread_id=self._loop_thread_id,
                executor=_executor,
                # The watchdog daemon thread calls on_stall from off-loop; marshal onto the
                # loop thread via call_soon_threadsafe so record_blocking_event always runs
                # on the loop thread (a persistence-layer threading invariant). Gate on is_running(): a loop
                # that is stopped-but-not-closed during shutdown still reports is_closed()
                # False, yet call_soon_threadsafe would schedule a callback that never runs.
                # Residual races after the check: if the loop CLOSES, call_soon_threadsafe
                # raises RuntimeError, caught and debug-logged by LoopWatchdog._emit; if it
                # merely STOPS, the callback is enqueued but never runs — one blocking_events
                # row is silently dropped, which is acceptable for fire-and-forget telemetry.
                on_stall=lambda ev: (
                    _loop.call_soon_threadsafe(_executor.record_blocking_event, ev) if _loop.is_running() else None
                ),
            )
            self._loop_watchdog.start()

        # Install Tier 2 call-site interception (monkeypatch). The dev/prod enablement decision
        # lives inside install_block_io_guard (see _should_install). install() no-ops
        # when disabled, so the only gate here is that an executor exists for marker attribution.
        if self._command_executor is not None:
            install_block_io_guard(
                self,
                loop_thread_id=self._loop_thread_id,
                executor=self._command_executor,
            )

        # on_initialize() runs AFTER the watchdog + Tier 2 guard are installed but BEFORE the
        # managed startup below. A raise here would otherwise skip before_shutdown(), leaking the
        # watchdog daemon thread and the process-global monkeypatches into the process. Route any
        # failure through shutdown() so both detectors are torn down.
        try:
            await self.on_initialize()
        except Exception:
            self.logger.exception("Startup failed during initialization")
            await self._fail_startup("startup failure: initialization raised before service startup")
            return

        self.logger.debug("Waiting for resources to initialize...")

        # The database service starts as a wave of its own, and session tracking is created as soon
        # as it is up: this guarantees a valid session_id exists before any handler can fire.
        # Its wave runs migrations under their own, longer bound, so it waits for the migration
        # budget on top of the normal startup budget (which covers the rest of its initialization).
        # Bounding it by startup_timeout_seconds alone would let a short startup timeout cut every
        # slow migration off, and a supervisor restart would re-run it forever.
        db_startup_timeout = (
            self.config.lifecycle.startup_timeout_seconds + self.config.database.migration_timeout_seconds
        )
        if not await self._start_wave([self.database_service], db_startup_timeout):
            return
        try:
            await self.session_manager.mark_orphaned_sessions()
            await self.session_manager.create_session()
        except Exception:
            self.logger.exception("Failed to initialize session tracking")
            await self._fail_startup("startup failure: session tracking initialization failed")
            return
        self.ready_event.set()

        # Each later wave's deps are ready before it begins, so _auto_wait_dependencies returns
        # immediately.
        type_to_instance = {type(c): c for c in self.children}
        for wave_types in self._init_waves:
            wave = [type_to_instance[t] for t in wave_types if t in type_to_instance]
            wave = [c for c in wave if c is not self.database_service]
            if wave and not await self._start_wave(wave):
                return

        # Clean up stale once=True listeners from previous sessions. Safe to run here
        # because: (a) CommandExecutor is ready, (b) session_id is set, and (c) the
        # NOT EXISTS(... session_id = ?) guard prevents deletion of any listener that
        # has current-session invocations still in the write queue.
        await self.session_manager.cleanup_stale_once_listeners()

        # does not take into consideration if apps failed to load, but those errors would have been logged already
        self.logger.info("All services started successfully.")
        self.logger.info("Hassette is running.")

        if self.shutdown_event.is_set():
            self.logger.warning("Hassette is shutting down, aborting run loop")
            await self.shutdown()

        try:
            await self.shutdown_event.wait()
        except asyncio.CancelledError:  # noqa: ASYNC103 — top-level; cancellation → graceful shutdown
            self.logger.debug("Hassette run loop cancelled")
        except Exception as exc:
            self.logger.error("Error in Hassette run loop: %s", exc)
        finally:
            await self.shutdown()

        self.logger.info("Hassette stopped.")
        self._raise_if_fatal_shutdown()

    async def _start_wave(self, wave: list[Resource], timeout: float | None = None) -> bool:
        """Start one startup wave and wait for it, for ``timeout`` seconds.

        ``timeout`` defaults to ``lifecycle.startup_timeout_seconds``.

        Returns True once the wave has started, and False after tearing down when a shutdown was
        requested mid-wave. A failed or timed-out wave raises ``FatalError`` (via ``_fail_startup()``).

        A boot-time start failure is fatal whether or not the resource is required: the wave joins its members'
        initialization attempts (spec 134 D1), so startup fails at once and the external supervisor restarts
        the process. A failure after the handoff to ``serve()`` is a report (``report_service_failure()``).
        """
        if timeout is None:
            timeout = self.config.lifecycle.startup_timeout_seconds
        # run_forever() runs on the loop thread, so start() always returns the attempt's task here.
        attempts: dict[Resource, asyncio.Task[None] | None] = {}
        for member in wave:
            try:
                attempts[member] = start(member)
            except Exception:
                self.logger.exception("Failed to start %s", member.class_name)
                await self._fail_startup(f"startup failure: could not start: {member.class_name}")
                return False

        result = await self._wait_for_wave(attempts, timeout)
        if result.outcome is WaveOutcome.OK:
            return True
        if result.outcome is WaveOutcome.SHUTDOWN:
            # Shutdown was requested while this wave was still starting — that is a shutdown, not a
            # resource startup failure. It happens when a clean/operator shutdown (or a crash that
            # already recorded its reason) lands before the later waves finish, including the common
            # case where a caller stops the instance right after readiness is signalled.
            # _raise_if_fatal_shutdown raises only when a fatal reason was recorded, so a clean
            # shutdown exits 0.
            await self.shutdown()
            self._raise_if_fatal_shutdown()
            return False

        # The attempt's own exception observer already logged a FAILED wave's traceback at ERROR; the
        # reason carries each cause so the exit message and session record name it too.
        reason = describe_wave_failure(result, timeout)
        self.logger.error("%s, shutting down\n%s", reason, describe_wave_members(result.resources))
        await self._fail_startup(reason)
        return False

    async def _wait_for_wave(self, attempts: dict[Resource, asyncio.Task[None] | None], timeout: float) -> WaveResult:
        """Wait for one startup wave; see ``wait_for_wave()``. A method so tests can stub the wait."""
        return await wait_for_wave(attempts, timeout=timeout, shutdown_event=self.shutdown_event)

    async def _fail_startup(self, reason: str) -> None:
        """Record a fatal startup reason, tear down, and raise ``FatalError``.

        Callers still ``return`` after it: ``_raise_if_fatal_shutdown()`` raises because a reason
        was just recorded, but nothing types that.

        The bus closes the event streams before teardown unless its drain loop is running, so no
        teardown send blocks on a channel nothing will drain (spec 134 D9). A draining bus keeps them
        open, and the shutdown's telemetry reaches it.
        """
        self.record_fatal_reason(reason)
        if self._bus_service is not None:
            await self._bus_service.close_streams_unless_draining()
        await self.shutdown()
        self._raise_if_fatal_shutdown()

    @property
    def fatal_shutdown_reason(self) -> str | None:
        """The reason a fatal shutdown was triggered, or None for a clean shutdown (read-only)."""
        return self._fatal_shutdown_reason

    def record_fatal_reason(self, reason: str) -> None:
        """Record why a fatal shutdown is happening, so the process exits non-zero. The first reason wins.

        Set synchronously at the decision site, before any teardown, so run_forever() sees it without event dispatch.
        """
        if self._fatal_shutdown_reason is None:
            self._fatal_shutdown_reason = reason

    def report_service_failure(self, service: "Service", exc: BaseException) -> None:
        """Route a post-handoff service failure, never awaiting (spec 134 D8); the seam harnesses replace."""
        route_service_failure(self, service, exc)

    @property
    def shutdown_snapshot_task(self) -> "asyncio.Task[bool] | None":
        """The database shutdown snapshot's copy, once the root started it (read-only)."""
        return self._database_service.shutdown_snapshot_task if self._database_service is not None else None

    def _raise_if_fatal_shutdown(self) -> None:
        """Raise FatalError (after a CRITICAL log) if a fatal reason was recorded.

        Called after teardown completes, at the two startup-failure branches and after the run loop.
        """
        if self._fatal_shutdown_reason is not None:
            self.logger.critical("Hassette terminated due to a fatal error: %s", self._fatal_shutdown_reason)
            raise FatalError(self._fatal_shutdown_reason)

    async def _shutdown_children(self) -> ShutdownOutcome:
        """Process exit's two stages: the stop stage, then the foundation stage.

        The stop stage stops every child but the foundation services, in dependency waves (dependents
        first), under ``total_shutdown_timeout_seconds`` minus ``FOUNDATION_SHUTDOWN_BUDGET_SECONDS``. The
        waves have no bound of their own; each child inherits the stage's deadline. When the deadline
        passes, the root stops waiting: every stop-stage child that hasn't finished is force-terminated
        and named in one ERROR.

        The foundation stage then runs whatever happened in the stop stage, under its own fixed budget:
        the session finalize, then the database drain and close, then the executor join. The shutdown
        snapshot runs after it, outside the budget.
        """
        # a raising stop stage must not cost the foundation stage its drain and finalize, nor either the snapshot;
        # the first exception still propagates
        try:
            stop_outcome = await self._run_stop_stage()
        finally:
            try:
                foundation_outcome = await self._run_foundation_stage()
            finally:
                if self._database_service is not None:
                    await self._database_service.write_shutdown_snapshot()
        return merge_outcomes(stop_outcome, foundation_outcome)

    def _foundation_services(self) -> list[Resource]:
        """The children the foundation stage stops, in its order: session, database, executor.

        Each sets ``shutdown_hook_timeout_applies = False``; a new foundation service needs both.
        """
        named = (self._session_manager, self._database_service, self._sync_executor_service)
        return [service for service in named if service is not None]

    async def _run_stop_stage(self) -> ShutdownOutcome:
        """Stop every non-foundation child in dependency waves under the stop stage's deadline."""
        foundation = {id(service) for service in self._foundation_services()}
        type_to_instance = {type(c): c for c in self.children if id(c) not in foundation}
        waves = [
            [type_to_instance[t] for t in wave_types if t in type_to_instance]
            for wave_types in reversed(self._init_waves)
        ]
        waves = [wave for wave in waves if wave]
        stage_children = [child for wave in waves for child in wave]

        async def run_waves() -> ShutdownOutcome:
            outcomes: list[ShutdownOutcome] = []
            for wave in waves:
                names = ", ".join(c.class_name for c in wave)
                self.logger.debug("Shutting down wave: [%s]", names)
                wave_start = asyncio.get_running_loop().time()
                outcomes.append(await shutdown_batch(self, wave, deadline=self._shutdown_deadline))
                self.logger.debug("Shutdown wave [%s] completed in %.2fs", names, elapsed_since(wave_start))
            return merge_outcomes(*outcomes)

        return await self._run_stage("stop", run_waves(), stage_children, deadline=self._shutdown_deadline)

    async def _run_foundation_stage(self) -> ShutdownOutcome:
        """Finalize the session, then stop the database and the executor, under the fixed foundation budget.

        Runs even when the stop stage timed out, so the session record gets the fatal reason and the
        database drains and closes. Executor threads that survive the join are named in one ERROR; under
        ``hassette run`` the exit watchdog bounds them (``server.exit_after_run()``).
        """
        deadline = deadline_in(FOUNDATION_SHUTDOWN_BUDGET_SECONDS)
        services = self._foundation_services()
        step = "session finalize"

        async def run_steps() -> ShutdownOutcome:
            nonlocal step
            await self._finalize_session()
            outcomes: list[ShutdownOutcome] = []
            for service in services:
                step = f"{service.class_name} shutdown"
                outcomes.append(await shutdown_batch(self, [service], deadline=deadline))
            return merge_outcomes(*outcomes)

        outcome = await self._run_stage(
            "foundation", run_steps(), services, deadline=deadline, current_step=lambda: step
        )
        surviving = self._sync_executor.surviving_threads()
        if surviving:
            self.logger.error("Sync executor threads still running after the shutdown join: %s", ", ".join(surviving))
        return outcome

    async def _run_stage(
        self,
        stage: str,
        work: "Coroutine[Any, Any, ShutdownOutcome]",
        stage_children: list[Resource],
        *,
        deadline: float | None,
        current_step: "Callable[[], str] | None" = None,
    ) -> ShutdownOutcome:
        """Run one exit stage, walking away from it when ``deadline`` passes.

        On expiry the stage's unfinished children are force-terminated (which also cancels their
        coordinators) and named in one ERROR, along with ``current_step()`` when given, and the stage's
        own task is cancelled without waiting for the cancellation to land. The stage's outcome is then
        ``INCOMPLETE``. The other walk-away owner, ``AppLifecycleService.walk_away_from_instance()``, follows
        the same order: force-terminate, then cancel.
        """
        task = create_lifecycle_task(work, name=f"hassette:shutdown_stage:{stage}")
        stage_start = asyncio.get_running_loop().time()
        timeout = None if deadline is None else max(0.0, deadline - stage_start)
        done, _pending = await asyncio.wait([task], timeout=timeout)
        if task in done:
            return task.result()

        unfinished = [child for child in stage_children if not child.shutdown_completed]
        detail = f" during the {current_step()}" if current_step is not None else ""
        self.logger.error(
            "Shutdown %s stage gave up after %.2fs%s; force-terminating: %s",
            stage,
            elapsed_since(stage_start),
            detail,
            ", ".join(f"{child.class_name} ({child.status.value})" for child in unfinished) or "nothing left",
        )
        outcomes: list[ShutdownOutcome] = []
        for child in unfinished:
            child._force_terminal()
            if (child_outcome := child.shutdown_outcome) is not None:
                outcomes.append(child_outcome)
        task.cancel()
        outcomes.append(
            incomplete_outcome(f"{self.unique_name}: the shutdown {stage} stage gave up after its deadline passed")
        )
        return merge_outcomes(*outcomes)

    async def _finalize_session(self) -> None:
        """Write the session's final record (status, drop counters, fatal reason) to the database.

        Capped at ``SESSION_FINALIZE_TIMEOUT_SECONDS``, the finalize's share of the foundation budget. A
        failure or timeout is logged, never raised.
        """
        if self._session_manager is None:
            return
        try:
            counters = (
                self._command_executor.get_drop_counters() if self._command_executor is not None else NO_DROP_COUNTERS
            )
        except Exception:
            self.logger.exception("Reading drop counters failed; finalizing the session with zeros")
            counters = NO_DROP_COUNTERS
        # A raise or a hang here must not cost the drain, close, join and snapshot that follow it.
        try:
            async with asyncio.timeout(SESSION_FINALIZE_TIMEOUT_SECONDS):
                await self._session_manager.finalize_session(drop_counters=counters)
        except Exception:
            self.logger.exception("Session finalize failed during shutdown")

    async def _on_children_stopped(self) -> None:
        """Emit Hassette's own STOPPED event, then close event streams.

        Called by the post-hook shutdown stage when the children's merged outcome is restart-safe.
        handle_stop() runs before close_streams(), so the root's STOPPED event is
        delivered if the bus is still draining; once the bus's loop has ended it is dropped.

        When a child's work may still be running, this hook is skipped — Hassette.shutdown()'s finally
        block handles both handle_stop() and close_streams() as a fallback.
        """
        await super()._on_children_stopped()
        await handle_stop(self)
        if self._event_stream_service is not None:
            await self._event_stream_service.close_streams()

    async def _shutdown_body(self) -> ShutdownOutcome:
        """Run the root shutdown body: hooks/cleanup/children, then stream closing and terminal status.

        This is the ordinary hooks/cleanup/children pipeline, with the root owning both exit stages'
        deadlines.

        The root's own hooks, task-cancel and cleanup run under the stop stage's deadline
        (``total_shutdown_timeout_seconds`` minus the foundation budget); ``_shutdown_children()`` runs
        the stop stage under the same deadline and the foundation stage under its own. Nothing bounds
        the body as a whole: each stage's walk-away is the only place the root stops waiting.
        """
        self.logger.info("Hassette shutdown initiated", stacklevel=2)
        total = self.config.lifecycle.total_shutdown_timeout_seconds
        tighten_shutdown_deadline(self, deadline_in(total - FOUNDATION_SHUTDOWN_BUDGET_SECONDS))

        outcome: ShutdownOutcome
        try:
            outcome = await super()._shutdown_body()
        finally:
            # Restore whatever task factory (if any) was installed before run_forever() set
            # its own -- an event loop that outlives this shutdown (an embedded caller, or a
            # test suite reusing the loop across cases) must not keep routing create_task()
            # through a closure over self.task_bucket, which is now permanently sealed.
            if self._loop is not None:
                # pyright ignore for the same apparent 3.11 stub issue as the set_task_factory()
                # call in run_forever() -- a plain callable/None argument is flagged there too.
                self._loop.set_task_factory(self._previous_task_factory)  # pyright: ignore[reportArgumentType]

            # Fallback for a shutdown body that raised before its own handle_stop(): otherwise the root is
            # already STOPPED and handle_stop() is a no-op. The event_streams_closed check only skips a
            # send that would be dropped anyway; the status is set directly below either way.
            if not self.event_streams_closed:
                with suppress(Exception):
                    await handle_stop(self)
            if self._event_stream_service is not None:
                with suppress(OSError):
                    await self._event_stream_service.close_streams()
            if self.status != ResourceStatus.STOPPED:
                self.status = ResourceStatus.STOPPED
            mark_not_ready(self, "shutdown complete")

        return outcome

    async def before_shutdown(self) -> None:
        """Stop the loop watchdog and the block-IO guard, and remove bus listeners, before child shutdown.

        The session finalize runs later, in the foundation stage (``_finalize_session()``).
        """
        # Stop the Tier 1 watchdog first so no spurious stall warnings fire during teardown.
        # stop() joins the daemon thread; log rather than swallow if it raises, so a teardown
        # hang is visible instead of silent.
        if self._loop_watchdog is not None:
            try:
                self._loop_watchdog.stop()
            except Exception:
                self.logger.warning("Loop watchdog stop raised during shutdown", exc_info=True)
            self._loop_watchdog = None
        # Uninstall Tier 2 call-site interception so no patches remain after shutdown.
        # Pass self so a non-owning instance's shutdown cannot remove the owner's process-global
        # patches (Tier 2 has a single owner; uninstall no-ops for non-owners).
        try:
            uninstall_block_io_guard(self)
        except Exception:
            self.logger.warning("Tier 2 block IO guard uninstall raised during shutdown", exc_info=True)
        try:
            if self._bus is not None:
                self._bus.remove_all_listeners()
        except Exception:
            self.logger.exception("Failed to remove bus listeners during shutdown")
