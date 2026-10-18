"""Escalation and terminal-outcome handling for ``ServiceWatcher``, as a mixin."""

import asyncio
import time
import typing

from hassette_wire import ResourceRole, ResourceStatus

from hassette.events import HassetteServiceEvent
from hassette.events.hassette import ServiceStatusPayload
from hassette.exceptions import RestartRefusedError
from hassette.resources.lifecycle import request_shutdown
from hassette.resources.operations import restart
from hassette.resources.restart import RestartSpec
from hassette.types.enums import RestartType

if typing.TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

    from hassette import Hassette, TaskBucket
    from hassette.core.restart_budget import RestartBudget
    from hassette.resources.service import Service


class ServiceEscalationMixin:
    """Budget-exhaustion, cooldown, refusal, and unretryable-failure handling of ``ServiceWatcher``.

    Reads the host attributes and calls the host methods declared below.
    """

    hassette: "Hassette"
    logger: "logging.Logger"
    task_bucket: "TaskBucket"
    _budgets: "dict[str, RestartBudget]"
    _cooldown_tasks: dict[str, asyncio.Task]
    _cooldown_cycles: dict[str, int]

    emit_service_status_event: "Callable[..., HassetteServiceEvent]"
    dispatch_status_event_best_effort: "Callable[[str, ResourceRole, HassetteServiceEvent], Awaitable[None]]"
    set_service_status: "Callable[..., None]"
    get_service: "Callable[[str, ResourceRole], Service | None]"
    log_if_admission_blocked: "Callable[[str | None, ResourceRole | None, str], bool]"
    shutdown_safe_sleep: "Callable[[float], Awaitable[bool]]"

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
        await self.dispatch_status_event_best_effort(name, role, crashed_event)

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
            await self.dispatch_failed_transition(name, role, ResourceStatus.CRASHED, status_payload)
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
            await self.dispatch_failed_transition(
                name, role, ResourceStatus.EXHAUSTED_COOLING, status_payload, retry_at=retry_at
            )
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
            await self.dispatch_failed_transition(name, role, ResourceStatus.EXHAUSTED_DEAD, status_payload)
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
            await self.dispatch_status_event_best_effort(name, role, dead_event)
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
        # A failed cooldown attempt is retried by the FAILED event it produces, which starts a
        # fresh episode against the budget reset above -- not by a loop here.
        try:
            await restart(service)
        except RestartRefusedError as exc:
            await self.handle_restart_refused(name, role, exc)
        except Exception as exc:
            self.logger.error("%s '%s' restart after cooldown failed: %s", role, name, exc)

    async def route_unretryable_failure(
        self,
        name: str,
        role: ResourceRole,
        key: str,
        spec: RestartSpec,
        status_payload: ServiceStatusPayload,
    ) -> bool:
        """Route a failure whose exception type the spec says must not be retried.

        A fatal error shuts the process down regardless of restart type; a non-retryable error goes
        straight to exhaustion handling. Applies both to a failure carried by a FAILED event and to
        one a restart attempt raises inside an episode, whose own FAILED event is dropped.

        Returns:
            True if the failure was routed (the caller must not restart), False if it is retryable.
        """
        exception_type = status_payload.exception_type
        if exception_type and exception_type in spec.fatal_error_names:
            self.logger.error(
                "%s '%s' raised fatal error '%s', triggering immediate shutdown", role, name, exception_type
            )
            # Record the fatal reason synchronously (see handle_exhaustion for rationale).
            self.hassette.record_fatal_reason(f"{role} '{name}' raised fatal error '{exception_type}'")
            await self.dispatch_failed_transition(name, role, ResourceStatus.CRASHED, status_payload)
            await self.hassette.shutdown()
            return True

        if exception_type and exception_type in spec.non_retryable_error_names:
            self.logger.warning("%s '%s' raised non-retryable error '%s', skipping restart", role, name, exception_type)
            await self.handle_exhaustion(name, role, key, spec, status_payload)
            return True

        return False

    async def dispatch_failed_transition(
        self,
        name: str,
        role: ResourceRole,
        status: ResourceStatus,
        status_payload: ServiceStatusPayload,
        retry_at: float | None = None,
    ) -> None:
        """Best-effort dispatch of a FAILED -> ``status`` event carrying ``status_payload``'s exception fields."""
        event = self.emit_service_status_event(
            name=name,
            role=role,
            status=status,
            previous_status=ResourceStatus.FAILED,
            source_payload=status_payload,
            retry_at=retry_at,
        )
        await self.dispatch_status_event_best_effort(name, role, event)
