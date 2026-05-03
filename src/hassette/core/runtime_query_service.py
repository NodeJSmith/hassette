"""RuntimeQueryService: aggregates and caches live system state for the web UI."""

import asyncio
import contextlib
import json
import time
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar

from hassette.bus import Bus
from hassette.core.app_handler import AppHandler
from hassette.core.app_registry import AppFullSnapshot, AppStatusSnapshot
from hassette.core.bus_service import BusService
from hassette.core.domain_models import (
    AppStatusChangedData,
    ConnectivityData,
    ServiceStatusData,
    StateChangedData,
    SystemStatus,
)
from hassette.core.state_proxy import StateProxy
from hassette.events import Event, RawStateChangeEvent
from hassette.logging_ import LogEntry, get_log_capture_handler
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from hassette.types.types import LOG_LEVEL_TYPE

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events.hassette import ExecutionCompletedPayload, InvocationCompletedPayload

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class RuntimeQueryService(Resource):
    """Aggregates and caches live system state for the web UI.

    Reads from in-memory sources: AppHandler, event buffer, log buffer, WS clients.
    All reads are instant — no database I/O.
    """

    depends_on: ClassVar[list[type[Resource]]] = [BusService, StateProxy, AppHandler]

    bus: Bus
    _event_buffer: deque[dict]
    _ws_clients: set[asyncio.Queue]
    _lock: asyncio.Lock
    _start_time: float
    _subscriptions: "list[Subscription]"

    _listener_meta: dict[int, tuple[str, int]]
    """Maps listener DB-ID → (app_key, instance_index) for completion event enrichment.

    Populated by :meth:`register_listener_meta` (called from ``CommandExecutor`` at
    registration time).  Stale entries are pruned by :meth:`prune_meta` during
    reconciliation after app reloads.
    """

    _job_meta: dict[int, tuple[str, int]]
    """Maps job DB-ID → (app_key, instance_index) for completion event enrichment."""

    _pending_invocations: list[dict]
    """Invocation completion dicts accumulated within the current drain tick, flushed as a batch."""

    _pending_executions: list[dict]
    """Execution completion dicts accumulated within the current drain tick, flushed as a batch."""

    _flush_scheduled: bool
    """True when an asyncio.sleep(0) flush has been scheduled for the current tick."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.bus = self.add_child(Bus)
        self._event_buffer = deque(maxlen=hassette.config.web_api_event_buffer_size)
        self._ws_clients: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._ws_drops: int = 0
        self._ws_drops_since_last_log: int = 0
        self._ws_drops_last_logged: float = 0.0
        self._start_time = time.time()
        self._subscriptions = []
        self._listener_meta: dict[int, tuple[str, int]] = {}
        self._job_meta: dict[int, tuple[str, int]] = {}
        self._pending_invocations: list[dict] = []
        self._pending_executions: list[dict] = []
        self._flush_scheduled = False

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.web_api_log_level

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
            self.mark_ready(reason="Web API disabled")
            return

        # BusService, StateProxy, and AppHandler are guaranteed ready by depends_on auto-wait.

        # Subscribe to bus events
        self._subscriptions.append(
            self.bus.on(
                topic=Topic.HASS_EVENT_STATE_CHANGED,
                handler=self._on_state_change,
            )
        )
        self._subscriptions.append(self.bus.on_app_state_changed(handler=self._on_app_state_changed))
        self._subscriptions.append(
            self.bus.on(
                topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
                handler=self._on_service_status,
            )
        )
        self._subscriptions.append(self.bus.on_websocket_connected(handler=self._on_ws_connected))
        self._subscriptions.append(self.bus.on_websocket_disconnected(handler=self._on_ws_disconnected))
        self._subscriptions.append(
            self.bus.on(
                topic=Topic.HASSETTE_EVENT_INVOCATION_COMPLETED,
                handler=self._on_invocation_completed,
            )
        )
        self._subscriptions.append(
            self.bus.on(
                topic=Topic.HASSETTE_EVENT_EXECUTION_COMPLETED,
                handler=self._on_execution_completed,
            )
        )

        # Wire up log capture handler for WS broadcast
        handler = get_log_capture_handler()
        if handler is not None:
            try:
                loop = asyncio.get_running_loop()
                handler.set_broadcast(self.broadcast, loop)
            except RuntimeError:
                self.logger.warning("No running event loop, log broadcast will not be available")

        self.mark_ready(reason="RuntimeQueryService initialized")

    async def on_shutdown(self) -> None:
        # Remove bus listeners
        for sub in self._subscriptions:
            sub.cancel()
        self._subscriptions.clear()

        # Close all WS client queues
        async with self._lock:
            for queue in self._ws_clients:
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(None)  # sentinel to close
            self._ws_clients.clear()

        self._event_buffer.clear()
        self._ws_drops = 0
        self._ws_drops_since_last_log = 0
        self._ws_drops_last_logged = 0.0

    # --- Event handlers ---

    async def _on_state_change(self, event: RawStateChangeEvent) -> None:
        payload = StateChangedData(
            entity_id=event.payload.data.entity_id,
            new_state=dict(event.payload.data.new_state) if event.payload.data.new_state else None,
            old_state=dict(event.payload.data.old_state) if event.payload.data.old_state else None,
        )
        entry = {"type": "state_changed", "data": payload.model_dump(), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_app_state_changed(self, event: Event) -> None:
        if not hasattr(event, "payload"):
            return
        data = event.payload.data
        payload = AppStatusChangedData(
            app_key=data.app_key,
            index=data.index,
            status=data.status.value,
            previous_status=data.previous_status.value if data.previous_status else None,
            instance_name=data.instance_name,
            class_name=data.class_name,
            exception=data.exception,
            exception_type=data.exception_type,
            exception_traceback=data.exception_traceback,
        )
        entry = {"type": "app_status_changed", "data": payload.model_dump(), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_service_status(self, event: Event[Any]) -> None:
        if not hasattr(event, "payload"):
            return
        data = event.payload.data
        payload = ServiceStatusData(
            resource_name=data.resource_name,
            role=data.role.value,
            status=data.status.value,
            previous_status=data.previous_status.value if data.previous_status else None,
            exception=data.exception,
            exception_type=data.exception_type,
            exception_traceback=data.exception_traceback,
            retry_at=data.retry_at,
            ready=data.ready,
            ready_phase=data.ready_phase,
        )
        entry = {"type": "service_status", "data": payload.model_dump(), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_ws_connected(self) -> None:
        payload = ConnectivityData(connected=True)
        entry = {"type": "connectivity", "data": payload.model_dump(), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_ws_disconnected(self) -> None:
        payload = ConnectivityData(connected=False)
        entry = {"type": "connectivity", "data": payload.model_dump(), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_invocation_completed(self, event: Event[Any]) -> None:
        """Accumulate an invocation completion into the pending batch for this drain tick."""
        if not hasattr(event, "payload"):
            return
        data: InvocationCompletedPayload = event.payload.data
        lid = data.listener_id if data.listener_id is not None else 0
        app_key, instance_index = self._listener_meta.get(lid, ("", 0))
        self._pending_invocations.append(
            {
                "listener_id": lid,
                "app_key": app_key,
                "instance_index": instance_index,
                "status": data.status,
                "duration_ms": data.duration_ms,
                "error_type": data.error_type,
            }
        )
        await self._schedule_flush()

    async def _on_execution_completed(self, event: Event[Any]) -> None:
        """Accumulate a job execution completion into the pending batch for this drain tick."""
        if not hasattr(event, "payload"):
            return
        data: ExecutionCompletedPayload = event.payload.data
        jid = data.job_id if data.job_id is not None else 0
        app_key, instance_index = self._job_meta.get(jid, ("", 0))
        self._pending_executions.append(
            {
                "job_id": jid,
                "app_key": app_key,
                "instance_index": instance_index,
                "status": data.status,
                "duration_ms": data.duration_ms,
                "error_type": data.error_type,
            }
        )
        await self._schedule_flush()

    async def _schedule_flush(self) -> None:
        """Schedule a single flush task for the current event-loop tick if not already scheduled.

        All completion events arriving within the same drain cycle are collected in
        ``_pending_invocations`` / ``_pending_executions`` before a single WS message
        is broadcast — one message per ``_drain_and_persist()`` cycle, not one per record.
        """
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        self.task_bucket.spawn(self._flush_completions(), name="rqs:flush_completions")

    async def _flush_completions(self) -> None:
        """Broadcast one WS message per type summarising all completions from the current drain tick.

        Emits an ``invocation_completed`` message (with a list payload) if any invocations are
        pending, and an ``execution_completed`` message if any executions are pending.  Each
        covers the full set persisted in one ``_drain_and_persist()`` cycle — one message per
        drain, not one message per record.
        """
        # Reset BEFORE the awaits so new events arriving during broadcast land in
        # the fresh pending lists and _schedule_flush re-arms correctly.
        self._flush_scheduled = False
        now = time.time()

        invocations = self._pending_invocations
        executions = self._pending_executions
        self._pending_invocations = []
        self._pending_executions = []

        if invocations:
            entry = {"type": "invocation_completed", "data": invocations, "timestamp": now}
            self._event_buffer.append(entry)
            await self.broadcast(entry)

        if executions:
            entry = {"type": "execution_completed", "data": executions, "timestamp": now}
            self._event_buffer.append(entry)
            await self.broadcast(entry)

    # --- Listener/job meta registration ---

    def register_listener_meta(self, listener_db_id: int, app_key: str, instance_index: int) -> None:
        """Record the (app_key, instance_index) for a newly registered listener DB row.

        Called by ``CommandExecutor.register_listener`` immediately after the DB insert so that
        ``RuntimeQueryService`` can enrich completion WS messages with app identity without the
        ``CommandExecutor`` needing to know about the web layer.

        Args:
            listener_db_id: The ``id`` of the newly inserted ``listeners`` row.
            app_key: The app key that owns this listener.
            instance_index: The instance index within the app.
        """
        self._listener_meta[listener_db_id] = (app_key, instance_index)

    def register_job_meta(self, job_db_id: int, app_key: str, instance_index: int) -> None:
        """Record the (app_key, instance_index) for a newly registered scheduled job DB row.

        Called by ``CommandExecutor.register_job`` immediately after the DB insert so that
        ``RuntimeQueryService`` can enrich completion WS messages with app identity.

        Args:
            job_db_id: The ``id`` of the newly inserted ``scheduled_jobs`` row.
            app_key: The app key that owns this job.
            instance_index: The instance index within the app.
        """
        self._job_meta[job_db_id] = (app_key, instance_index)

    def prune_meta(self, live_listener_ids: set[int], live_job_ids: set[int]) -> None:
        """Remove stale entries from the meta dicts after reconciliation."""
        self._listener_meta = {k: v for k, v in self._listener_meta.items() if k in live_listener_ids}
        self._job_meta = {k: v for k, v in self._job_meta.items() if k in live_job_ids}

    # --- App status ---

    def get_app_status_snapshot(self) -> AppStatusSnapshot:
        return self.hassette.app_handler.get_status_snapshot()

    def get_all_manifests_snapshot(self) -> AppFullSnapshot:
        """Return full manifest-based snapshot including stopped/disabled apps."""
        return self.hassette.app_handler.registry.get_full_snapshot()

    # --- Event history ---

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        events = list(self._event_buffer)
        return events[-limit:]

    # --- Log access ---

    def get_recent_logs(self, limit: int = 100, app_key: str | None = None, level: str | None = None) -> list[dict]:
        handler = get_log_capture_handler()
        if handler is None:
            return []

        entries: list[LogEntry] = handler.get_buffer_snapshot()

        if app_key:
            entries = [e for e in entries if e.app_key == app_key]

        if level:
            min_level = LOG_LEVELS.get(level.upper(), 0)
            entries = [e for e in entries if LOG_LEVELS.get(e.level, 0) >= min_level]

        return [e.to_dict() for e in entries[-limit:]]

    # --- System status ---

    def get_system_status(self) -> SystemStatus:
        ws_connected = self.hassette.websocket_service.is_ready()
        uptime = time.time() - self._start_time

        try:
            entity_count = len(self.hassette.state_proxy.states)
        except (AttributeError, RuntimeError):
            entity_count = 0

        try:
            snapshot = self.hassette.app_handler.get_status_snapshot()
            app_count = snapshot.total_count
        except (AttributeError, RuntimeError):
            app_count = 0

        services_running = [
            child.class_name
            for child in self.hassette.children
            if hasattr(child, "status") and child.status == ResourceStatus.RUNNING
        ]

        try:
            proxy_ready = self.hassette.state_proxy.is_ready()
        except (AttributeError, RuntimeError):
            proxy_ready = False

        if ws_connected:
            status = "ok"
        elif proxy_ready:
            status = "degraded"
        else:
            status = "starting"

        return SystemStatus(
            status=status,
            websocket_connected=ws_connected,
            uptime_seconds=uptime,
            entity_count=entity_count,
            app_count=app_count,
            services_running=services_running,
        )

    # --- WebSocket client management ---

    async def register_ws_client(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._ws_clients.add(queue)
        self.logger.debug("WebSocket client registered (total: %d)", len(self._ws_clients))
        return queue

    async def unregister_ws_client(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._ws_clients.discard(queue)
            count = len(self._ws_clients)
        self.logger.debug("WebSocket client unregistered (total: %d)", count)

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected WebSocket clients."""
        # Pre-serialize once for all clients (handles enums, dataclasses, etc.)
        safe_message = json.loads(json.dumps(message, default=str))
        should_log = False
        log_since: int = 0
        log_total: int = 0
        log_clients: int = 0
        async with self._lock:
            for queue in self._ws_clients:
                try:
                    queue.put_nowait(safe_message)
                except asyncio.QueueFull:
                    self._ws_drops += 1
                    self._ws_drops_since_last_log += 1
                    now = time.monotonic()
                    if now - self._ws_drops_last_logged >= 10.0:
                        should_log = True
                        log_since = self._ws_drops_since_last_log
                        log_total = self._ws_drops
                        log_clients = len(self._ws_clients)
                        self._ws_drops_since_last_log = 0
                        self._ws_drops_last_logged = now
        if should_log:
            self.logger.warning(
                "Dropped %d messages since last log (total: %d, clients: %d)",
                log_since,
                log_total,
                log_clients,
            )
