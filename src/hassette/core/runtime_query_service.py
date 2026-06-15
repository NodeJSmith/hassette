"""RuntimeQueryService: aggregates and caches live system state for the web UI."""

import asyncio
import contextlib
import json
import time
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from hassette.bus import Bus
from hassette.core.app_handler import AppHandler
from hassette.core.app_registry import AppFullSnapshot, AppStatusSnapshot
from hassette.core.bus_service import BusService
from hassette.core.domain_models import (
    AppStatusChangedData,
    BootIssue,
    ConnectivityData,
    ServiceInfo,
    ServiceStatusData,
    StateChangedData,
    SystemStatus,
)
from hassette.core.logging_service import LoggingService
from hassette.core.state_proxy import StateProxy
from hassette.events import Event, RawStateChangeEvent
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from hassette.types.types import LOG_LEVEL_TYPE

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events.hassette import ExecutionCompletedPayload

_WS_CLIENT_QUEUE_MAX = 256
_WS_DROP_LOG_INTERVAL = 10.0


class RuntimeQueryService(Resource):
    """Aggregates and caches live system state for the web UI.

    Reads from in-memory sources: AppHandler, event buffer, log buffer, WS clients.
    All reads are instant — no database I/O. LoggingService is in depends_on to
    guarantee the capture handler is ready before WS broadcast wiring runs.
    """

    depends_on: ClassVar[list[type[Resource]]] = [BusService, StateProxy, AppHandler, LoggingService]

    bus: Bus
    _event_buffer: deque[dict[str, Any]]
    _ws_clients: set[asyncio.Queue[dict[str, Any] | None]]
    _lock: asyncio.Lock
    _start_time: float
    _subscriptions: "list[Subscription]"

    _pending_completions: list[dict]
    """Execution completion dicts (handler and job) accumulated within the current drain tick, flushed as a batch."""

    _flush_scheduled: bool
    """True when an asyncio.sleep(0) flush has been scheduled for the current tick."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.bus = self.add_child(Bus)
        self._event_buffer = deque(maxlen=hassette.config.web_api.event_buffer_size)
        self._ws_clients: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._lock = asyncio.Lock()
        self._ws_drops: int = 0
        self._ws_drops_since_last_log: int = 0
        self._ws_drops_last_logged: float = 0.0
        self._start_time = time.time()
        self._subscriptions = []
        self._pending_completions: list[dict] = []
        self._flush_scheduled = False

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.web_api

    async def on_initialize(self) -> None:
        if not self.hassette.config.web_api.run:
            self.mark_ready(reason="Web API disabled")
            return

        # BusService, StateProxy, and AppHandler are guaranteed ready by depends_on auto-wait.

        # Subscribe to bus events
        self._subscriptions.append(
            await self.bus.on(
                topic=Topic.HASS_EVENT_STATE_CHANGED,
                handler=self.on_state_change,
                name="hassette.rqs.on_state_change",
            )
        )
        self._subscriptions.append(
            await self.bus.on_app_state_changed(
                handler=self.on_app_state_changed, name="hassette.rqs.on_app_state_changed"
            )
        )
        self._subscriptions.append(
            await self.bus.on(
                topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
                handler=self.on_service_status,
                name="hassette.rqs.on_service_status",
            )
        )
        self._subscriptions.append(
            await self.bus.on_websocket_connected(handler=self.on_ws_connected, name="hassette.rqs.on_ws_connected")
        )
        self._subscriptions.append(
            await self.bus.on_websocket_disconnected(
                handler=self.on_ws_disconnected, name="hassette.rqs.on_ws_disconnected"
            )
        )
        self._subscriptions.append(
            await self.bus.on(
                topic=Topic.HASSETTE_EVENT_EXECUTION_COMPLETED,
                handler=self.on_execution_completed,
                name="hassette.rqs.on_execution_completed",
            )
        )

        # Wire up log capture handler for WS broadcast
        handler = self.hassette.logging_service.capture_handler
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

    async def buffer_and_broadcast(self, event_type: str, payload: BaseModel) -> None:
        entry: dict[str, Any] = {"type": event_type, "data": payload.model_dump(), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def on_state_change(self, event: RawStateChangeEvent) -> None:
        payload = StateChangedData(
            entity_id=event.payload.data.entity_id,
            new_state=dict(event.payload.data.new_state) if event.payload.data.new_state else None,
            old_state=dict(event.payload.data.old_state) if event.payload.data.old_state else None,
        )
        await self.buffer_and_broadcast("state_changed", payload)

    async def on_app_state_changed(self, event: Event) -> None:
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
        await self.buffer_and_broadcast("app_status_changed", payload)

    async def on_service_status(self, event: Event[Any]) -> None:
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
        await self.buffer_and_broadcast("service_status", payload)

    async def on_ws_connected(self) -> None:
        await self.buffer_and_broadcast("connectivity", ConnectivityData(connected=True))

    async def on_ws_disconnected(self) -> None:
        await self.buffer_and_broadcast("connectivity", ConnectivityData(connected=False))

    async def on_execution_completed(self, event: Event[Any]) -> None:
        """Accumulate an execution completion (handler or job) into the pending batch for this drain tick."""
        data: ExecutionCompletedPayload = event.payload.data
        self._pending_completions.append(
            {
                "kind": data.kind,
                "app_key": data.app_key,
                "instance_index": data.instance_index,
                "status": data.status,
                "duration_ms": data.duration_ms,
                "error_type": data.error_type,
                "listener_id": data.listener_id,
                "job_id": data.job_id,
            }
        )
        await self.schedule_flush()

    async def schedule_flush(self) -> None:
        """Schedule a single flush task for the current event-loop tick if not already scheduled.

        All completion events arriving within the same drain cycle are collected in
        ``_pending_completions`` before a single WS message is broadcast -
        one message per ``drain_and_persist()`` cycle, not one per record.
        """
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        self.task_bucket.spawn(self.flush_completions(), name="rqs:flush_completions")

    async def flush_completions(self) -> None:
        """Broadcast a single ``execution_completed`` WS message for the current drain tick.

        All handler and job completions accumulated in ``_pending_completions`` are
        emitted as one batched message. The ``kind`` field on each item discriminates
        handler invocations from job executions. One message per ``drain_and_persist()``
        cycle, not one per record.
        """
        # Reset BEFORE the awaits so new events arriving during broadcast land in
        # the fresh pending list and schedule_flush re-arms correctly.
        self._flush_scheduled = False
        now = time.time()

        completions = self._pending_completions
        self._pending_completions = []

        if completions:
            entry = {"type": "execution_completed", "data": completions, "timestamp": now}
            self._event_buffer.append(entry)
            await self.broadcast(entry)

    def get_app_status_snapshot(self) -> AppStatusSnapshot:
        return self.hassette.app_handler.get_status_snapshot()

    def get_all_manifests_snapshot(self) -> AppFullSnapshot:
        """Return full manifest-based snapshot including stopped/disabled apps."""
        return self.hassette.app_handler.registry.get_full_snapshot()

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        events = list(self._event_buffer)
        return events[-limit:]

    def get_system_status(self) -> SystemStatus:
        ws = self.hassette.websocket_service
        ws_connected = ws.is_ready()
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

        services = [
            ServiceInfo(
                name=child.class_name,
                status=child.status.value if hasattr(child, "status") else "unknown",
                role=child.role.value if hasattr(child, "role") and hasattr(child.role, "value") else "",
                ready_phase=getattr(child, "_ready_reason", None),
                retry_at=getattr(child, "_retry_at", None),
            )
            for child in self.hassette.children
            if hasattr(child, "status")
        ]
        services_running = [s.name for s in services if s.status == ResourceStatus.RUNNING.value]

        if ws_connected:
            status = "ok"
        elif ws.ever_connected:
            status = "degraded"
        else:
            status = "starting"

        boot_issues = self.collect_boot_issues()

        return SystemStatus(
            status=status,
            websocket_connected=ws_connected,
            uptime_seconds=uptime,
            entity_count=entity_count,
            app_count=app_count,
            services_running=services_running,
            services=services,
            boot_issues=boot_issues,
            log_records_dropped=self.hassette.get_log_records_dropped(),
        )

    def collect_boot_issues(self) -> list[BootIssue]:
        """Collect boot-time issues from blocked apps and failed app instances.

        Returns a list of ``BootIssue`` objects derived from:
        - Apps that are blocked (e.g. import error, pre-check failure) — severity ``warn``
        - Apps that failed to start — severity ``err``
        """
        issues: list[BootIssue] = []
        try:
            full_snapshot = self.hassette.app_handler.registry.get_full_snapshot()
        except (AttributeError, RuntimeError):
            return issues

        for manifest in full_snapshot.manifests:
            if manifest.status == "blocked" and manifest.block_reason:
                issues.append(
                    BootIssue(
                        severity="warn",
                        label=f"App blocked: {manifest.display_name}",
                        detail=manifest.block_reason,
                    )
                )
            elif manifest.status == "failed" and manifest.error_message:
                issues.append(
                    BootIssue(
                        severity="err",
                        label=f"App failed: {manifest.display_name}",
                        detail=manifest.error_message,
                    )
                )

        return issues

    async def register_ws_client(self) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_WS_CLIENT_QUEUE_MAX)
        async with self._lock:
            self._ws_clients.add(queue)
        self.logger.debug("WebSocket client registered (total: %d)", len(self._ws_clients))
        return queue

    async def unregister_ws_client(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
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
                    if now - self._ws_drops_last_logged >= _WS_DROP_LOG_INTERVAL:
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
