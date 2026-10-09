import typing

from hassette.utils.url_utils import build_rest_url, build_ws_url

if typing.TYPE_CHECKING:
    import asyncio

    from hassette.api import Api
    from hassette.bus import Bus
    from hassette.config import HassetteConfig
    from hassette.conversion import StateRegistry, TypeRegistry
    from hassette.state_manager import StateManager

    from .api_resource import ApiResource
    from .app_bootstrap_coordinator import AppBootstrapCoordinator
    from .app_handler import AppHandler
    from .bus_service import BusService
    from .command_executor import CommandExecutor
    from .database_service import DatabaseService
    from .event_stream_service import EventStreamService
    from .logging_service import LoggingService
    from .runtime_query_service import RuntimeQueryService
    from .scheduler_service import SchedulerService
    from .session_manager import SessionManager
    from .state_proxy import StateProxy
    from .sync_executor_service import SyncExecutorService
    from .telemetry.query_service import TelemetryQueryService
    from .websocket_service import WebsocketService


def service_not_wired_error(service: str) -> RuntimeError:
    """Build the error raised when a service accessor is read before ``wire_services()`` ran.

    Names the missing service and the startup-ordering fix, so a premature read during
    construction (or a misordered embedding) is debuggable from the message alone.
    """
    return RuntimeError(
        f"{service} is unavailable: wire_services() has not been called. "
        "Construct Hassette(config), call wire_services(), then run_forever()."
    )


class HassetteAccessorsMixin:
    """Typed accessors for the services and runtime state ``Hassette`` wires up.

    Each service accessor raises ``RuntimeError`` (via ``service_not_wired_error``) when read
    before ``Hassette.wire_services()`` has populated its slot. The slots themselves are assigned
    in ``Hassette.__init__`` and ``wire_services()``; this mixin only reads them.
    """

    config: "HassetteConfig"
    _loop: "asyncio.AbstractEventLoop | None"
    _loop_thread_id: int | None
    _session_manager: "SessionManager | None"
    _event_stream_service: "EventStreamService | None"
    _sync_executor_service: "SyncExecutorService | None"
    _command_executor: "CommandExecutor | None"
    _logging_service: "LoggingService | None"
    _database_service: "DatabaseService | None"
    _runtime_query_service: "RuntimeQueryService | None"
    _telemetry_query_service: "TelemetryQueryService | None"
    _app_handler: "AppHandler | None"
    _app_bootstrap_coordinator: "AppBootstrapCoordinator | None"
    _websocket_service: "WebsocketService | None"
    _bus_service: "BusService | None"
    _bus: "Bus | None"
    _state_proxy: "StateProxy | None"
    _api_service: "ApiResource | None"
    _scheduler_service: "SchedulerService | None"
    _api: "Api | None"
    _states: "StateManager | None"
    _state_registry: "StateRegistry | None"
    _type_registry: "TypeRegistry | None"

    @property
    def session_id(self) -> int:
        """Return the current session ID.

        Raises:
            RuntimeError: If no session has been created.
        """
        return self.session_manager.session_id

    def try_session_id(self) -> int | None:
        """Return the current session ID, or None if no session exists yet."""
        try:
            return self.session_id
        except RuntimeError:
            return None

    @property
    def session_manager(self) -> "SessionManager":
        """SessionManager instance for session lifecycle management."""
        if self._session_manager is None:
            raise service_not_wired_error("SessionManager")
        return self._session_manager

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
    def event_stream_service(self) -> "EventStreamService":
        """EventStreamService instance for internal event stream lifecycle."""
        if self._event_stream_service is None:
            raise service_not_wired_error("EventStreamService")
        return self._event_stream_service

    @property
    def loop(self) -> "asyncio.AbstractEventLoop":
        """Get the current event loop."""
        if self._loop is None:
            raise RuntimeError("Event loop is not running")
        return self._loop

    @property
    def loop_thread_id(self) -> int | None:
        """Thread id of the event-loop thread, or None before run_forever() captures it.

        None is a valid return, not an error. Callers that compare a thread ident against
        this value treat None as "the loop thread is not running yet".
        """
        return self._loop_thread_id

    @property
    def sync_executor_service(self) -> "SyncExecutorService":
        """The SyncExecutorService instance that owns the dedicated sync thread pool."""
        if self._sync_executor_service is None:
            raise service_not_wired_error("SyncExecutorService")
        return self._sync_executor_service

    @property
    def command_executor(self) -> "CommandExecutor":
        """CommandExecutor for telemetry recording."""
        if self._command_executor is None:
            raise service_not_wired_error("CommandExecutor")
        return self._command_executor

    def get_drop_counters(self) -> tuple[int, int, int]:
        return self.command_executor.get_drop_counters()

    def get_error_handler_failures(self) -> int:
        return self.command_executor.get_error_handler_failures()

    def get_log_queue_drops(self) -> int:
        """Return the number of log records dropped because the log queue was full.

        Drops here mean ``logging.log_queue_max`` is too small for the current log volume.
        These records reached no handler at all, so they are missing from console output as
        well as the database.

        Returns:
            Cumulative count of dropped log records since process start.
        """
        if self._logging_service is None:
            return 0
        return self._logging_service.log_queue_drops

    def get_db_write_queue_drops(self) -> int:
        """Return the number of log records dropped because the DB write queue was full.

        Drops here mean ``database.write_queue_max`` is too small, or the persistence handler's
        queue was unavailable or closed. The records reached the persistence handler but were never
        written.

        Returns:
            Cumulative count of dropped log records since process start.
        """
        if self._logging_service is None:
            return 0
        return self._logging_service.db_write_queue_drops

    def is_log_persistence_active(self) -> bool:
        """Return whether log records are currently being persisted to the database.

        False before the logging service is wired, when its persistence handler failed to
        be created, and after the logging pipeline has shut down.
        """
        if self._logging_service is None:
            return False
        return self._logging_service.persistence_active

    @property
    def database_service(self) -> "DatabaseService":
        """DatabaseService instance for SQLite telemetry storage."""
        if self._database_service is None:
            raise service_not_wired_error("DatabaseService")
        return self._database_service

    @property
    def logging_service(self) -> "LoggingService":
        """LoggingService instance for the async logging pipeline."""
        if self._logging_service is None:
            raise service_not_wired_error("LoggingService")
        return self._logging_service

    @property
    def runtime_query_service(self) -> "RuntimeQueryService":
        """RuntimeQueryService instance for live in-memory state queries."""
        if self._runtime_query_service is None:
            raise service_not_wired_error("RuntimeQueryService")
        return self._runtime_query_service

    @property
    def telemetry_query_service(self) -> "TelemetryQueryService":
        """TelemetryQueryService instance for historical DB-backed telemetry queries."""
        if self._telemetry_query_service is None:
            raise service_not_wired_error("TelemetryQueryService")
        return self._telemetry_query_service

    @property
    def app_handler(self) -> "AppHandler":
        """AppHandler instance for app lifecycle management."""
        if self._app_handler is None:
            raise service_not_wired_error("AppHandler")
        return self._app_handler

    @property
    def app_bootstrap_coordinator(self) -> "AppBootstrapCoordinator":
        """AppBootstrapCoordinator instance for app-bootstrap release control."""
        if self._app_bootstrap_coordinator is None:
            raise service_not_wired_error("AppBootstrapCoordinator")
        return self._app_bootstrap_coordinator

    @property
    def websocket_service(self) -> "WebsocketService":
        """WebsocketService instance for HA WebSocket connection."""
        if self._websocket_service is None:
            raise service_not_wired_error("WebsocketService")
        return self._websocket_service

    @property
    def bus_service(self) -> "BusService":
        """BusService instance for event bus management."""
        if self._bus_service is None:
            raise service_not_wired_error("BusService")
        return self._bus_service

    @property
    def bus(self) -> "Bus":
        """Bus instance for internal event pub/sub."""
        if self._bus is None:
            raise service_not_wired_error("Bus")
        return self._bus

    @property
    def state_proxy(self) -> "StateProxy":
        """StateProxy instance for entity state caching."""
        if self._state_proxy is None:
            raise service_not_wired_error("StateProxy")
        return self._state_proxy

    def try_state_proxy(self) -> "StateProxy | None":
        """Return the StateProxy if wired, else None — for callers that tolerate its absence.

        Unlike the state_proxy property (which raises before wiring), this returns None so
        hot paths like BusService.read_entity_state skip silently during early startup
        instead of catching an exception.
        """
        return self._state_proxy

    @property
    def api_service(self) -> "ApiResource":
        """ApiResource instance for HA REST/WebSocket transport."""
        if self._api_service is None:
            raise service_not_wired_error("ApiResource")
        return self._api_service

    @property
    def scheduler_service(self) -> "SchedulerService":
        """SchedulerService instance for job scheduling."""
        if self._scheduler_service is None:
            raise service_not_wired_error("SchedulerService")
        return self._scheduler_service

    @property
    def api(self) -> "Api":
        """API service for handling HTTP requests."""
        if self._api is None:
            raise service_not_wired_error("Api")
        return self._api

    @property
    def states(self) -> "StateManager":
        """States manager instance for accessing Home Assistant states."""
        if self._states is None:
            raise service_not_wired_error("StateManager")
        return self._states

    @property
    def state_registry(self) -> "StateRegistry":
        """State registry for managing state class registrations and conversions."""
        if self._state_registry is None:
            raise service_not_wired_error("StateRegistry")
        return self._state_registry

    @property
    def type_registry(self) -> "TypeRegistry":
        """Type registry for managing state value type conversions."""
        if self._type_registry is None:
            raise service_not_wired_error("TypeRegistry")
        return self._type_registry
