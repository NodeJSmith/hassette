"""DataSyncService: aggregates and caches system state for the web UI."""

import asyncio
import contextlib
import logging
import time
import typing
from collections import deque
from dataclasses import asdict

from hassette.bus import Bus
from hassette.events import Event, RawStateChangeEvent
from hassette.logging_ import LogEntry, get_log_capture_handler
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from hassette.web.models import (
    AppInstanceResponse,
    AppStatusResponse,
    BusMetricsSummaryResponse,
    SystemStatusResponse,
)

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events import HassStateDict

LOGGER = logging.getLogger(__name__)

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class DataSyncService(Resource):
    """Aggregates and caches system state for the web UI.

    Single source of truth that FastAPI endpoints query.
    """

    bus: Bus
    _event_buffer: deque[dict]
    _ws_clients: set[asyncio.Queue]
    _lock: asyncio.Lock
    _start_time: float
    _subscriptions: "list[Subscription]"

    @classmethod
    def create(cls, hassette: "Hassette", parent: Resource):
        inst = cls(hassette=hassette, parent=parent)
        inst.bus = inst.add_child(Bus)
        inst._event_buffer = deque(maxlen=hassette.config.web_api_event_buffer_size)
        inst._ws_clients = set()
        inst._lock = asyncio.Lock()
        inst._start_time = time.time()
        inst._subscriptions = []
        return inst

    @property
    def config_log_level(self):
        return self.hassette.config.web_api_log_level

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
            self.mark_ready(reason="Web API disabled")
            return

        # Wait for dependencies
        await self.hassette.wait_for_ready(
            [
                self.hassette._bus_service,
                self.hassette._state_proxy,
                self.hassette._app_handler,
            ]
        )

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

        # Wire up log capture handler for WS broadcast
        handler = get_log_capture_handler()
        if handler is not None:
            try:
                loop = asyncio.get_running_loop()
                handler.set_broadcast(self.broadcast, loop)
            except RuntimeError:
                self.logger.warning("No running event loop, log broadcast will not be available")

        self.mark_ready(reason="DataSyncService initialized")

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

    # --- Event handlers ---

    async def _on_state_change(self, event: RawStateChangeEvent) -> None:
        entry = {
            "type": "state_changed",
            "entity_id": event.payload.data.entity_id,
            "new_state": event.payload.data.new_state,
            "old_state": event.payload.data.old_state,
            "timestamp": time.time(),
        }
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_app_state_changed(self, event: Event) -> None:
        entry = {
            "type": "app_status_changed",
            "data": event.payload.data if hasattr(event, "payload") else {},
            "timestamp": time.time(),
        }
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_service_status(self, event: Event) -> None:
        entry = {
            "type": "service_status",
            "data": event.payload.data if hasattr(event, "payload") else {},
            "timestamp": time.time(),
        }
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_ws_connected(self) -> None:
        entry = {
            "type": "connectivity",
            "data": {"connected": True},
            "timestamp": time.time(),
        }
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_ws_disconnected(self) -> None:
        entry = {
            "type": "connectivity",
            "data": {"connected": False},
            "timestamp": time.time(),
        }
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    # --- Entity state access (delegates to StateProxy) ---

    def get_entity_state(self, entity_id: str) -> "HassStateDict | None":
        return self.hassette._state_proxy.get_state(entity_id)

    def get_all_entity_states(self) -> "dict[str, HassStateDict]":
        return dict(self.hassette._state_proxy.states)

    def get_domain_states(self, domain: str) -> "dict[str, HassStateDict]":
        return self.hassette._state_proxy.get_domain_states(domain)

    # --- App status ---

    def get_app_status_snapshot(self) -> AppStatusResponse:
        snapshot = self.hassette._app_handler.get_status_snapshot()
        apps = [
            AppInstanceResponse(
                app_key=info.app_key,
                index=info.index,
                instance_name=info.instance_name,
                class_name=info.class_name,
                status=info.status.value,
                error_message=info.error_message,
            )
            for info in (*snapshot.running, *snapshot.failed)
        ]
        return AppStatusResponse(
            total=snapshot.total_count,
            running=snapshot.running_count,
            failed=snapshot.failed_count,
            apps=apps,
            only_app=snapshot.only_app,
        )

    # --- Event history ---

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        events = list(self._event_buffer)
        return events[-limit:]

    # --- Log access ---

    def get_recent_logs(self, limit: int = 100, app_key: str | None = None, level: str | None = None) -> list[dict]:
        handler = get_log_capture_handler()
        if handler is None:
            return []

        entries: list[LogEntry] = list(handler.buffer)

        if app_key:
            entries = [e for e in entries if e.app_key == app_key]

        if level:
            min_level = LOG_LEVELS.get(level.upper(), 0)
            entries = [e for e in entries if LOG_LEVELS.get(e.level, 0) >= min_level]

        return [e.to_dict() for e in entries[-limit:]]

    # --- Scheduler access ---

    async def get_scheduled_jobs(self, owner: str | None = None) -> list[dict]:
        """Return all scheduled jobs across all apps, sorted by next_run."""
        jobs = await self.hassette._scheduler_service.get_all_jobs()
        result = [
            {
                "job_id": job.job_id,
                "name": job.name,
                "owner": job.owner,
                "next_run": str(job.next_run),
                "repeat": job.repeat,
                "cancelled": job.cancelled,
                "trigger_type": type(job.trigger).__name__ if job.trigger else "once",
                "timeout_seconds": job.timeout_seconds,
            }
            for job in sorted(jobs, key=lambda j: j.next_run)
        ]
        if owner:
            result = [j for j in result if j["owner"] == owner]
        return result

    def get_job_execution_history(self, limit: int = 50, owner: str | None = None) -> list[dict]:
        records = self.hassette._scheduler_service.get_execution_history(limit, owner)
        return [asdict(r) for r in records]

    # --- System status ---

    def get_system_status(self) -> SystemStatusResponse:
        ws_connected = self.hassette._websocket_service.status == ResourceStatus.RUNNING
        uptime = time.time() - self._start_time

        try:
            entity_count = len(self.hassette._state_proxy.states)
        except Exception:
            entity_count = 0

        try:
            snapshot = self.hassette._app_handler.get_status_snapshot()
            app_count = snapshot.total_count
        except Exception:
            app_count = 0

        services_running = [
            child.class_name
            for child in self.hassette.children
            if hasattr(child, "status") and child.status == ResourceStatus.RUNNING
        ]

        if ws_connected:
            status = "ok"
        elif self.hassette._state_proxy.is_ready():
            status = "degraded"
        else:
            status = "starting"

        return SystemStatusResponse(
            status=status,
            websocket_connected=ws_connected,
            uptime_seconds=uptime,
            entity_count=entity_count,
            app_count=app_count,
            services_running=services_running,
        )

    # --- Bus listener metrics ---

    def get_listener_metrics(self, owner: str | None = None) -> list[dict]:
        """Return per-listener metrics, optionally filtered by owner."""
        bus_service = self.hassette._bus_service
        metrics = bus_service.get_listener_metrics_by_owner(owner) if owner else bus_service.get_all_listener_metrics()
        return [m.to_dict() for m in metrics]

    def get_bus_metrics_summary(self) -> BusMetricsSummaryResponse:
        """Compute aggregate totals across all listener metrics."""
        all_metrics = self.hassette._bus_service.get_all_listener_metrics()
        return BusMetricsSummaryResponse(
            total_listeners=len(all_metrics),
            total_invocations=sum(m.total_invocations for m in all_metrics),
            total_successful=sum(m.successful for m in all_metrics),
            total_failed=sum(m.failed for m in all_metrics),
            total_di_failures=sum(m.di_failures for m in all_metrics),
            total_cancelled=sum(m.cancelled for m in all_metrics),
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
        async with self._lock:
            for queue in self._ws_clients:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    self.logger.debug("Dropping message for slow WebSocket client")
