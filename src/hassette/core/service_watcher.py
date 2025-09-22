from .classes import Resource
from .events import HassetteServiceEvent


class _ServiceWatcher(Resource):
    """Watches for service events and handles them."""

    async def initialize(self, *args, **kwargs) -> None:
        self._register_internal_event_listeners()
        return await super().initialize(*args, **kwargs)

    async def restart_service(self, event: HassetteServiceEvent) -> None:
        """Start a service from a service event."""
        data = event.payload.data
        name = data.resource_name
        role = data.role

        try:
            if name is None:
                self.logger.warning("No %s specified to start, skipping", role)
                return

            self.logger.info("%s '%s' is being restarted after '%s'", role, name, event.payload.event_type)

            self.logger.info("Starting %s '%s'", role, name)
            service = self.hassette._resources.get(name)
            if service is None:
                self.logger.warning("No %s found for '%s', skipping start", role, name)
                return

            service.cancel()
            service.start()

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
            self.logger.info(
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
                data.event_id,
                data.exception_traceback,
            )
            self.hassette.shutdown()
        except Exception:
            self.logger.error("Failed to handle %s crash for '%s': %s", role, name)
            raise

    def _register_internal_event_listeners(self) -> None:
        """Register internal event listeners for resource lifecycle."""
        self.hassette.bus.on_hassette_service_failed(handler=self.restart_service)
        self.hassette.bus.on_hassette_service_crashed(handler=self.shutdown_if_crashed)
        self.hassette.bus.on_hassette_service_status(handler=self.log_service_event)
