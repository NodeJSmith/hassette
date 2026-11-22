"""RuntimeQueryService: aggregates and caches live system state for the web UI."""

import asyncio
import dataclasses
import json
import time
from typing import TYPE_CHECKING, Any, ClassVar, Final

from hassette_wire import (
    API_SCHEMA_VERSION,
    AppsChangedData,
    AppStatus,
    AppStatusChangedData,
    BootIssue,
    ConnectivityData,
    EntityStateChangedData,
    ExecutionCompletedData,
    LogLevel,
    ServiceInfo,
    ServiceStatusData,
    SystemStatusResponse,
)
from pydantic import BaseModel

from hassette.bus import Bus
from hassette.core.app_registry import StatusChange, listed_apps, overlay_runtime_state
from hassette.core.bus_service import BusService
from hassette.core.logging_service import LoggingService
from hassette.core.pipeline_counters import PipelineCounter
from hassette.core.state_proxy import StateProxy
from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.events import AnyEvent
from hassette.events.hassette import extract_exception_fields
from hassette.integration.declarations import CommittedEntity
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.schemas.app_snapshots import AppInstanceInfo, AppListingSnapshot, AppManifestInfo
from hassette.schemas.ws_queue import WsClientSignal, WsQueueItem
from hassette.types.enums import ResourceRole, Topic
from hassette.utils import get_version
from hassette.web.mappers import declared_entity_from

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events.hassette import ExecutionCompletedPayload

WS_CLIENT_QUEUE_MAX = 256

RQS_LISTENER_PREFIX: Final = "hassette.rqs."

STATUS_OK: Final = "ok"
STATUS_DEGRADED: Final = "degraded"
STATUS_STARTING: Final = "starting"

SEVERITY_WARN: Final = "warn"
SEVERITY_ERR: Final = "err"

WS_EVENT_CONNECTIVITY: Final = "connectivity"
WS_EVENT_ENTITY_STATE_CHANGED: Final = "entity_state_changed"
WS_EVENT_APP_STATUS_CHANGED: Final = "app_status_changed"

SERVICE_ROLE_PATH = "payload.data.role"

IS_NOT_APP_ROLE = ~P.ValueIs(source=get_path(SERVICE_ROLE_PATH), condition=ResourceRole.APP)
"""Excludes APP-role resources from a service-status subscription.

Every ``Resource`` emits ``HASSETTE_EVENT_SERVICE_STATUS`` through the shared lifecycle
machinery, so an app's status transitions land on the same topic the framework's own do. This
keeps app transitions out of the web UI's framework-services stream, where apps (keyed by class
name, not instance) would collide; app status reaches the UI through ``app_status_changed``
instead.

Excludes APP rather than admitting SERVICE only, and the difference matters: several framework
resources are plain ``Resource`` subclasses (RESOURCE role), not ``Service``, and a SERVICE-only
filter would swallow their events. Negating APP also fails open on a missing or malformed role.
"""


class RuntimeQueryService(Resource):
    """Aggregates and caches live system state for the web UI.

    Reads from in-memory sources: AppHandler, log buffer, WS clients.
    All reads are instant — no database I/O. LoggingService is in depends_on to
    guarantee the capture handler is ready before WS broadcast wiring runs.

    AppHandler is deliberately absent from ``depends_on``: AppHandler and its ``AppRegistry``
    are constructed before the Resource lifecycle starts (see ``Hassette.wire_services()``), so
    registry metadata (manifests, only-app filter) is safely queryable before apps bootstrap and
    the dashboard is not gated on app-bootstrap release. This also removes the guaranteed reverse
    shutdown ordering that a ``depends_on`` edge would otherwise provide, so every AppHandler read
    below tolerates concurrent AppHandler teardown (registry state clearing mid-read) without
    raising.
    """

    depends_on: ClassVar[list[type[Resource]]] = [BusService, StateProxy, LoggingService]

    bus: Bus
    _lock: asyncio.Lock
    _start_time: float
    _subscriptions: "list[Subscription]"

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.bus = self.add_child(Bus)
        self._ws_clients: set[asyncio.Queue[WsQueueItem]] = set()
        self._lock = asyncio.Lock()
        self._start_time = time.time()
        self._subscriptions = []
        # Execution completions (handler and job) accumulated within the current drain tick, flushed as a batch.
        self._pending_completions: list[ExecutionCompletedData] = []
        # True when an asyncio.sleep(0) flush has been scheduled for the current tick.
        self._flush_scheduled = False

    @property
    def config_log_level(self) -> LogLevel:
        """Return the ``logging.web_api`` level, which this service shares with the web API."""
        return self.hassette.config.logging.web_api

    async def on_initialize(self) -> None:
        """Subscribe to the bus events the web UI streams and wire the log capture broadcast.

        Marks the service ready without subscribing when the web API is disabled.
        """
        if not self.hassette.config.web_api.run:
            mark_ready(self, reason="Web API disabled")
            return

        # BusService, StateProxy, and LoggingService are guaranteed ready by depends_on auto-wait.
        # AppHandler is not a dependency — its registry may still be pre-bootstrap here.

        # Subscribe to bus events. App status changes aren't subscribed to here: set_app_status calls
        # publish_app_status directly, so they reach clients in write order.
        self._subscriptions.append(
            await self.bus.on(
                topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
                handler=self.on_service_status,
                name=f"{RQS_LISTENER_PREFIX}on_service_status",
                # App instances have their own app_status_changed stream, so keep them out of the
                # Services panel. App-owned children (Bus, Scheduler, ...) carry RESOURCE role and
                # still pass this filter.
                where=IS_NOT_APP_ROLE,
            )
        )
        self._subscriptions.append(
            await self.bus.on_websocket_connected(
                handler=self.on_ws_connected, name=f"{RQS_LISTENER_PREFIX}on_ws_connected"
            )
        )
        self._subscriptions.append(
            await self.bus.on_websocket_disconnected(
                handler=self.on_ws_disconnected, name=f"{RQS_LISTENER_PREFIX}on_ws_disconnected"
            )
        )
        self._subscriptions.append(
            await self.bus.on(
                topic=Topic.HASSETTE_EVENT_EXECUTION_COMPLETED,
                handler=self.on_execution_completed,
                name=f"{RQS_LISTENER_PREFIX}on_execution_completed",
            )
        )
        # Named for its WS-layer effect (app data may have changed), not the backend
        # event name — see on_apps_changed's docstring.
        self._subscriptions.append(
            await self.bus.on(
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=self.on_apps_changed,
                name=f"{RQS_LISTENER_PREFIX}on_apps_changed",
            )
        )

        # Wire up log capture handler for WS broadcast
        handler = self.hassette.logging_service.capture_handler
        try:
            loop = asyncio.get_running_loop()
            handler.set_broadcast(self.put_to_clients, loop)
        except RuntimeError:
            self.logger.warning("No running event loop, log broadcast will not be available")

        mark_ready(self, reason="RuntimeQueryService initialized")

    async def on_shutdown(self) -> None:
        """Cancel bus subscriptions and send a shutdown signal to every WS client queue."""
        # Remove bus listeners
        for sub in self._subscriptions:
            sub.cancel()
        self._subscriptions.clear()

        # Close all WS client queues
        async with self._lock:
            for queue in self._ws_clients:
                replace_backlog(queue, WsClientSignal.SHUTDOWN)
            self._ws_clients.clear()

    def broadcast_envelope(self, event_type: str, data: Any) -> None:
        """Broadcast a WS envelope of the shape ``{"type", "data", "timestamp"}``.

        ``data`` is already dumped: a single model's dict, or a list of them for a batch.
        """
        self.put_to_clients(envelope(event_type, data))

    def build_and_broadcast(self, event_type: str, payload: BaseModel) -> None:
        """Dump a single wire model and broadcast it as the ``data`` of an ``event_type`` envelope."""
        self.broadcast_envelope(event_type, payload.model_dump())

    def publish_app_status(self, change: StatusChange) -> None:
        """Put one app instance status change on every client queue as ``app_status_changed``.

        ``AppInstanceLifecycleMixin.set_app_status`` calls this right after ``AppRegistry.set_status`` returns the
        change, so messages reach every client queue in ``status_revision`` order. Keep it synchronous: an await
        here would let a later write's message overtake this one.
        """
        exc_str, exc_type, exc_tb = extract_exception_fields(change.error)
        payload = AppStatusChangedData(
            app_key=change.app_key,
            instance_name=change.instance_name,
            status=change.status,
            status_revision=change.status_revision,
            boot_id=self.hassette.integration_service.boot_id,
            app_status=change.app_status,
            previous_status=change.previous,
            class_name=change.class_name,
            exception=exc_str,
            exception_type=exc_type,
            exception_traceback=exc_tb,
            needs_restart=change.needs_restart.to_wire() if change.needs_restart else None,
        )
        self.put_to_clients(envelope(WS_EVENT_APP_STATUS_CHANGED, payload.model_dump()))
        self.logger.debug(
            "Published app_status_changed for app '%s' instance '%s' (status_revision %d, clients: %d)",
            change.app_key,
            change.instance_name,
            change.status_revision,
            len(self._ws_clients),
        )

    async def on_service_status(self, event: AnyEvent) -> None:
        """Convert a non-app service status event to ``ServiceStatusData`` and broadcast it to WS clients."""
        data = event.payload.data
        payload = ServiceStatusData(
            resource_name=data.resource_name,
            status=data.status,
            previous_status=data.previous_status,
            exception=data.exception,
            exception_type=data.exception_type,
            exception_traceback=data.exception_traceback,
            ready=data.ready,
            ready_phase=data.ready_phase,
        )
        self.build_and_broadcast("service_status", payload)

    async def on_apps_changed(self) -> None:
        """Broadcast a refetch signal after a full app load/reload pass.

        The triggering event (``HASSETTE_EVENT_APP_LOAD_COMPLETED``) carries no data — see
        ``AppsChangedData`` — so this handler declares no ``event`` parameter;
        ``ParameterInjector`` only injects what a handler's signature actually asks for.
        """
        self.build_and_broadcast("apps_changed", AppsChangedData())

    async def on_ws_connected(self) -> None:
        """Broadcast a ``connectivity`` message reporting the Home Assistant connection as up."""
        self.build_and_broadcast(WS_EVENT_CONNECTIVITY, ConnectivityData(connected=True))

    async def on_ws_disconnected(self) -> None:
        """Broadcast a ``connectivity`` message reporting the Home Assistant connection as down."""
        self.build_and_broadcast(WS_EVENT_CONNECTIVITY, ConnectivityData(connected=False))

    def publish_entity_state(
        self, boot_id: str, entity_revision: int, instance: tuple[str, str], entity: CommittedEntity
    ) -> None:
        """Put one committed entity state change on every client queue as ``entity_state_changed``.

        ``IntegrationService.set_job`` calls this inline after it bumps the revision, so messages reach every
        client queue in revision order. Keep it that way: take every value as an argument, read no
        ``IntegrationService`` state, and keep it synchronous.
        """
        payload = EntityStateChangedData(
            boot_id=boot_id,
            entity_revision=entity_revision,
            app_key=instance[0],
            instance_name=instance[1],
            entity=declared_entity_from(entity),
        )
        self.put_to_clients(envelope(WS_EVENT_ENTITY_STATE_CHANGED, payload.model_dump()))

    async def on_execution_completed(self, event: AnyEvent) -> None:
        """Accumulate an execution completion (handler or job) into the pending batch for this drain tick.

        Builds the wire model through its constructor, so a malformed payload raises here — this
        is a bus-handler invocation, so ``CommandExecutor._execute`` records the failure and the
        malformed completion never reaches ``_pending_completions`` or the WS feed.
        """
        data: ExecutionCompletedPayload = event.payload.data
        self._pending_completions.append(
            ExecutionCompletedData(
                kind=data.kind,
                app_key=data.app_key,
                status=data.status,
                duration_ms=data.duration_ms,
                error_type=data.error_type,
                listener_id=data.listener_id,
                job_id=data.job_id,
                thread_leaked=data.thread_leaked,
            )
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

        completions = self._pending_completions
        self._pending_completions = []

        if completions:
            self.broadcast_envelope("execution_completed", [c.model_dump() for c in completions])

    def overlay_manifest_rows(self, db_rows: list[dict[str, Any]]) -> list[AppManifestInfo]:
        """Overlay DB-persisted ``app_manifests`` rows with live runtime state.

        Thin wrapper around ``overlay_runtime_state()`` (owned by ``AppRegistry``) that lets
        web routes reach it through ``RuntimeQueryService`` instead of importing ``core``
        directly — the web layer must not runtime-import ``core`` (see ``web-no-core`` in
        ``tools/check_module_boundaries.py``).
        """
        return overlay_runtime_state(db_rows, self.hassette.app_handler.registry)

    def overlay_listed_manifest_rows(self, db_rows: list[dict[str, Any]]) -> list[AppManifestInfo]:
        """Overlay ``app_manifests`` rows for an app list, leaving out apps removed from config.

        See ``listed_apps`` for which removed apps stay listed.
        """
        return listed_apps(self.overlay_manifest_rows(db_rows))

    def app_listing(self, manifests: list[AppManifestInfo]) -> AppListingSnapshot:
        """Attach each instance's declared entities to the app list's manifests, with the revision they were read at.

        Only ``GET /api/apps`` calls this: the shared overlays stay entity-free, so the other
        responses carrying instances never hold entity state without a revision beside it. Synchronous, so the
        entities and ``entity_revision`` are one snapshot.
        """
        integration = self.hassette.integration_service

        def with_entities(instance: AppInstanceInfo) -> AppInstanceInfo:
            entities = tuple(integration.entities(instance.app_key, instance.instance_name))
            return dataclasses.replace(instance, entities=entities)

        listed = tuple(
            dataclasses.replace(manifest, instances=tuple(with_entities(instance) for instance in manifest.instances))
            for manifest in manifests
        )
        return AppListingSnapshot(
            manifests=listed, boot_id=integration.boot_id, entity_revision=integration.entity_revision
        )

    def get_registry_only_apps(self) -> list[str]:
        """Return the exclusive-app filter (``--app`` CLI flag), sorted.

        Sourced from ``AppRegistry`` — the exclusive-app filter is session-specific
        in-memory state, never persisted to the ``app_manifests`` DB table.
        """
        return sorted(self.hassette.app_handler.registry.only_apps)

    def is_bootstrap_released(self) -> bool:
        """Return whether app bootstrap has been released, tolerating an unwired coordinator.

        ``app_bootstrap_coordinator`` is a lazily-wired ``Hassette`` attribute, like
        ``app_handler``/``websocket_service``/``state_proxy`` elsewhere in this class — reading it
        before it's wired (or after teardown) raises ``AttributeError``/``RuntimeError``. Shared by
        both ``get_system_status()`` and ``collect_boot_issues()`` so the tolerance lives in one place.

        Returns:
            True when the bootstrap latch is open. False when the latch is closed or the
            coordinator is not reachable.
        """
        try:
            return self.hassette.app_bootstrap_coordinator.is_released()
        except (AttributeError, RuntimeError):
            return False

    def get_system_status(self) -> SystemStatusResponse:
        """Build the system status snapshot from in-memory state.

        Unreachable components (not yet wired, or torn down) report zero counts instead of raising.

        Returns:
            The status response, with ``status`` set to ``ok`` when Home Assistant is connected and
            app bootstrap is released, ``starting`` when it has never connected, and ``degraded``
            otherwise.
        """
        websocket_service = self.hassette.websocket_service
        is_connected = websocket_service.is_connected
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

        try:
            pending_wait_for_count = self.hassette.bus_service.pending_wait_for_count
        except (AttributeError, RuntimeError):
            pending_wait_for_count = 0

        services = [
            ServiceInfo(
                name=child.class_name,
                status=child.status,
                ready_phase=getattr(child, "_ready_reason", None),
            )
            for child in self.hassette.children
        ]
        bootstrap_released = self.is_bootstrap_released()
        if is_connected and bootstrap_released:
            status = STATUS_OK
        elif websocket_service.has_ever_connected:
            # "degraded" covers two distinct situations: a connection that was live and is now
            # lost, and a currently-live connection where app bootstrap hasn't released yet (e.g.
            # still waiting on the initial state snapshot). Both mean "not fully healthy yet/anymore",
            # but only `bootstrap_released` + `websocket_connected` on the response distinguish them.
            status = STATUS_DEGRADED
        else:
            status = STATUS_STARTING

        boot_issues = self.collect_boot_issues()

        return SystemStatusResponse(
            status=status,
            websocket_connected=is_connected,
            bootstrap_released=bootstrap_released,
            uptime_seconds=uptime,
            entity_count=entity_count,
            app_count=app_count,
            services=services,
            version=get_version(),
            api_schema_version=API_SCHEMA_VERSION,
            boot_issues=boot_issues,
            log_queue_drops=self.hassette.get_log_queue_drops(),
            db_write_queue_drops=self.hassette.get_db_write_queue_drops(),
            log_persistence_active=self.hassette.is_log_persistence_active(),
            pending_wait_for_count=pending_wait_for_count,
        )

    def collect_boot_issues(self) -> list[BootIssue]:
        """Collect boot-time issues from blocked apps, failed app instances, and pending bootstrap.

        Returns a list of ``BootIssue`` objects derived from:
        - App bootstrap not yet released while at least one autostart app is configured — severity ``warn``
        - Apps that are blocked (e.g. import error, pre-check failure) — severity ``warn``
        - Apps that failed to start — severity ``err``
        """
        issues: list[BootIssue] = []
        try:
            full_snapshot = self.hassette.app_handler.registry.get_full_snapshot()
        except (AttributeError, RuntimeError):
            return issues

        if not self.is_bootstrap_released() and any(manifest.autostart for manifest in full_snapshot.manifests):
            issues.append(
                BootIssue(
                    severity=SEVERITY_WARN,
                    label="Apps pending on Home Assistant",
                    detail=(
                        "App bootstrap has not been released — autostart apps will remain stopped "
                        "until Home Assistant connects and the initial state snapshot succeeds."
                    ),
                )
            )

        for manifest in full_snapshot.manifests:
            if manifest.status == AppStatus.BLOCKED and manifest.block_reason:
                issues.append(
                    BootIssue(
                        severity=SEVERITY_WARN,
                        label=f"App blocked: {manifest.display_name}",
                        detail=manifest.block_reason,
                    )
                )
            elif manifest.status in (AppStatus.FAILED, AppStatus.DEGRADED) and manifest.error_message:
                issues.append(
                    BootIssue(
                        severity=SEVERITY_ERR,
                        label=f"App failed: {manifest.display_name}",
                        detail=manifest.error_message,
                    )
                )

        return issues

    async def register_ws_client(self) -> asyncio.Queue[WsQueueItem]:
        """Register a new WS client to receive broadcasts.

        Returns:
            A bounded queue that receives each broadcast message. It receives
            ``WsClientSignal.SHUTDOWN`` when the service shuts down. A broadcast that finds it full
            unregisters it and replaces its backlog with ``WsClientSignal.TOO_SLOW``: the client
            has missed a message and must close and reconnect to resync.
        """
        queue: asyncio.Queue[WsQueueItem] = asyncio.Queue(maxsize=WS_CLIENT_QUEUE_MAX)
        async with self._lock:
            self._ws_clients.add(queue)
        self.logger.debug("WebSocket client registered (total: %d)", len(self._ws_clients))
        return queue

    async def unregister_ws_client(self, queue: asyncio.Queue[WsQueueItem]) -> None:
        """Stop broadcasting to a client queue returned by ``register_ws_client``; unknown queues are ignored."""
        async with self._lock:
            self._ws_clients.discard(queue)
            count = len(self._ws_clients)
        self.logger.debug("WebSocket client unregistered (total: %d)", count)

    def put_to_clients(self, message: dict) -> None:
        """Put a message on every client queue; the one path every message takes.

        A client whose queue is full is cut off rather than skipped, so it never misses a message while its socket
        stays open (see ``register_ws_client``).

        Synchronous with no lock: it runs on the event loop without suspending, so no client can register or
        unregister mid-loop, and callers that need ordering (``publish_app_status``, ``publish_entity_state``)
        get it by calling this in write order.
        """
        # Pre-serialize once for all clients (handles enums, dataclasses, etc.)
        safe_message = json.loads(json.dumps(message, default=str))
        too_slow: list[asyncio.Queue[WsQueueItem]] = []
        for queue in self._ws_clients:
            try:
                queue.put_nowait(safe_message)
            except asyncio.QueueFull:
                too_slow.append(queue)
        for queue in too_slow:
            self._ws_clients.discard(queue)
            replace_backlog(queue, WsClientSignal.TOO_SLOW)
        if too_slow:
            self.hassette.pipeline_counters.increment(PipelineCounter.WS_CLIENT_CLOSED_TOO_SLOW, n=len(too_slow))
            self.logger.warning(
                "Closing %d WebSocket client(s) with a full queue (%d messages); they will reconnect "
                "(clients left: %d)",
                len(too_slow),
                WS_CLIENT_QUEUE_MAX,
                len(self._ws_clients),
            )


def replace_backlog(queue: asyncio.Queue[WsQueueItem], signal: WsClientSignal) -> None:
    """Discard everything waiting in ``queue`` and leave ``signal`` as its only item.

    Emptying the queue first is what guarantees the signal fits, so it arrives even when the queue was full.
    """
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    queue.put_nowait(signal)


def envelope(event_type: str, data: Any) -> dict[str, Any]:
    """A WS message of the shape ``{"type", "data", "timestamp"}``; ``data`` is already dumped."""
    return {"type": event_type, "data": data, "timestamp": time.time()}
