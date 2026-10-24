import asyncio
import threading
import typing
from contextlib import suppress
from typing import Any

from dotenv import load_dotenv
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
from hassette.exceptions import AppPrecheckFailedError, FatalError
from hassette.logging_ import enable_basic_logging
from hassette.resources.base import Resource
from hassette.resources.lifecycle import create_lifecycle_task, handle_stop, mark_not_ready, start
from hassette.resources.operations import finalize_shutdown_report, shutdown_batch
from hassette.resources.shutdown_deadline import deadline_in, elapsed_since, tighten_shutdown_deadline
from hassette.resources.teardown import (
    TeardownCause,
    TeardownReport,
    merge_teardown_reports,
)
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.utils.app_utils import app_startup_warnings, run_apps_pre_check
from hassette.utils.service_utils import topological_levels, topological_sort, validate_dependency_graph, wait_for_ready
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
from .runtime_query_service import RuntimeQueryService
from .scheduler_service import SchedulerService
from .service_watcher import ServiceWatcher
from .session_manager import SessionManager
from .state_proxy import StateProxy
from .sync_executor import SyncExecutor
from .sync_executor_service import SyncExecutorService
from .telemetry.query_service import TelemetryQueryService
from .web_api_service import WebApiService
from .web_ui_watcher import WebUiWatcherService
from .websocket_service import WebsocketService

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable

    from hassette.events import AnyEvent

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

    def _should_skip_dependency_check(self) -> bool:
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
        # rebuild_pool() on both first start and restart-in-place.
        self._sync_executor = SyncExecutor()
        self.sync_executor = self._sync_executor

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
        self._service_watcher: ServiceWatcher | None = None
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

        # Fatal-exit observability: set by shutdown_if_crashed or startup-failure branches.
        # When set, run_forever() raises FatalError after teardown instead of returning normally.
        self._fatal_shutdown_reason: str | None = None

        # Work a deadline owner walked away from during this process's life (stage expiry, runtime
        # entry-deadline expiry, executor threads surviving the join). The `hassette run` path reads it
        # and hard-exits instead of letting the interpreter wait on that work.
        self._force_terminated_work: list[str] = []

        # Tier 1 loop-responsiveness watchdog — installed in run_forever(), torn down in before_shutdown().
        self._loop_watchdog: LoopWatchdog | None = None

    def startup_tasks(self) -> None:
        """Perform one-time startup tasks.

        These were originally on the `HassetteConfig` class but we do not want these called
        when the config is reloaded, only on initial startup.
        """
        # one time startup tasks
        if self.config.import_dot_env_files:
            for env_file in self.config.env_files:
                if env_file.exists():
                    self.logger.debug("Loading environment variables from %s", env_file)
                    load_dotenv(env_file)

        self.config.set_validated_app_manifests()

        config_files = sorted(self.config.toml_files | self.config.env_files)
        self.logger.info("Config files read: %s", ", ".join(map(str, config_files)) or "none", stacklevel=3)

        self.logger.info("Apps directory: %s", self.config.apps.directory, stacklevel=3)
        for warning in app_startup_warnings(self.config.apps, config_files=config_files, cwd=self.config.locations.cwd):
            self.logger.warning(warning, stacklevel=3)

        active_apps = [app for app in self.config.apps.manifests.values() if app.enabled]
        self.logger.info("Found %d active apps", len(active_apps), stacklevel=3)

        inactive_apps = [app for app in self.config.apps.manifests.values() if not app.enabled]
        if inactive_apps:
            self.logger.info("Found %d inactive apps", len(inactive_apps), stacklevel=3)

        try:
            run_apps_pre_check(self.config)
        except AppPrecheckFailedError:
            if not self.config.allow_startup_if_app_precheck_fails:
                self.logger.error("App precheck failed and startup is not allowed to continue. Raising exception.")
                raise
            self.logger.warning("App precheck failed, but startup will continue due to configuration setting.")

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

        self.startup_tasks()

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
        self._service_watcher = self.add_child(ServiceWatcher)
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
        validate_registries(STATE_REGISTRY, TYPE_REGISTRY, strict=self.config.strict_lifecycle)

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
        """Send an event to the event bus."""
        if self._event_stream_service is None:
            raise service_not_wired_error("EventStreamService")
        if self.event_streams_closed:
            self.logger.debug("send_event dropped: streams closed (topic=%s)", event.topic)
            return
        await self._event_stream_service.send_event(event)

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

        # on_initialize() and database_service.start() run AFTER the watchdog + Tier 2 guard are
        # installed but BEFORE the managed startup try below. A raise here would otherwise skip
        # before_shutdown(), leaking the watchdog daemon thread and the process-global monkeypatches
        # into the process. Route any failure through shutdown() so both detectors are torn down.
        try:
            await self.on_initialize()

            # Phase 1: Start database and create session before anything else.
            # This guarantees a valid session_id exists before any handler can fire.
            start(self.database_service)
        except Exception:
            self.logger.exception("Startup failed during initialization")
            self.record_fatal_reason("startup failure: initialization raised before service startup")
            await self.shutdown()
            self._raise_if_fatal_shutdown()
            return

        try:
            await self.wait_for_ready([self.database_service], timeout=self.config.lifecycle.startup_timeout_seconds)
            if self._session_manager is None:
                raise service_not_wired_error("SessionManager")
            await self._session_manager.mark_orphaned_sessions()
            await self._session_manager.create_session()
        except Exception:
            self.logger.exception("Failed to initialize session tracking")
            self.record_fatal_reason("startup failure: session tracking initialization failed")
            await self.shutdown()
            self._raise_if_fatal_shutdown()
            return

        # Phase 2: Start remaining children wave-by-wave.  Each wave's deps
        # are guaranteed ready before the wave begins, so _auto_wait_dependencies
        # returns immediately (kept as defense-in-depth for restarts).
        self.logger.debug("Waiting for resources to initialize...")
        self.ready_event.set()
        type_to_instance = {type(c): c for c in self.children}
        already_started: set[int] = {id(self.database_service)}

        for wave_types in self._init_waves:
            wave = [type_to_instance[t] for t in wave_types if t in type_to_instance]
            wave = [c for c in wave if id(c) not in already_started]
            if not wave:
                continue
            for child in wave:
                start(child)
            started = await self.wait_for_ready(wave, timeout=self.config.lifecycle.startup_timeout_seconds)
            if not started:
                if self.shutdown_event.is_set():
                    # Shutdown was requested while this wave was still starting — that is a
                    # shutdown, not a resource startup failure.  It happens when a clean/operator
                    # shutdown (or a crash that already recorded its reason) lands before the later
                    # waves finish, including the common case where a caller stops the instance
                    # right after readiness is signalled.  Route to teardown; _raise_if_fatal_shutdown
                    # raises only when a fatal reason was recorded, so a clean shutdown exits 0.
                    await self.shutdown()
                    self._raise_if_fatal_shutdown()
                    return
                not_ready = [r.class_name for r in wave if not r.is_ready()]
                self.logger.error("The following resources failed to start: %s", ", ".join(not_ready))
                self.logger.error("Not all resources started successfully, shutting down")
                self.record_fatal_reason(f"startup failure: required resources did not start: {', '.join(not_ready)}")
                await self.shutdown()
                self._raise_if_fatal_shutdown()
                return

        # Clean up stale once=True listeners from previous sessions. Safe to run here
        # because: (a) CommandExecutor is ready, (b) session_id is set, and (c) the
        # NOT EXISTS(... session_id = ?) guard prevents deletion of any listener that
        # has current-session invocations still in the write queue.
        await self._session_manager.cleanup_stale_once_listeners()

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

    @property
    def fatal_shutdown_reason(self) -> str | None:
        """The reason a fatal shutdown was triggered, or None for a clean shutdown (read-only)."""
        return self._fatal_shutdown_reason

    def record_fatal_reason(self, reason: str) -> None:
        """Record why a fatal shutdown is happening, so the process exits non-zero.

        Set synchronously at the crash decision site (before any teardown) so run_forever()
        observes it independent of async event dispatch. The first reason wins — the universal
        crash handler does not overwrite a more specific reason from the exhaustion/fatal-error path.
        """
        if self._fatal_shutdown_reason is None:
            self._fatal_shutdown_reason = reason

    @property
    def force_terminated_work(self) -> tuple[str, ...]:
        """What a shutdown deadline force-terminated or left running during this process's life (read-only)."""
        return tuple(self._force_terminated_work)

    @property
    def shutdown_snapshot_task(self) -> "asyncio.Task[bool] | None":
        """The database shutdown snapshot's copy, once the root started it (read-only)."""
        return self._database_service.shutdown_snapshot_task if self._database_service is not None else None

    def record_force_terminated(self, names: "Iterable[str]") -> None:
        """Record work a deadline owner walked away from, so the ``hassette run`` path hard-exits."""
        self._force_terminated_work.extend(names)

    def _raise_if_fatal_shutdown(self) -> None:
        """Raise FatalError (after a CRITICAL log) if a fatal reason was recorded.

        Called after teardown completes, at the two startup-failure branches and after the run loop.
        """
        if self._fatal_shutdown_reason is not None:
            self.logger.critical("Hassette terminated due to a fatal error: %s", self._fatal_shutdown_reason)
            raise FatalError(self._fatal_shutdown_reason)

    async def _shutdown_children(self) -> TeardownReport:
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
            stop_report = await self._run_stop_stage()
        finally:
            try:
                foundation_report = await self._run_foundation_stage()
            finally:
                if self._database_service is not None:
                    await self._database_service.write_shutdown_snapshot()
        return merge_teardown_reports(stop_report, foundation_report)

    def _foundation_services(self) -> list[Resource]:
        """The children the foundation stage stops, in its order: session, database, executor.

        Each sets ``shutdown_hook_timeout_applies = False``; a new foundation service needs both.
        """
        named = (self._session_manager, self._database_service, self._sync_executor_service)
        return [service for service in named if service is not None]

    async def _run_stop_stage(self) -> TeardownReport:
        """Stop every non-foundation child in dependency waves under the stop stage's deadline."""
        foundation = {id(service) for service in self._foundation_services()}
        type_to_instance = {type(c): c for c in self.children if id(c) not in foundation}
        waves = [
            [type_to_instance[t] for t in wave_types if t in type_to_instance]
            for wave_types in reversed(self._init_waves)
        ]
        waves = [wave for wave in waves if wave]
        stage_children = [child for wave in waves for child in wave]

        async def run_waves() -> TeardownReport:
            child_reports: list[TeardownReport] = []
            causes: list[TeardownCause] = []
            affected: list[str] = []
            for wave in waves:
                names = ", ".join(c.class_name for c in wave)
                self.logger.debug("Shutting down wave: [%s]", names)
                wave_start = asyncio.get_running_loop().time()
                result = await shutdown_batch(self, wave, deadline=self._shutdown_deadline)
                self.logger.debug("Shutdown wave [%s] completed in %.2fs", names, elapsed_since(wave_start))
                child_reports.extend(result.reports)
                causes.extend(result.causes)
                affected.extend(result.affected)
            return finalize_shutdown_report(child_reports, causes, affected)

        return await self._run_stage("stop", run_waves(), stage_children, deadline=self._shutdown_deadline)

    async def _run_foundation_stage(self) -> TeardownReport:
        """Finalize the session, then stop the database and the executor, under the fixed foundation budget.

        Runs even when the stop stage timed out, so the session record gets the fatal reason and the
        database drains and closes. Executor threads that survive the join are recorded as
        force-terminated work, since they would otherwise hold the process at interpreter exit.
        """
        deadline = deadline_in(FOUNDATION_SHUTDOWN_BUDGET_SECONDS)
        services = self._foundation_services()
        step = "session finalize"

        async def run_steps() -> TeardownReport:
            nonlocal step
            await self._finalize_session()
            reports: list[TeardownReport] = []
            causes: list[TeardownCause] = []
            affected: list[str] = []
            for service in services:
                step = f"{service.class_name} shutdown"
                result = await shutdown_batch(self, [service], deadline=deadline)
                reports.extend(result.reports)
                causes.extend(result.causes)
                affected.extend(result.affected)
            return finalize_shutdown_report(reports, causes, affected)

        report = await self._run_stage(
            "foundation", run_steps(), services, deadline=deadline, current_step=lambda: step
        )
        surviving = self._sync_executor.surviving_threads()
        if surviving:
            self.logger.error("Sync executor threads still running after the shutdown join: %s", ", ".join(surviving))
            self.record_force_terminated(f"thread {name}" for name in surviving)
        return report

    async def _run_stage(
        self,
        stage: str,
        work: "Coroutine[Any, Any, TeardownReport]",
        stage_children: list[Resource],
        *,
        deadline: float | None,
        current_step: "Callable[[], str] | None" = None,
    ) -> TeardownReport:
        """Run one exit stage, walking away from it when ``deadline`` passes.

        On expiry the stage's unfinished children are force-terminated (which also cancels their
        coordinators) and named in one ERROR, along with ``current_step()`` when given, and the stage's
        own task is cancelled without waiting for the cancellation to land. The other walk-away owner,
        ``AppLifecycleService.walk_away_from_instance()``, follows the same order: force-terminate, cancel,
        record.
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
        reports: list[TeardownReport] = []
        for child in unfinished:
            child._force_terminal()
            if (child_report := child.teardown_report) is not None:
                reports.append(child_report)
        self.record_force_terminated(child.unique_name for child in unfinished)
        task.cancel()
        return finalize_shutdown_report(
            reports, [TeardownCause.CHILD_SHUTDOWN_TIMED_OUT], [child.unique_name for child in unfinished]
        )

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

        Called by _finalize_shutdown() after all children have shut down cleanly.
        handle_stop() must run before close_streams() so Hassette's STOPPED event
        is delivered while streams are still open.

        On the timeout path, this hook is skipped — Hassette.shutdown()'s finally
        block handles both handle_stop() and close_streams() as a fallback.
        """
        await super()._on_children_stopped()
        await handle_stop(self)
        if self._event_stream_service is not None:
            await self._event_stream_service.close_streams()

    async def _shutdown_body(self) -> "TeardownReport":
        """Root shutdown body: the ordinary hooks/cleanup/children pipeline, with the root owning both
        exit stages' deadlines, then stream closing and terminal status.

        The root's own hooks, task-cancel and cleanup run under the stop stage's deadline
        (``total_shutdown_timeout_seconds`` minus the foundation budget); ``_shutdown_children()`` runs
        the stop stage under the same deadline and the foundation stage under its own. Nothing bounds
        the body as a whole: each stage's walk-away is the only place the root stops waiting.
        """
        self.logger.info("Hassette shutdown initiated", stacklevel=2)
        total = self.config.lifecycle.total_shutdown_timeout_seconds
        tighten_shutdown_deadline(self, deadline_in(total - FOUNDATION_SHUTDOWN_BUDGET_SECONDS))

        report: TeardownReport
        try:
            report = await super()._shutdown_body()
        finally:
            # Restore whatever task factory (if any) was installed before run_forever() set
            # its own -- an event loop that outlives this shutdown (an embedded caller, or a
            # test suite reusing the loop across cases) must not keep routing create_task()
            # through a closure over self.task_bucket, which is now permanently sealed.
            if self._loop is not None:
                # pyright ignore for the same apparent 3.11 stub issue as the set_task_factory()
                # call in run_forever() -- a plain callable/None argument is flagged there too.
                self._loop.set_task_factory(self._previous_task_factory)  # pyright: ignore[reportArgumentType]

            # Emit Hassette's own STOPPED event while streams are still open,
            # then close streams and set terminal status. Guarded by event_streams_closed
            # so the clean path (which already closed streams via _on_children_stopped())
            # does not double-close or double-emit.
            if not self.event_streams_closed:
                with suppress(Exception):
                    await handle_stop(self)
            if self._event_stream_service is not None:
                with suppress(OSError):
                    await self._event_stream_service.close_streams()
            if self.status != ResourceStatus.STOPPED:
                self.status = ResourceStatus.STOPPED
            mark_not_ready(self, "shutdown complete")

        return report

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
