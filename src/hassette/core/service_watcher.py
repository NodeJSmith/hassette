import asyncio
import time
import typing

from hassette.bus import Bus
from hassette.events import HassetteServiceEvent
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette


class ServiceWatcher(Resource):
    """Watches for service events and handles them."""

    bus: Bus
    """Event bus for inter-service communication."""

    _restart_attempts: dict[str, int]
    """Tracks restart attempt counts per service, keyed by 'name:role'."""

    _last_failure_time: dict[str, float]
    """Tracks the last failure timestamp per service, keyed by 'name:role'."""

    @classmethod
    def create(cls, hassette: "Hassette"):
        inst = cls(hassette, parent=hassette)
        inst.bus = inst.add_child(Bus)
        inst._restart_attempts = {}
        inst._last_failure_time = {}
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.service_watcher_log_level

    async def on_initialize(self) -> None:
        self._restart_attempts = {}
        self._last_failure_time = {}
        self._register_internal_event_listeners()
        self.mark_ready(reason="Service watcher initialized")

    async def on_shutdown(self) -> None:
        self.bus.remove_all_listeners()

    @staticmethod
    def _service_key(name: str, role: object) -> str:
        return f"{name}:{role}"

    async def restart_service(self, event: HassetteServiceEvent) -> None:
        """Restart a failed service with exponential backoff and a retry limit."""
        data = event.payload.data
        name = data.resource_name
        role = data.role

        try:
            if name is None:
                self.logger.warning("No %s specified to start, skipping", role)
                return

            key = self._service_key(name, role)
            config = self.hassette.config
            max_attempts = config.service_restart_max_attempts
            attempts = self._restart_attempts.get(key, 0)

            if attempts >= max_attempts:
                self.logger.error(
                    "%s '%s' has failed %d times (max %d), not restarting",
                    role,
                    name,
                    attempts,
                    max_attempts,
                )
                return

            # Calculate exponential backoff
            backoff = min(
                config.service_restart_backoff_seconds * (config.service_restart_backoff_multiplier**attempts),
                config.service_restart_max_backoff_seconds,
            )

            # Increment attempt counter BEFORE restarting. The serve task runs
            # asynchronously, so restart() returns before serve() has a chance
            # to fail. The counter persists for the process lifetime.
            self._restart_attempts[key] = attempts + 1

            if backoff > 0:
                self.logger.info(
                    "%s '%s' restart attempt %d/%d, waiting %.1fs",
                    role,
                    name,
                    attempts + 1,
                    max_attempts,
                    backoff,
                )
                await asyncio.sleep(backoff)

            self.logger.debug("%s '%s' is being restarted after '%s'", role, name, event.payload.event_type)

            services = [child for child in self.hassette.children if child.class_name == name and child.role == role]
            if not services:
                self.logger.warning("No %s found for '%s', skipping start", role, name)
                return
            if len(services) > 1:
                self.logger.warning("Multiple %s found for '%s', restarting all", role, name)

            self.logger.debug("Restarting %s '%s'", role, name)
            for service in services:
                await service.restart()

        except Exception as e:
            key = self._service_key(name, role) if name else "unknown"
            self._last_failure_time[key] = time.monotonic()
            self.logger.error("Failed to restart %s '%s': %s", role, name, e)
            raise

    async def log_service_event(self, event: HassetteServiceEvent) -> None:
        """Log the startup of a service."""

        name = event.payload.data.resource_name
        role = event.payload.data.role

        if name is None:
            self.logger.warning("No resource specified for startup, cannot log")
            return

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
            self.logger.exception(
                "%s '%s' has crashed (event_id %d), shutting down Hassette, %s",
                role,
                name,
                event.payload.event_id,
                data.exception_traceback,
            )
            await self.hassette.shutdown()
        except Exception:
            self.logger.error("Failed to handle %s crash for '%s': %s", role, name)
            raise

    def _register_internal_event_listeners(self) -> None:
        """Register internal event listeners for resource lifecycle."""
        self.bus.on_hassette_service_failed(handler=self.restart_service)
        self.bus.on_hassette_service_crashed(handler=self.shutdown_if_crashed)
        self.bus.on_hassette_service_status(handler=self.log_service_event)
