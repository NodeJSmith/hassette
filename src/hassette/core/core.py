import asyncio
import threading
import typing
from contextlib import suppress
from typing import Any, ParamSpec, TypeVar, final

from dotenv import load_dotenv

from hassette import context
from hassette.api import Api
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.bus import Bus
from hassette.config import HassetteConfig
from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY, StateRegistry, TypeRegistry
from hassette.exceptions import AppPrecheckFailedError
from hassette.logging_ import enable_logging
from hassette.resources.base import Resource, Service
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.types.enums import ResourceStatus
from hassette.utils.app_utils import run_apps_pre_check
from hassette.utils.service_utils import topological_levels, topological_sort, validate_dependency_graph, wait_for_ready
from hassette.utils.url_utils import build_rest_url, build_ws_url

from .api_resource import ApiResource
from .app_handler import AppHandler
from .bus_service import BusService
from .command_executor import CommandExecutor
from .database_service import DatabaseService
from .event_stream_service import EventStreamService
from .file_watcher import FileWatcherService
from .runtime_query_service import RuntimeQueryService
from .scheduler_service import SchedulerService
from .service_watcher import ServiceWatcher
from .session_manager import SessionManager
from .state_proxy import StateProxy
from .telemetry_query_service import TelemetryQueryService
from .web_api_service import WebApiService
from .web_ui_watcher import WebUiWatcherService
from .websocket_service import WebsocketService

if typing.TYPE_CHECKING:
    from hassette.events import Event

P = ParamSpec("P")
R = TypeVar("R")

T = TypeVar("T", bound=Resource | Service)


class Hassette(Resource):
    """Main class for the Hassette application.

    This class initializes the Hassette instance, manages services, and provides access to the API,
    event bus, app handler, and other core components.
    """

    _api: Api | None
    _states: StateManager | None
    _state_registry: StateRegistry | None
    _type_registry: TypeRegistry | None

    @property
    def unique_name(self) -> str:
        return "Hassette"

    def _should_skip_dependency_check(self) -> bool:
        return False

    def __init__(self, config: HassetteConfig) -> None:
        self.config = config

        enable_logging(self.config.log_level, log_buffer_size=self.config.web_api_log_buffer_size)

        super().__init__(self, task_bucket=TaskBucket(self, parent=self), parent=self)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None

        # Service slot declarations — populated by wire_services()
        self._event_stream_service: EventStreamService | None = None
        self._database_service: DatabaseService | None = None
        self._command_executor: CommandExecutor | None = None
        self._bus_service: BusService | None = None
        self._scheduler_service: SchedulerService | None = None
        self._session_manager: SessionManager | None = None
        self._service_watcher: ServiceWatcher | None = None
        self._websocket_service: WebsocketService | None = None
        self._file_watcher: FileWatcherService | None = None
        self._web_ui_watcher: WebUiWatcherService | None = None
        self._app_handler: AppHandler | None = None
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

        active_apps = [app for app in self.config.app_manifests.values() if app.enabled]
        self.logger.info("Found %d active apps", len(active_apps), stacklevel=3)

        inactive_apps = [app for app in self.config.app_manifests.values() if not app.enabled]
        self.logger.info("Found %d inactive apps", len(inactive_apps), stacklevel=3)

        if self.config.run_app_precheck:
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
        self.logger.info("Starting Hassette...")

        # set context variables
        context.set_global_hassette(self)
        context.set_global_hassette_config(self.config)

        self.startup_tasks()

        # private background services — EventStreamService FIRST (BusService needs receive_stream at construction)
        self._event_stream_service = self.add_child(EventStreamService)
        self._database_service = self.add_child(DatabaseService)
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
        self._app_handler = self.add_child(AppHandler)

        self._api_service = self.add_child(ApiResource)
        self._state_proxy = self.add_child(StateProxy)

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
            self.logger.info("Resource dependency graph:\n%s", "\n".join(dep_lines))

        self.logger.info("All components registered...", stacklevel=2)

    @property
    def session_id(self) -> int:
        """Return the current session ID.

        Raises:
            RuntimeError: If no session has been created.
        """
        if self._session_manager is None:
            raise RuntimeError("wire_services() has not been called")
        return self._session_manager.session_id

    @property
    def ws_url(self) -> str:
        """Construct the WebSocket URL for Home Assistant."""
        return build_ws_url(self.config)

    @property
    def rest_url(self) -> str:
        """Construct the REST API URL for Home Assistant."""
        return build_rest_url(self.config)

    @property
    def event_streams_closed(self) -> bool:
        """Check if the event streams are closed."""
        if self._event_stream_service is None:
            return True
        return self._event_stream_service.event_streams_closed

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Get the current event loop."""
        if self._loop is None:
            raise RuntimeError("Event loop is not running")
        return self._loop

    @property
    def command_executor(self) -> CommandExecutor:
        """CommandExecutor for telemetry recording."""
        if self._command_executor is None:
            raise RuntimeError("wire_services() has not been called")
        return self._command_executor

    def get_drop_counters(self) -> tuple[int, int, int, int]:
        """Return (dropped_overflow, dropped_exhausted, dropped_no_session, dropped_shutdown) from the CommandExecutor.

        Returns:
            A tuple of counters where:
            - overflow_count: records dropped because the write queue was full.
            - exhausted_count: records dropped because max retries were exceeded.
            - no_session_count: records dropped because session_id was unavailable.
            - shutdown_count: records dropped during shutdown flush.
        """
        return self.command_executor.get_drop_counters()

    def get_error_handler_failures(self) -> int:
        """Return the count of user error handler invocations that raised or timed out."""
        return self.command_executor.get_error_handler_failures()

    @property
    def database_service(self) -> DatabaseService:
        """DatabaseService instance for SQLite telemetry storage."""
        if self._database_service is None:
            raise RuntimeError("wire_services() has not been called")
        return self._database_service

    @property
    def runtime_query_service(self) -> RuntimeQueryService:
        """RuntimeQueryService instance for live in-memory state queries."""
        if self._runtime_query_service is None:
            raise RuntimeError("wire_services() has not been called")
        return self._runtime_query_service

    @property
    def telemetry_query_service(self) -> TelemetryQueryService:
        """TelemetryQueryService instance for historical DB-backed telemetry queries."""
        if self._telemetry_query_service is None:
            raise RuntimeError("wire_services() has not been called")
        return self._telemetry_query_service

    @property
    def app_handler(self) -> AppHandler:
        """AppHandler instance for app lifecycle management."""
        if self._app_handler is None:
            raise RuntimeError("wire_services() has not been called")
        return self._app_handler

    @property
    def websocket_service(self) -> WebsocketService:
        """WebsocketService instance for HA WebSocket connection."""
        if self._websocket_service is None:
            raise RuntimeError("wire_services() has not been called")
        return self._websocket_service

    @property
    def bus_service(self) -> BusService:
        """BusService instance for event bus management."""
        if self._bus_service is None:
            raise RuntimeError("wire_services() has not been called")
        return self._bus_service

    @property
    def state_proxy(self) -> StateProxy:
        """StateProxy instance for entity state caching."""
        if self._state_proxy is None:
            raise RuntimeError("wire_services() has not been called")
        return self._state_proxy

    @property
    def scheduler_service(self) -> SchedulerService:
        """SchedulerService instance for job scheduling."""
        if self._scheduler_service is None:
            raise RuntimeError("wire_services() has not been called")
        return self._scheduler_service

    @property
    def api(self) -> Api:
        """API service for handling HTTP requests."""
        if self._api is None:
            raise RuntimeError("wire_services() has not been called")
        return self._api

    @property
    def states(self) -> StateManager:
        """States manager instance for accessing Home Assistant states."""
        if self._states is None:
            raise RuntimeError("wire_services() has not been called")
        return self._states

    @property
    def state_registry(self) -> StateRegistry:
        """State registry for managing state class registrations and conversions."""
        if self._state_registry is None:
            raise RuntimeError("wire_services() has not been called")
        return self._state_registry

    @property
    def type_registry(self) -> TypeRegistry:
        """Type registry for managing state value type conversions."""
        if self._type_registry is None:
            raise RuntimeError("wire_services() has not been called")
        return self._type_registry

    @property
    def apps(self) -> dict[str, dict[int, App[AppConfig]]]:
        """Get the currently loaded apps."""
        return self.app_handler.apps

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

    async def send_event(self, event_name: str, event: "Event[Any]") -> None:
        """Send an event to the event bus."""
        if self._event_stream_service is None:
            raise RuntimeError("wire_services() has not been called")
        await self._event_stream_service.send_event(event_name, event)

    async def wait_for_ready(self, resources: list[Resource] | Resource, timeout: float | None = None) -> bool:
        """Block until all dependent resources are ready or shutdown is requested.

        Args:
            resources: The resource(s) to wait for.
            timeout: The timeout for the wait operation.

        Returns:
            True if all resources are ready, False if shutdown is requested.
        """
        timeout = timeout if timeout is not None else self.config.startup_timeout_seconds

        return await wait_for_ready(resources, timeout=timeout, shutdown_event=self.shutdown_event)

    async def on_initialize(self) -> None:
        """Emit warnings for disabled global timeouts.

        Called once during startup after log infrastructure is running.
        """
        for field in ("scheduler_job_timeout_seconds", "event_handler_timeout_seconds"):
            if getattr(self.config, field) is None:
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

        # pyright ignore is to handle what seems like another 3.11 bug/type issue
        self.loop.set_task_factory(make_task_factory(self.task_bucket))  # pyright: ignore[reportArgumentType]

        await self.on_initialize()

        # Phase 1: Start database and create session before anything else.
        # This guarantees a valid session_id exists before any handler can fire.
        self.database_service.start()

        try:
            await self.wait_for_ready([self.database_service], timeout=self.config.startup_timeout_seconds)
            if self._session_manager is None:
                raise RuntimeError("wire_services() has not been called")
            await self._session_manager.mark_orphaned_sessions()
            await self._session_manager.create_session()
        except Exception:
            self.logger.exception("Failed to initialize session tracking")
            await self.shutdown()
            return

        # Phase 2: Start remaining children wave-by-wave.  Each wave's deps
        # are guaranteed ready before the wave begins, so _auto_wait_dependencies
        # returns immediately (kept as defense-in-depth for restarts).
        self.logger.info("Waiting for resources to initialize...")
        self.ready_event.set()
        type_to_instance = {type(c): c for c in self.children}
        already_started: set[int] = {id(self.database_service)}

        for wave_types in self._init_waves:
            wave = [type_to_instance[t] for t in wave_types if t in type_to_instance]
            wave = [c for c in wave if id(c) not in already_started]
            if not wave:
                continue
            for child in wave:
                child.start()
            started = await self.wait_for_ready(wave, timeout=self.config.startup_timeout_seconds)
            if not started:
                not_ready = [r.class_name for r in wave if not r.is_ready()]
                self.logger.error("The following resources failed to start: %s", ", ".join(not_ready))
                self.logger.error("Not all resources started successfully, shutting down")
                await self.shutdown()
                return

        try:
            await asyncio.wait_for(
                self.bus_service.drain_framework_registrations(),
                timeout=self.config.registration_await_timeout,
            )
        except TimeoutError:
            self.logger.warning(
                "drain_framework_registrations timed out after %ds — proceeding with startup",
                self.config.registration_await_timeout,
            )

        # Clean up stale once=True listeners from previous sessions. Safe to run here
        # because: (a) CommandExecutor is ready, (b) session_id is set, and (c) the
        # NOT EXISTS(... session_id = ?) guard prevents deletion of any listener that
        # has current-session invocations still in the write queue.
        if self._session_manager is None:
            raise RuntimeError("wire_services() has not been called")
        await self._session_manager.cleanup_stale_once_listeners()

        # does not take into consideration if apps failed to load, but those errors would have been logged already
        self.logger.info("All services started successfully.")
        self.logger.info("Hassette is running.")

        if self.shutdown_event.is_set():
            self.logger.warning("Hassette is shutting down, aborting run loop")
            await self.shutdown()

        try:
            await self.shutdown_event.wait()
        except asyncio.CancelledError:
            self.logger.debug("Hassette run loop cancelled")
        except Exception as e:
            self.logger.error("Error in Hassette run loop: %s", e)
        finally:
            await self.shutdown()

        self.logger.info("Hassette stopped.")

    async def _shutdown_children(self) -> bool:
        """Wave-based shutdown: gather each dependency level sequentially.

        Dependents (leaf services) shut down first, their dependencies last.
        Within each wave, services shut down concurrently via gather.
        """
        timeout = self.config.resource_shutdown_timeout_seconds
        type_to_instance = {type(c): c for c in self.children}

        for wave_types in reversed(self._init_waves):
            wave = [type_to_instance[t] for t in wave_types if t in type_to_instance]
            if not wave:
                continue
            self.logger.debug("Shutting down wave: [%s]", ", ".join(c.class_name for c in wave))
            try:
                async with asyncio.timeout(timeout):
                    results = await asyncio.gather(
                        *[child.shutdown() for child in wave],
                        return_exceptions=True,
                    )
                    for child, result in zip(wave, results, strict=True):
                        if isinstance(result, Exception):
                            self.logger.error("Child %s shutdown failed: %s", child.unique_name, result)
            except TimeoutError:
                self.logger.error(
                    "Shutdown wave [%s] timed out after %ss — forcing remaining children",
                    ", ".join(c.class_name for c in wave),
                    timeout,
                )
                for child in wave:
                    child._force_terminal()
                return False
        return True

    async def _on_children_stopped(self) -> None:
        """Emit Hassette's own STOPPED event, then close event streams.

        Called by _finalize_shutdown() after all children have shut down cleanly.
        handle_stop() must run before close_streams() so Hassette's STOPPED event
        is delivered while streams are still open.

        On the timeout path, this hook is skipped — Hassette.shutdown()'s finally
        block handles both handle_stop() and close_streams() as a fallback.
        """
        await super()._on_children_stopped()
        await self.handle_stop()
        if self._event_stream_service is not None:
            await self._event_stream_service.close_streams()

    @final
    async def shutdown(self) -> None:
        """Override to wrap the entire shutdown in a total timeout.

        FinalMeta exempts Hassette from the @final on Resource.shutdown().
        This ensures hooks + child propagation + cleanup all share one budget.
        """
        try:
            async with asyncio.timeout(self.config.total_shutdown_timeout_seconds):
                await super().shutdown()
        except TimeoutError:
            self.logger.critical(
                "Total shutdown timeout (%ss) exceeded — forcing termination",
                self.config.total_shutdown_timeout_seconds,
            )
            for child in self.children:
                child._force_terminal()
        finally:
            # _shutdown_completed FIRST — prevents re-entry regardless of what follows.
            self._shutdown_completed = True
            # Emit Hassette's own STOPPED event while streams are still open,
            # then close streams and set terminal status.
            if not self.event_streams_closed:
                with suppress(Exception):
                    await self.handle_stop()
            if self._event_stream_service is not None:
                with suppress(Exception):
                    await self._event_stream_service.close_streams()
            self.status = ResourceStatus.STOPPED
            self.mark_not_ready("shutdown complete")

    async def before_shutdown(self) -> None:
        """Remove bus listeners and finalize session before child shutdown."""
        try:
            if self._bus is not None:
                await self._bus.remove_all_listeners()
        except Exception:
            self.logger.exception("Failed to remove bus listeners during shutdown")
        finally:
            try:
                if self._command_executor is not None:
                    counters = self._command_executor.get_drop_counters()
                else:
                    counters = (0, 0, 0, 0)
            except Exception:
                counters = (0, 0, 0, 0)
            if self._session_manager is not None:
                await self._session_manager.finalize_session(drop_counters=counters)
