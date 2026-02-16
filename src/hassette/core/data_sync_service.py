"""DataSyncService: aggregates and caches system state for the web UI."""

import asyncio
import contextlib
import json
import time
from collections import deque
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from hassette.bus import Bus
from hassette.events import Event, RawStateChangeEvent
from hassette.logging_ import LogEntry, get_log_capture_handler
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from hassette.web.models import (
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppStatusResponse,
    BusMetricsSummaryResponse,
    SchedulerSummaryResponse,
    SystemStatusResponse,
)

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events import HassStateDict
    from hassette.scheduler import ScheduledJob

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _serialize_payload(data: object) -> object:
    """Convert a dataclass (possibly containing enums) to a JSON-safe dict."""
    if hasattr(data, "__dataclass_fields__"):
        return json.loads(json.dumps(asdict(data), default=str))  # pyright: ignore[reportArgumentType]
    return data


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
                self.hassette.bus_service,
                self.hassette.state_proxy,
                self.hassette.app_handler,
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
        raw = event.payload.data if hasattr(event, "payload") else {}
        entry = {
            "type": "app_status_changed",
            "data": _serialize_payload(raw),
            "timestamp": time.time(),
        }
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_service_status(self, event: Event[Any]) -> None:
        raw = event.payload.data if hasattr(event, "payload") else {}
        entry = {"type": "service_status", "data": _serialize_payload(raw), "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_ws_connected(self) -> None:
        entry = {"type": "connectivity", "data": {"connected": True}, "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    async def _on_ws_disconnected(self) -> None:
        entry = {"type": "connectivity", "data": {"connected": False}, "timestamp": time.time()}
        self._event_buffer.append(entry)
        await self.broadcast(entry)

    # --- Owner resolution ---

    def _resolve_owner_ids(self, app_key: str) -> list[str]:
        """Resolve an app_key to the owner_id(s) used by listeners and jobs."""
        instances = self.hassette.app_handler.registry.get_apps_by_key(app_key)
        return [app.unique_name for app in instances.values()]

    def get_user_app_owner_map(self) -> dict[str, str]:
        """Return {owner_id: app_key} for all running user-app instances."""
        return {app.unique_name: app_key for app_key, _, app in self.hassette.app_handler.registry.iter_all_instances()}

    def get_instance_owner_map(self) -> dict[str, tuple[str, int]]:
        """Return {owner_id: (app_key, index)} for all running user-app instances."""
        return {
            app.unique_name: (app_key, index)
            for app_key, index, app in self.hassette.app_handler.registry.iter_all_instances()
        }

    def _resolve_instance_owner_id(self, app_key: str, index: int) -> str | None:
        """Resolve a specific app instance to its owner_id (unique_name)."""
        app = self.hassette.app_handler.registry.get(app_key, index)
        if app is not None:
            return app.unique_name
        return None

    def get_listener_metrics_for_instance(self, app_key: str, index: int) -> list[dict]:
        """Return listener metrics filtered to a specific app instance."""
        owner_id = self._resolve_instance_owner_id(app_key, index)
        if not owner_id:
            return []
        bus_service = self.hassette.bus_service
        return [m.to_dict() for m in bus_service.get_listener_metrics_by_owner(owner_id)]

    async def get_scheduled_jobs_for_instance(self, app_key: str, index: int) -> list[dict]:
        """Return scheduled jobs filtered to a specific app instance."""
        owner_id = self._resolve_instance_owner_id(app_key, index)
        if not owner_id:
            return []
        jobs = await self.hassette.scheduler_service.get_all_jobs()
        return [self._serialize_job(job) for job in sorted(jobs, key=lambda j: j.next_run) if job.owner == owner_id]

    @staticmethod
    def _serialize_job(job: "ScheduledJob") -> dict:
        """Convert a scheduled job to a JSON-safe dict."""
        return {
            "job_id": job.job_id,
            "name": job.name,
            "owner": job.owner,
            "next_run": str(job.next_run),
            "repeat": job.repeat,
            "cancelled": job.cancelled,
            "trigger_type": type(job.trigger).__name__ if job.trigger else "once",
        }

    # --- Entity state access (delegates to StateProxy) ---

    def get_entity_state(self, entity_id: str) -> "HassStateDict | None":
        return self.hassette.state_proxy.get_state(entity_id)

    def get_all_entity_states(self) -> "dict[str, HassStateDict]":
        return dict(self.hassette.state_proxy.states)

    def get_domain_states(self, domain: str) -> "dict[str, HassStateDict]":
        return self.hassette.state_proxy.get_domain_states(domain)

    # --- App status ---

    def get_app_status_snapshot(self) -> AppStatusResponse:
        snapshot = self.hassette.app_handler.get_status_snapshot()
        apps = [
            AppInstanceResponse(
                app_key=info.app_key,
                index=info.index,
                instance_name=info.instance_name,
                class_name=info.class_name,
                status=info.status.value,
                error_message=info.error_message,
                owner_id=info.owner_id,
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

    def get_all_manifests_snapshot(self) -> AppManifestListResponse:
        """Return full manifest-based snapshot including stopped/disabled apps."""
        snapshot = self.hassette.app_handler.registry.get_full_snapshot()
        manifests = [
            AppManifestResponse(
                app_key=m.app_key,
                class_name=m.class_name,
                display_name=m.display_name,
                filename=m.filename,
                enabled=m.enabled,
                auto_loaded=m.auto_loaded,
                status=m.status,
                block_reason=m.block_reason,
                instance_count=m.instance_count,
                instances=[
                    AppInstanceResponse(
                        app_key=inst.app_key,
                        index=inst.index,
                        instance_name=inst.instance_name,
                        class_name=inst.class_name,
                        status=str(inst.status),
                        error_message=inst.error_message,
                        owner_id=inst.owner_id,
                    )
                    for inst in m.instances
                ],
                error_message=m.error_message,
            )
            for m in snapshot.manifests
        ]
        return AppManifestListResponse(
            total=snapshot.total,
            running=snapshot.running,
            failed=snapshot.failed,
            stopped=snapshot.stopped,
            disabled=snapshot.disabled,
            blocked=snapshot.blocked,
            manifests=manifests,
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

        entries: list[LogEntry] = handler.get_buffer_snapshot()

        if app_key:
            entries = [e for e in entries if e.app_key == app_key]

        if level:
            min_level = LOG_LEVELS.get(level.upper(), 0)
            entries = [e for e in entries if LOG_LEVELS.get(e.level, 0) >= min_level]

        return [e.to_dict() for e in entries[-limit:]]

    # --- Scheduler access ---

    async def get_scheduled_jobs(self, owner: str | None = None) -> list[dict]:
        """Return all scheduled jobs across all apps, sorted by next_run."""
        jobs = await self.hassette.scheduler_service.get_all_jobs()
        result = [self._serialize_job(job) for job in sorted(jobs, key=lambda j: j.next_run)]
        if owner:
            owner_ids = self._resolve_owner_ids(owner)
            if owner_ids:
                owner_set = set(owner_ids)
                result = [j for j in result if j["owner"] in owner_set]
            else:
                result = [j for j in result if j["owner"] == owner]
        return result

    def get_job_execution_history(self, limit: int = 50, owner: str | None = None) -> list[dict]:
        if owner:
            owner_ids = self._resolve_owner_ids(owner)
            if owner_ids:
                owner_set = set(owner_ids)
                records = self.hassette.scheduler_service.get_execution_history(limit * 2)
                records = [r for r in records if r.owner in owner_set][-limit:]
                return [asdict(r) for r in records]
        records = self.hassette.scheduler_service.get_execution_history(limit, owner)
        return [asdict(r) for r in records]

    async def get_scheduler_summary(self) -> SchedulerSummaryResponse:
        """Compute aggregate counts across all scheduled jobs."""
        jobs = await self.hassette.scheduler_service.get_all_jobs()
        return SchedulerSummaryResponse(
            total_jobs=len(jobs),
            active=sum(1 for j in jobs if not j.cancelled),
            cancelled=sum(1 for j in jobs if j.cancelled),
            repeating=sum(1 for j in jobs if j.repeat and not j.cancelled),
        )

    # --- System status ---

    def get_system_status(self) -> SystemStatusResponse:
        ws_connected = self.hassette.websocket_service.status == ResourceStatus.RUNNING
        uptime = time.time() - self._start_time

        try:
            entity_count = len(self.hassette.state_proxy.states)
        except Exception:
            entity_count = 0

        try:
            snapshot = self.hassette.app_handler.get_status_snapshot()
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
        elif self.hassette.state_proxy.is_ready():
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
        bus_service = self.hassette.bus_service
        if not owner:
            return [m.to_dict() for m in bus_service.get_all_listener_metrics()]
        owner_ids = self._resolve_owner_ids(owner)
        if not owner_ids:
            return [m.to_dict() for m in bus_service.get_listener_metrics_by_owner(owner)]
        result: list[dict] = []
        for oid in owner_ids:
            result.extend(m.to_dict() for m in bus_service.get_listener_metrics_by_owner(oid))
        return result

    def get_bus_metrics_summary(self) -> BusMetricsSummaryResponse:
        """Compute aggregate totals across all listener metrics."""
        all_metrics = self.hassette.bus_service.get_all_listener_metrics()
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
        # Pre-serialize once for all clients (handles enums, dataclasses, etc.)
        safe_message = json.loads(json.dumps(message, default=str))
        async with self._lock:
            for queue in self._ws_clients:
                try:
                    queue.put_nowait(safe_message)
                except asyncio.QueueFull:
                    self.logger.debug("Dropping message for slow WebSocket client")
