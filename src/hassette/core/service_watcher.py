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

    @classmethod
    def create(cls, hassette: "Hassette"):
        inst = cls(hassette, parent=hassette)
        inst.bus = inst.add_child(Bus)
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.service_watcher_log_level

    async def on_initialize(self) -> None:
        self._register_internal_event_listeners()
        self.mark_ready(reason="Service watcher initialized")

    async def on_shutdown(self) -> None:
        self.bus.remove_all_listeners()

    async def restart_service(self, event: HassetteServiceEvent) -> None:
        """Start a service from a service event."""
        data = event.payload.data
        name = data.resource_name
        role = data.role

        try:
            if name is None:
                self.logger.warning("No %s specified to start, skipping", role)
                return

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
