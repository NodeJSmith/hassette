import typing

from aiohttp import web

from hassette.resources.base import Service
from hassette.types.enums import ResourceStatus

if typing.TYPE_CHECKING:
    from hassette import Hassette

_T = typing.TypeVar("_T")


# subclass to prevent the weird UnboundLocalError we get from aiohttp
# i think it's due to pytest but i'm tired of trying to figure it out
# that's why you don't use frame inspections
class MyAppKey(web.AppKey[_T]):
    def __init__(self, name: str, t: type[_T]):
        self._name = __name__ + "." + name
        self._t = t


class HealthService(Service):
    """Tiny HTTP server exposing /healthz for container healthchecks."""

    host: str
    """Host to bind the health server to."""

    port: int
    """Port to bind the health server to."""

    _runner: web.AppRunner | None
    """Aiohttp app runner for the health server."""

    @classmethod
    def create(cls, hassette: "Hassette", host: str = "0.0.0.0", port: int | None = None):
        inst = cls(hassette, parent=hassette)
        inst.host = host
        inst.port = port or hassette.config.health_service_port or 8126
        inst._runner = None

        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.health_service_log_level

    async def serve(self) -> None:
        if not self.hassette.config.run_health_service:
            return

        try:
            # Just idle until cancelled
            await self.shutdown_event.wait()
        except OSError as e:
            error_no = e.errno if hasattr(e, "errno") else type(e)
            self.logger.error("Health service failed to start: %s (errno=%s)", e, error_no)
            raise

    async def before_initialize(self) -> None:
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

    async def on_initialize(self):
        """Start the health HTTP server."""

        if not self.hassette.config.run_health_service:
            self.logger.warning("Health service disabled by configuration")
            # we don't want to fail startup due to "not ready", as this is not unhealthy, just disabled
            self.mark_ready(reason="Health service disabled")
            return

        app = web.Application()
        hassette_key = MyAppKey[HealthService]("health_service", HealthService)
        app[hassette_key] = self
        app.router.add_get("/healthz", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        self.logger.debug("Health service listening on %s:%s", self.host, self.port)

        self.mark_ready(reason="Health service started")

    async def on_shutdown(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self.logger.debug("Health service stopped")

    async def _handle_health(self, request: web.Request) -> web.Response:
        # You can check internals here (e.g., WS status)
        ws_running = self.hassette._websocket_service.status == ResourceStatus.RUNNING
        if ws_running:
            self.logger.debug("Health check OK")
            return web.json_response({"status": "ok", "ws": "connected"})
        self.logger.warning("Health check FAILED: WebSocket disconnected")
        return web.json_response({"status": "degraded", "ws": "disconnected"}, status=503)
