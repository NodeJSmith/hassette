import asyncio
import time
import typing
from typing import ClassVar

from hassette.bus import Bus
from hassette.core.bus_service import BusService
from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.events import HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.base import Resource, RestartSpec, Service
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import Hassette


class RestartBudget:
    """Sliding-window restart budget tracker.

    Tracks restart timestamps within a rolling time window. Once the number of
    recorded restarts within the window reaches ``intensity``, the budget is
    considered exhausted.

    Uses :func:`time.monotonic` for clock-independence and resistance to
    system clock changes.
    """

    def __init__(self, intensity: int, period_seconds: float) -> None:
        """Initialize the budget tracker.

        Args:
            intensity: Maximum number of restarts allowed within the window.
            period_seconds: Sliding window size in seconds.
        """
        self._timestamps: list[float] = []
        self._intensity = intensity
        self._period = period_seconds

    def record_restart(self) -> None:
        """Record a restart at the current monotonic time."""
        self._timestamps.append(time.monotonic())

    def is_exhausted(self) -> bool:
        """Return True if the number of restarts within the window meets or exceeds intensity."""
        self._evict_expired()
        return len(self._timestamps) >= self._intensity

    def current_attempts(self) -> int:
        """Return the number of restarts within the current window."""
        self._evict_expired()
        return len(self._timestamps)

    def reset(self) -> None:
        """Clear all recorded restart timestamps."""
        self._timestamps.clear()

    def _evict_expired(self) -> None:
        """Remove timestamps that have fallen outside the sliding window."""
        cutoff = time.monotonic() - self._period
        self._timestamps = [t for t in self._timestamps if t > cutoff]


class ServiceWatcher(Resource):
    """Watches for service events and handles them."""

    depends_on: ClassVar[list[type[Resource]]] = [BusService]

    bus: Bus
    """Event bus for inter-service communication."""

    _budgets: dict[str, RestartBudget]
    """Per-service sliding-window restart budget, keyed by 'name:role'."""

    _restarting: set[str]
    """Set of service keys currently in the middle of a restart sequence."""

    _cooldown_tasks: dict[str, asyncio.Task]
    """Active long-cooldown tasks, keyed by 'name:role'."""

    _cooldown_cycles: dict[str, int]
    """Count of cooldown cycles completed per service."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.bus = self.add_child(Bus)
        self._budgets = {}
        self._restarting = set()
        self._cooldown_tasks = {}
        self._cooldown_cycles = {}

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.service_watcher

    async def on_initialize(self) -> None:
        self._budgets = {}
        self._restarting = set()
        self._cooldown_tasks = {}
        self._cooldown_cycles = {}
        self._register_internal_event_listeners()
        self.mark_ready(reason="Service watcher initialized")

    @staticmethod
    def _service_key(name: str, role: object) -> str:
        return f"{name}:{role}"

    def _get_service(self, name: str, role: object) -> list[Service]:
        """Return matching Service instances from hassette.children."""
        return [c for c in self.hassette.children if isinstance(c, Service) and c.class_name == name and c.role == role]

    def _get_budget(self, key: str, spec: RestartSpec) -> RestartBudget:
        """Return existing budget for key or create a new one from spec."""
        if key not in self._budgets:
            self._budgets[key] = RestartBudget(spec.budget_intensity, spec.budget_period_seconds)
        return self._budgets[key]

    async def _shutdown_safe_sleep(self, duration: float) -> bool:
        """Sleep for duration seconds, waking early if shutdown is requested.

        Returns:
            True if sleep completed normally (timeout expired).
            False if shutdown was requested before the timeout.
        """
        try:
            await asyncio.wait_for(self.hassette.shutdown_event.wait(), timeout=duration)
            # Shutdown event fired before timeout — abort
            return False
        except TimeoutError:
            # Timeout expired normally — sleep completed
            return True

    def _emit_service_status_event(
        self,
        name: str,
        role: object,
        status: ResourceStatus,
        previous_status: ResourceStatus,
        exception: str | None = None,
        exception_type: str | None = None,
        exception_traceback: str | None = None,
        retry_at: float | None = None,
    ) -> HassetteServiceEvent:
        """Build a HassetteServiceEvent for a service status transition."""
        return HassetteServiceEvent(
            topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
            payload=HassettePayload(
                event_type=str(status),
                # ready=False is always correct for ServiceWatcher-synthesized events: this method
                # only fires for CRASHED/EXHAUSTED states where the service loop has already exited.
                data=ServiceStatusPayload(
                    resource_name=name,
                    role=role,  # pyright: ignore[reportArgumentType]
                    status=status,
                    previous_status=previous_status,
                    exception=exception,
                    exception_type=exception_type,
                    exception_traceback=exception_traceback,
                    retry_at=retry_at,
                    ready=False,
                    ready_phase=None,
                ),
            ),
        )

    async def _handle_exhaustion(
        self,
        name: str,
        role: object,
        key: str,
        spec: RestartSpec,
        original_data: ServiceStatusPayload,
    ) -> None:
        """Handle budget exhaustion according to restart_type."""
        if spec.restart_type == RestartType.PERMANENT:
            self.logger.error(
                "%s '%s' restart budget exhausted (PERMANENT), emitting CRASHED and shutting down",
                role,
                name,
            )
            crashed_event = self._emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.CRASHED,
                previous_status=ResourceStatus.FAILED,
                exception=original_data.exception,
                exception_type=original_data.exception_type,
                exception_traceback=original_data.exception_traceback,
            )
            await self.hassette.send_event(Topic.HASSETTE_EVENT_SERVICE_STATUS, crashed_event)
            await self.hassette.shutdown()

        elif spec.restart_type == RestartType.TRANSIENT:
            retry_at = time.time() + spec.cooldown_seconds
            self.logger.warning(
                "%s '%s' restart budget exhausted (TRANSIENT), entering cooldown for %.1fs (retry_at=%.0f)",
                role,
                name,
                spec.cooldown_seconds,
                retry_at,
            )
            cooling_event = self._emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.EXHAUSTED_COOLING,
                previous_status=ResourceStatus.FAILED,
                exception=original_data.exception,
                exception_type=original_data.exception_type,
                exception_traceback=original_data.exception_traceback,
                retry_at=retry_at,
            )
            await self.hassette.send_event(Topic.HASSETTE_EVENT_SERVICE_STATUS, cooling_event)
            services = self._get_service(name, role)
            if not services:
                self.logger.warning("No %s found for '%s' after EXHAUSTED_COOLING, skipping status set", role, name)
            else:
                services[0].status = ResourceStatus.EXHAUSTED_COOLING
            # Cancel existing cooldown for this service if any
            existing = self._cooldown_tasks.get(key)
            if existing and not existing.done():
                existing.cancel()
            cooldown_task = self.task_bucket.spawn(
                self._cooldown_and_retry(name, role, key, spec),
                name=f"service_watcher:cooldown:{key}",
            )
            self._cooldown_tasks[key] = cooldown_task

        else:  # TEMPORARY
            self.logger.warning(
                "%s '%s' restart budget exhausted (TEMPORARY), marking as EXHAUSTED_DEAD",
                role,
                name,
            )
            dead_event = self._emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.EXHAUSTED_DEAD,
                previous_status=ResourceStatus.FAILED,
                exception=original_data.exception,
                exception_type=original_data.exception_type,
                exception_traceback=original_data.exception_traceback,
            )
            await self.hassette.send_event(Topic.HASSETTE_EVENT_SERVICE_STATUS, dead_event)
            services = self._get_service(name, role)
            if not services:
                self.logger.warning("No %s found for '%s' after EXHAUSTED_DEAD, skipping status set", role, name)
            else:
                services[0].status = ResourceStatus.EXHAUSTED_DEAD

    async def _cooldown_and_retry(self, name: str, role: object, key: str, spec: RestartSpec) -> None:
        """Long-cooldown sleep followed by budget reset and restart attempt.

        Tracks cooldown cycles. If max_cooldown_cycles is exceeded, transitions to EXHAUSTED_DEAD.
        """
        self._cooldown_cycles[key] = self._cooldown_cycles.get(key, 0) + 1
        cycle = self._cooldown_cycles[key]

        if spec.max_cooldown_cycles > 0 and cycle > spec.max_cooldown_cycles:
            self.logger.warning(
                "%s '%s' cooldown cycle limit exceeded (%d/%d), transitioning to EXHAUSTED_DEAD",
                role,
                name,
                cycle,
                spec.max_cooldown_cycles,
            )
            dead_event = self._emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.EXHAUSTED_DEAD,
                previous_status=ResourceStatus.EXHAUSTED_COOLING,
            )
            await self.hassette.send_event(Topic.HASSETTE_EVENT_SERVICE_STATUS, dead_event)
            services = self._get_service(name, role)
            if not services:
                self.logger.warning(
                    "No %s found for '%s' after cooldown cycle limit, skipping EXHAUSTED_DEAD status set", role, name
                )
            else:
                services[0].status = ResourceStatus.EXHAUSTED_DEAD
            return

        self.logger.info(
            "%s '%s' in cooldown for %.1fs (cycle %d)",
            role,
            name,
            spec.cooldown_seconds,
            cycle,
        )

        completed = await self._shutdown_safe_sleep(spec.cooldown_seconds)
        if not completed or self.hassette.shutdown_event.is_set():
            self.logger.debug("%s '%s' cooldown aborted (shutdown requested)", role, name)
            return

        # Reset budget and attempt restart
        budget = self._budgets.get(key)
        if budget:
            budget.reset()

        services = self._get_service(name, role)
        if not services:
            self.logger.warning("No %s found for '%s' after cooldown, skipping restart", role, name)
            return

        self.logger.info("%s '%s' cooldown complete, attempting restart", role, name)
        for service in services:
            try:
                await service.restart()
            except Exception as e:
                self.logger.error("%s '%s' restart after cooldown failed: %s", role, name, e)

    async def restart_service(self, event: HassetteServiceEvent) -> None:
        """Restart a failed service using per-service RestartSpec-driven behavior."""
        data = event.payload.data
        name = data.resource_name
        role = data.role

        key = self._service_key(name, role)

        # Resolve the service and its restart_spec
        services = self._get_service(name, role)
        if not services:
            self.logger.warning("No %s found for '%s', skipping restart", role, name)
            return

        service = services[0]
        spec = service.restart_spec

        # Step 1: Check fatal errors — immediate shutdown regardless of restart type
        if data.exception_type and data.exception_type in spec.fatal_error_names:
            self.logger.error(
                "%s '%s' raised fatal error '%s', triggering immediate shutdown",
                role,
                name,
                data.exception_type,
            )
            crashed_event = self._emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.CRASHED,
                previous_status=ResourceStatus.FAILED,
                exception=data.exception,
                exception_type=data.exception_type,
                exception_traceback=data.exception_traceback,
            )
            await self.hassette.send_event(Topic.HASSETTE_EVENT_SERVICE_STATUS, crashed_event)
            await self.hassette.shutdown()
            return

        # Step 2: Check non-retryable errors — skip restart, go to exhaustion handling
        if data.exception_type and data.exception_type in spec.non_retryable_error_names:
            self.logger.warning(
                "%s '%s' raised non-retryable error '%s', skipping restart",
                role,
                name,
                data.exception_type,
            )
            await self._handle_exhaustion(name, role, key, spec, data)
            return

        # Step 3: In-restart guard — prevent double budget depletion from concurrent FAILED events
        if key in self._restarting:
            self.logger.debug(
                "%s '%s' restart already in progress, dropping duplicate FAILED event",
                role,
                name,
            )
            return

        # Step 4: Check budget exhaustion
        budget = self._get_budget(key, spec)
        if budget.is_exhausted():
            # Clear any stale in-restart state before handling exhaustion
            self._restarting.discard(key)
            await self._handle_exhaustion(name, role, key, spec, data)
            return

        # Step 5: Mark in-restart and record the restart
        self._restarting.add(key)
        budget.record_restart()

        attempts = budget.current_attempts()

        # Step 6: Apply exponential backoff with shutdown-safe sleep
        backoff = min(
            spec.backoff_base_seconds * (spec.backoff_multiplier ** (attempts - 1)),
            spec.backoff_max_seconds,
        )

        if backoff > 0:
            self.logger.info(
                "%s '%s' restarting (attempt %d, waiting %.1fs)",
                role,
                name,
                attempts,
                backoff,
            )
            completed = await self._shutdown_safe_sleep(backoff)
            if not completed or self.hassette.shutdown_event.is_set():
                self.logger.debug("%s '%s' backoff sleep aborted (shutdown requested)", role, name)
                self._restarting.discard(key)
                return

        self.logger.debug("%s '%s' is being restarted after '%s'", role, name, event.payload.event_type)

        if len(services) > 1:
            self.logger.warning("Multiple %s found for '%s', restarting all", role, name)

        # Step 7: Restart the service — catch and log exceptions, do NOT double-count budget.
        # Clear in-restart guard AFTER the entire loop so concurrent FAILED events cannot
        # enter restart_service() while restarts are still in progress.
        try:
            for svc in services:
                try:
                    await svc.restart()
                except Exception as e:
                    self.logger.error(
                        "%s '%s' restart raised an exception (service left in FAILED state): %s",
                        role,
                        name,
                        e,
                    )
        finally:
            self._restarting.discard(key)

    async def log_service_event(self, event: HassetteServiceEvent) -> None:
        """Log the startup of a service."""

        name = event.payload.data.resource_name
        role = event.payload.data.role

        status, previous_status = event.payload.data.status, event.payload.data.previous_status

        if status == previous_status:
            self.logger.debug("%s '%s' status unchanged at '%s', not logging", role, name, status)
            return

        try:
            self.logger.debug(
                "%s '%s' transitioned to status '%s' from '%s'",
                role,
                name,
                event.payload.data.status,
                event.payload.data.previous_status,
            )

        except Exception as e:
            self.logger.error("Failed to log %s startup for '%s': %s", role, name, e)
            raise

    async def shutdown_if_crashed(self, event: HassetteServiceEvent) -> None:
        """Shutdown the Hassette instance if a service has crashed."""
        data = event.payload.data
        name = data.resource_name
        role = data.role

        try:
            self.logger.error(
                "%s '%s' has crashed (event_id %s), shutting down Hassette, %s",
                role,
                name,
                event.payload.event_id,
                data.exception_traceback,
            )
            await self.hassette.shutdown()
        except Exception as e:
            self.logger.error("Failed to handle %s crash for '%s': %s", role, name, e)
            raise

    async def _on_service_running(self, event: HassetteServiceEvent) -> None:
        """Reset restart budget when a service transitions to RUNNING and becomes ready."""
        data = event.payload.data
        name = data.resource_name
        role = data.role

        key = self._service_key(name, role)
        if key not in self._budgets and key not in self._restarting:
            return

        # Find the service to verify it actually becomes ready (not just RUNNING)
        service = next(
            (c for c in self.hassette.children if c.class_name == name and c.role == role),
            None,
        )
        if service is None:
            return

        # Use per-service startup_timeout_seconds from restart_spec
        spec = service.restart_spec if isinstance(service, Service) else None
        readiness_timeout = spec.startup_timeout_seconds if spec is not None else 30.0

        try:
            await service.wait_ready(timeout=readiness_timeout)
        except TimeoutError:
            self.logger.warning(
                "%s '%s' reached RUNNING but did not become ready within %.1fs",
                role,
                name,
                readiness_timeout,
            )
            # Readiness timeout does NOT affect the restart budget
            return

        self.logger.debug("%s '%s' is running and ready, resetting restart budget", role, name)

        # Reset budget on confirmed recovery
        budget = self._budgets.get(key)
        if budget:
            budget.reset()

        # Clear in-restart flag — restart succeeded
        self._restarting.discard(key)

    async def _reconcile_after_bus_recovery(self) -> None:
        """After BusService recovery, check for services that FAILED during the blind window.

        Services in FAILED state with no budget entry had their FAILED event dropped during
        the BusService restart window. Treat as if a FAILED event had been received.
        """
        self.logger.info("Running post-BusService-recovery reconciliation scan")
        for child in self.hassette.children:
            if not isinstance(child, Service):
                continue
            if child.status != ResourceStatus.FAILED:
                continue

            name = child.class_name
            role = child.role
            key = self._service_key(name, role)

            if key in self._budgets:
                # Already have a budget entry — FAILED event was processed normally
                continue

            self.logger.warning(
                "%s '%s' is in FAILED state but has no budget entry — missed FAILED event during bus restart window, "
                "entering restart flow now",
                role,
                name,
            )

            # Synthesize a FAILED event to re-enter the normal restart flow
            synthetic_event = HassetteServiceEvent(
                topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
                payload=HassettePayload(
                    event_type=str(ResourceStatus.FAILED),
                    data=ServiceStatusPayload(
                        resource_name=name,
                        role=role,
                        status=ResourceStatus.FAILED,
                        previous_status=None,  # unknown — event was missed during BusService restart
                        ready=False,
                        ready_phase=None,
                    ),
                ),
            )
            await self.restart_service(synthetic_event)

    def _register_internal_event_listeners(self) -> None:
        """Register internal event listeners for resource lifecycle."""
        topic = str(Topic.HASSETTE_EVENT_SERVICE_STATUS)
        self.bus.on(
            topic=topic,
            handler=self.restart_service,
            name="hassette.service_watcher.restart_service",
            where=P.ValueIs(source=get_path("payload.data.status"), condition=ResourceStatus.FAILED),
        )
        self.bus.on(
            topic=topic,
            handler=self.shutdown_if_crashed,
            name="hassette.service_watcher.shutdown_if_crashed",
            where=P.ValueIs(source=get_path("payload.data.status"), condition=ResourceStatus.CRASHED),
        )
        self.bus.on(
            topic=topic,
            handler=self.log_service_event,
            name="hassette.service_watcher.log_service_event",
        )
        self.bus.on(
            topic=topic,
            handler=self._on_service_running,
            name="hassette.service_watcher._on_service_running",
            where=P.ValueIs(source=get_path("payload.data.status"), condition=ResourceStatus.RUNNING),
        )
        self.bus.on(
            topic=topic,
            handler=self._on_bus_service_running,
            name="hassette.service_watcher._on_bus_service_running",
            where=P.ValueIs(source=get_path("payload.data.status"), condition=ResourceStatus.RUNNING),
        )

    async def _on_bus_service_running(self, event: HassetteServiceEvent) -> None:
        """Trigger reconciliation scan when BusService recovers."""
        data = event.payload.data
        if data.resource_name != BusService.__name__:
            return
        await self._reconcile_after_bus_recovery()
