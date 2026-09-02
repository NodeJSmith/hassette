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
from hassette.exceptions import RestartRefusedError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import create_service_status_event, mark_ready, request_shutdown
from hassette.resources.operations import restart
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types import ResourceRole, ResourceStatus, Topic
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import Hassette

SERVICE_STATUS_PATH = "payload.data.status"


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
        self.evict_expired()
        return len(self._timestamps) >= self._intensity

    def current_attempts(self) -> int:
        """Return the number of restarts within the current window."""
        self.evict_expired()
        return len(self._timestamps)

    def reset(self) -> None:
        """Clear all recorded restart timestamps."""
        self._timestamps.clear()

    def evict_expired(self) -> None:
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
        return self.hassette.config.logging.service_watcher

    async def on_initialize(self) -> None:
        self._budgets = {}
        self._restarting = set()
        self._cooldown_tasks = {}
        self._cooldown_cycles = {}
        await self.register_internal_event_listeners()
        mark_ready(self, reason="Service watcher initialized")

    @staticmethod
    def service_key(name: str, role: ResourceRole) -> str:
        return f"{name}:{role}"

    def get_service(self, name: str, role: ResourceRole) -> Service | None:
        """Return the Service child matching name/role, or None if there is no match.

        Hassette rejects duplicate child *types* at construction (see the
        `type_counts`/`duplicates` check in `Hassette.__init__`, core.py). Since
        `class_name` is set to `type(self).__name__` and `role` is a fixed
        `ClassVar` per subclass, at most one instance of a given type can ever
        exist in `hassette.children`, so (class_name, role) identifies at most
        one service.
        """
        return next(
            (c for c in self.hassette.children if isinstance(c, Service) and c.class_name == name and c.role == role),
            None,
        )

    def get_budget(self, key: str, spec: RestartSpec) -> RestartBudget:
        """Return existing budget for key or create a new one from spec."""
        if key not in self._budgets:
            self._budgets[key] = RestartBudget(spec.budget_intensity, spec.budget_period_seconds)
        return self._budgets[key]

    def set_service_status(
        self, name: str, role: ResourceRole, status: ResourceStatus, context: str | None = None
    ) -> None:
        """Find the service by name/role and set its status, warning if not found."""
        service = self.get_service(name, role)
        if service is None:
            label = context if context is not None else status.name
            self.logger.warning("No %s found for '%s' after %s, skipping status set", role, name, label)
            return
        service.status = status

    async def shutdown_safe_sleep(self, duration: float) -> bool:
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

    def emit_service_status_event(
        self,
        name: str,
        role: ResourceRole,
        status: ResourceStatus,
        previous_status: ResourceStatus,
        source_payload: ServiceStatusPayload | None = None,
        retry_at: float | None = None,
    ) -> HassetteServiceEvent:
        """Build a HassetteServiceEvent for a service status transition."""
        return HassetteServiceEvent(
            topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
            payload=HassettePayload(
                # ready=False is always correct for ServiceWatcher-synthesized events: this method
                # only fires for CRASHED/EXHAUSTED states where the service loop has already exited.
                data=ServiceStatusPayload(
                    resource_name=name,
                    role=role,
                    status=status,
                    previous_status=previous_status,
                    exception=source_payload.exception if source_payload else None,
                    exception_type=source_payload.exception_type if source_payload else None,
                    exception_traceback=source_payload.exception_traceback if source_payload else None,
                    retry_at=retry_at,
                    ready=False,
                    ready_phase=None,
                ),
            ),
        )

    def restart_admission_blocked(self) -> bool:
        """Return True when a fatal reason has been recorded or root shutdown has been requested.

        Checked at entry to ``restart_service()``, ``execute_restart()``, and
        ``cooldown_and_retry()``, and again immediately before every ``restart()`` call in the
        latter two, so a delayed retry or cooldown-continuation task started before a refusal
        landed cannot race past the process-latched fatal state after it lands. This closes the
        race without a second watcher state machine — the same process-latched
        ``fatal_shutdown_reason``/``shutdown_event`` state that ``handle_restart_refused()``
        writes is what every admission check reads.
        """
        return self.hassette.fatal_shutdown_reason is not None or self.hassette.shutdown_event.is_set()

    def log_if_admission_blocked(self, name: str | None, role: ResourceRole | None, action: str) -> bool:
        """Return True and log at debug level if restart admission is currently blocked.

        Shared by the admission checks in ``restart_service()`` (entry), ``cooldown_and_retry()``
        (entry and its post-sleep re-check), and ``execute_restart()`` (entry and its
        post-backoff re-check) so all five near-identical inline blocks share one log format.
        ``action`` is a short phrase naming what step is being skipped (e.g. "restart_service",
        "cooldown").
        """
        if not self.restart_admission_blocked():
            return False
        if name is not None and role is not None:
            self.logger.debug(
                "%s '%s' restart admission blocked (fatal reason or shutdown requested), skipping %s",
                role,
                name,
                action,
            )
        else:
            self.logger.debug("Restart admission blocked (fatal reason or shutdown requested), skipping %s", action)
        return True

    async def handle_restart_refused(self, name: str, role: ResourceRole, error: RestartRefusedError) -> None:
        """Escalate a typed restart refusal to one fatal outcome.

        Records the fatal reason synchronously at this decision site (same race-safe pattern as
        ``handle_exhaustion``'s PERMANENT branch — see its comment: the CRASHED event dispatched
        below is handled asynchronously, so relying on ``shutdown_if_crashed`` alone would race
        any caller reading ``fatal_shutdown_reason``). Requests shutdown via ``request_shutdown()``
        rather than calling ``hassette.shutdown()`` inline, so ``run_forever()`` owns root
        teardown and fatal-exit behavior instead of this handler racing it. The CRASHED event is
        best-effort and sent last — event dispatch is telemetry, not the control path, so its
        failure is logged and does not undo the already-recorded fatal reason or shutdown
        request. Callers hold ``_restarting`` until this coroutine returns, so no retry or
        cooldown scheduling can observe a half-completed refusal.
        """
        reason = f"{role} '{name}' restart refused: {error}"
        self.logger.error("%s '%s' restart refused, escalating to fatal shutdown: %s", role, name, error)
        self.hassette.record_fatal_reason(reason)
        request_shutdown(self.hassette, reason)

        crashed_event = HassetteServiceEvent.from_service_status(
            resource_name=name,
            role=role,
            status=ResourceStatus.CRASHED,
            previous_status=ResourceStatus.FAILED,
            exception=error,
            ready=False,
        )
        try:
            await self.hassette.send_event(crashed_event)
        except Exception as exc:
            self.logger.error("%s '%s' failed to dispatch CRASHED event after restart refusal: %s", role, name, exc)

    async def handle_exhaustion(
        self,
        name: str,
        role: ResourceRole,
        key: str,
        spec: RestartSpec,
        status_payload: ServiceStatusPayload,
    ) -> None:
        """Handle budget exhaustion according to restart_type."""
        if spec.restart_type == RestartType.PERMANENT:
            self.logger.error(
                "%s '%s' restart budget exhausted (PERMANENT), emitting CRASHED and shutting down",
                role,
                name,
            )
            # Record the fatal reason synchronously at the decision site so run_forever()
            # exits non-zero. The CRASHED event is dispatched asynchronously (task-per-handler),
            # so relying on shutdown_if_crashed alone would race the inline shutdown() below.
            self.hassette.record_fatal_reason(f"{role} '{name}' restart budget exhausted (PERMANENT)")
            crashed_event = self.emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.CRASHED,
                previous_status=ResourceStatus.FAILED,
                source_payload=status_payload,
            )
            await self.hassette.send_event(crashed_event)
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
            cooling_event = self.emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.EXHAUSTED_COOLING,
                previous_status=ResourceStatus.FAILED,
                source_payload=status_payload,
                retry_at=retry_at,
            )
            await self.hassette.send_event(cooling_event)
            self.set_service_status(name, role, ResourceStatus.EXHAUSTED_COOLING)
            # Cancel existing cooldown for this service if any
            existing = self._cooldown_tasks.get(key)
            if existing and not existing.done():
                existing.cancel()
            cooldown_task = self.task_bucket.spawn(
                self.cooldown_and_retry(name, role, key, spec),
                name=f"service_watcher:cooldown:{key}",
            )
            self._cooldown_tasks[key] = cooldown_task

        else:  # TEMPORARY
            self.logger.warning(
                "%s '%s' restart budget exhausted (TEMPORARY), marking as EXHAUSTED_DEAD",
                role,
                name,
            )
            dead_event = self.emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.EXHAUSTED_DEAD,
                previous_status=ResourceStatus.FAILED,
                source_payload=status_payload,
            )
            await self.hassette.send_event(dead_event)
            self.set_service_status(name, role, ResourceStatus.EXHAUSTED_DEAD)

    async def cooldown_and_retry(self, name: str, role: ResourceRole, key: str, spec: RestartSpec) -> None:
        """Long-cooldown sleep followed by budget reset and restart attempt.

        Tracks cooldown cycles. If max_cooldown_cycles is exceeded, transitions to EXHAUSTED_DEAD.
        """
        if self.log_if_admission_blocked(name, role, "cooldown"):
            return

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
            dead_event = self.emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.EXHAUSTED_DEAD,
                previous_status=ResourceStatus.EXHAUSTED_COOLING,
            )
            await self.hassette.send_event(dead_event)
            self.set_service_status(name, role, ResourceStatus.EXHAUSTED_DEAD, "cooldown cycle limit")
            return

        self.logger.info(
            "%s '%s' in cooldown for %.1fs (cycle %d)",
            role,
            name,
            spec.cooldown_seconds,
            cycle,
        )

        completed = await self.shutdown_safe_sleep(spec.cooldown_seconds)
        if not completed or self.hassette.shutdown_event.is_set():
            self.logger.debug("%s '%s' cooldown aborted (shutdown requested)", role, name)
            return

        # Admission check before the budget reset and the restart() call below — nothing async
        # happens between here and restart(), so one check immediately upstream of both is
        # sufficient to close the delayed-task race for both effects. A fatal reason or root
        # shutdown request recorded during the cooldown sleep must stop the budget reset too,
        # not just the restart attempt.
        if self.log_if_admission_blocked(name, role, "budget reset and restart (after cooldown sleep)"):
            return

        # Reset budget and attempt restart
        budget = self._budgets.get(key)
        if budget:
            budget.reset()

        service = self.get_service(name, role)
        if service is None:
            self.logger.warning("No %s found for '%s' after cooldown, skipping restart", role, name)
            return

        self.logger.info("%s '%s' cooldown complete, attempting restart", role, name)
        try:
            await restart(service)
        except RestartRefusedError as exc:
            await self.handle_restart_refused(name, role, exc)
        except Exception as exc:
            self.logger.error("%s '%s' restart after cooldown failed: %s", role, name, exc)

    async def restart_service(self, event: HassetteServiceEvent) -> None:
        """Restart a failed service using per-service RestartSpec-driven behavior."""
        if self.log_if_admission_blocked(None, None, "restart_service"):
            return

        status_payload = event.payload.data
        name = status_payload.resource_name
        role = status_payload.role

        key = self.service_key(name, role)

        # Resolve the service and its restart_spec
        service = self.get_service(name, role)
        if service is None:
            self.logger.warning("No %s found for '%s', skipping restart", role, name)
            return

        spec = service.restart_spec

        # Step 1: Check fatal errors — immediate shutdown regardless of restart type
        if status_payload.exception_type and status_payload.exception_type in spec.fatal_error_names:
            self.logger.error(
                "%s '%s' raised fatal error '%s', triggering immediate shutdown",
                role,
                name,
                status_payload.exception_type,
            )
            # Record the fatal reason synchronously (see handle_exhaustion for rationale).
            self.hassette.record_fatal_reason(f"{role} '{name}' raised fatal error '{status_payload.exception_type}'")
            crashed_event = self.emit_service_status_event(
                name=name,
                role=role,
                status=ResourceStatus.CRASHED,
                previous_status=ResourceStatus.FAILED,
                source_payload=status_payload,
            )
            await self.hassette.send_event(crashed_event)
            await self.hassette.shutdown()
            return

        # Step 2: Check non-retryable errors — skip restart, go to exhaustion handling
        if status_payload.exception_type and status_payload.exception_type in spec.non_retryable_error_names:
            self.logger.warning(
                "%s '%s' raised non-retryable error '%s', skipping restart",
                role,
                name,
                status_payload.exception_type,
            )
            await self.handle_exhaustion(name, role, key, spec, status_payload)
            return

        # Step 3: In-restart guard — prevent double budget depletion from concurrent FAILED events.
        # Always drop while a restart is in progress: the budget's exhausted/not-exhausted state
        # alone cannot tell whether this event is the in-flight attempt's own failure or a
        # duplicate/redelivery of the original failure that started this attempt — record_restart()
        # for the current attempt already ran at Step 5, so is_exhausted() reads the same either
        # way. The in-flight attempt's own failure is instead detected directly and unambiguously
        # in execute_restart()'s own exception handler, which cannot race this guard because it
        # runs on the same task that owns `_restarting` for this key.
        if key in self._restarting:
            self.logger.debug(
                "%s '%s' restart already in progress, dropping duplicate FAILED event",
                role,
                name,
            )
            return

        # Step 4: Check budget exhaustion
        budget = self.get_budget(key, spec)
        if budget.is_exhausted():
            # Clear any stale in-restart state before handling exhaustion
            self._restarting.discard(key)
            await self.handle_exhaustion(name, role, key, spec, status_payload)
            return

        # Step 5: Mark in-restart and record the restart
        self._restarting.add(key)
        budget.record_restart()

        # Spawn the backoff + restart as a detached task so this handler returns
        # immediately and releases its dispatch semaphore slot.
        self.task_bucket.spawn(
            self.execute_restart(name, role, key, spec, service, budget),
            name=f"service_watcher:restart:{key}",
        )

    async def execute_restart(
        self,
        name: str,
        role: ResourceRole,
        key: str,
        spec: RestartSpec,
        service: Service,
        budget: RestartBudget,
    ) -> None:
        """Execute backoff sleep and service restart (runs as a detached task)."""
        attempts = budget.current_attempts()

        # Step 6: Apply exponential backoff with shutdown-safe sleep
        backoff = min(
            spec.backoff_base_seconds * (spec.backoff_multiplier ** (attempts - 1)),
            spec.backoff_max_seconds,
        )

        try:
            if self.log_if_admission_blocked(name, role, "backoff and restart"):
                return

            if backoff > 0:
                self.logger.info(
                    "%s '%s' restarting (attempt %d, waiting %.1fs)",
                    role,
                    name,
                    attempts,
                    backoff,
                )
                completed = await self.shutdown_safe_sleep(backoff)
                if not completed or self.hassette.shutdown_event.is_set():
                    self.logger.debug("%s '%s' backoff sleep aborted (shutdown requested)", role, name)
                    return

            self.logger.debug("%s '%s' is being restarted", role, name)

            # Admission check again, immediately before the restart() call — the backoff sleep
            # above is an await point where a refusal on another service key (or a fatal error)
            # could have landed since the entry check.
            if self.log_if_admission_blocked(name, role, "restart (after backoff)"):
                return

            if service.shutting_down:
                self.logger.debug(
                    "%s '%s' was already mid-shutdown for an unrelated reason when the watcher's "
                    "backoff sleep ended -- restart() will join that in-flight attempt",
                    role,
                    name,
                )

            # Step 7: Restart the service — catch and log exceptions, do NOT double-count budget.
            # Clear the in-restart guard in the finally so concurrent FAILED events cannot enter
            # restart_service() while the restart is still in progress.
            try:
                await restart(service)
            except RestartRefusedError as exc:
                await self.handle_restart_refused(name, role, exc)
            except Exception as exc:
                self.logger.error(
                    "%s '%s' restart raised an exception (service left in FAILED state): %s",
                    role,
                    name,
                    exc,
                )
                # This is the attempt's own failure, observed directly on the task that owns
                # `_restarting` for this key -- not inferred from a FAILED event racing back
                # through the bus (see Step 3's guard). Check exhaustion here, unambiguously.
                if budget.is_exhausted():
                    self.logger.debug(
                        "%s '%s' restart attempt failed and budget exhausted, handling exhaustion",
                        role,
                        name,
                    )
                    self._restarting.discard(key)
                    status_event = create_service_status_event(service, ResourceStatus.FAILED, exc)
                    await self.handle_exhaustion(name, role, key, spec, status_event.payload.data)
        finally:
            self._restarting.discard(key)

    async def log_service_event(self, event: HassetteServiceEvent) -> None:
        status_payload = event.payload.data
        name = status_payload.resource_name
        role = status_payload.role
        status = status_payload.status
        previous_status = status_payload.previous_status

        if status == previous_status:
            self.logger.debug("%s '%s' status unchanged at '%s', not logging", role, name, status)
            return

        self.logger.debug(
            "%s '%s' transitioned to status '%s' from '%s'",
            role,
            name,
            status,
            previous_status,
        )

    async def shutdown_if_crashed(self, event: HassetteServiceEvent) -> None:
        """Record the fatal reason and request shutdown when a service has crashed.

        Universal reaction to a CRASHED event from any source. Records the fatal reason
        (unless a more specific one is already set) before calling request_shutdown() so
        run_forever()'s shutdown_event.wait() unblocks, runs the full teardown (including
        finalize_session), and then raises FatalError via _raise_if_fatal_shutdown(). This
        makes a crash-driven exit non-zero to external supervisors (systemd Restart=on-failure,
        Docker healthcheck).
        """
        status_payload = event.payload.data
        name = status_payload.resource_name
        role = status_payload.role

        try:
            self.logger.error(
                "%s '%s' has crashed (event_id %s), shutting down Hassette, %s",
                role,
                name,
                event.payload.event_id,
                status_payload.exception_traceback,
            )
            reason = f"{role} '{name}' crashed"
            if status_payload.exception_type:
                reason += f": {status_payload.exception_type}"
            self.hassette.record_fatal_reason(reason)
            request_shutdown(self.hassette, reason)
        except Exception as exc:
            self.logger.error("Failed to handle %s crash for '%s': %s", role, name, exc)
            raise

    async def on_service_running(self, event: HassetteServiceEvent) -> None:
        """Reset restart budget when a service transitions to RUNNING and becomes ready."""
        status_payload = event.payload.data
        name = status_payload.resource_name
        role = status_payload.role

        key = self.service_key(name, role)
        if key not in self._budgets and key not in self._restarting:
            return

        # Find the service to verify it actually becomes ready (not just RUNNING).
        # See get_service() for why (class_name, role) resolves to at most one match.
        service = self.get_service(name, role)
        if service is None:
            return

        # Use per-service startup_timeout_seconds from restart_spec
        readiness_timeout = service.restart_spec.startup_timeout_seconds

        # Spawn readiness check as a detached task so this handler returns
        # immediately and releases its dispatch semaphore slot.
        self.task_bucket.spawn(
            self.await_service_readiness(service, name, role, key, readiness_timeout),
            name=f"service_watcher:readiness:{key}",
        )

    async def await_service_readiness(
        self,
        service: Service,
        name: str,
        role: ResourceRole,
        key: str,
        readiness_timeout: float,
    ) -> None:
        """Wait for a restarted service to become ready and reset its budget (runs as a detached task)."""
        try:
            await service.wait_ready(timeout=readiness_timeout)
        except TimeoutError:
            self.logger.warning(
                "%s '%s' reached RUNNING but did not become ready within %.1fs",
                role,
                name,
                readiness_timeout,
            )
            return

        self.logger.debug("%s '%s' is running and ready, resetting restart budget", role, name)

        budget = self._budgets.get(key)
        if budget:
            budget.reset()

        self._restarting.discard(key)

    async def reconcile_after_bus_recovery(self) -> None:
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
            key = self.service_key(name, role)

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

    async def register_internal_event_listeners(self) -> None:
        """Register internal event listeners for resource lifecycle."""
        topic = str(Topic.HASSETTE_EVENT_SERVICE_STATUS)
        await self.bus.on(
            topic=topic,
            handler=self.restart_service,
            name="hassette.service_watcher.restart_service",
            where=P.ValueIs(source=get_path(SERVICE_STATUS_PATH), condition=ResourceStatus.FAILED),
        )
        await self.bus.on(
            topic=topic,
            handler=self.shutdown_if_crashed,
            name="hassette.service_watcher.shutdown_if_crashed",
            where=P.ValueIs(source=get_path(SERVICE_STATUS_PATH), condition=ResourceStatus.CRASHED),
        )
        await self.bus.on(
            topic=topic,
            handler=self.log_service_event,
            name="hassette.service_watcher.log_service_event",
        )
        await self.bus.on(
            topic=topic,
            handler=self.on_service_running,
            name="hassette.service_watcher.on_service_running",
            where=P.ValueIs(source=get_path(SERVICE_STATUS_PATH), condition=ResourceStatus.RUNNING),
        )
        await self.bus.on(
            topic=topic,
            handler=self.on_bus_service_running,
            name="hassette.service_watcher.on_bus_service_running",
            where=P.ValueIs(source=get_path(SERVICE_STATUS_PATH), condition=ResourceStatus.RUNNING),
        )

    async def on_bus_service_running(self, event: HassetteServiceEvent) -> None:
        """Trigger reconciliation scan when BusService recovers."""
        status_payload = event.payload.data
        if status_payload.resource_name != BusService.__name__:
            return
        await self.reconcile_after_bus_recovery()
