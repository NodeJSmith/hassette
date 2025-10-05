import typing

from aiohttp import web

from .classes.resource import Service
from .enums import ResourceStatus

if typing.TYPE_CHECKING:
    from .core import Hassette

_T = typing.TypeVar("_T")


# subclass to prevent the weird UnboundLocalError we get from aiohttp
# i think it's due to pytest but i'm tired of trying to figure it out
# that's why you don't use frame inspections
class MyAppKey(web.AppKey[_T]):
    def __init__(self, name: str, t: type[_T]):
        self._name = __name__ + "." + name
        self._t = t


class _HealthService(Service):
    """Tiny HTTP server exposing /healthz for container healthchecks."""

    def __init__(self, hassette: "Hassette", host: str = "0.0.0.0", port: int | None = None):
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.health_service_log_level)

        self.host = host
        self.port = port or hassette.config.health_service_port

        self._runner: web.AppRunner | None = None

    async def run_forever(self) -> None:
        if not self.hassette.config.run_health_service:
            self.logger.info("Health service disabled by configuration")
            return

        try:
            async with self.starting():
                await self.startup()

            # Just idle until cancelled
            await self.hassette.shutdown_event.wait()
        except OSError as e:
            error_no = e.errno if hasattr(e, "errno") else type(e)
            self.logger.error("Health service failed to start: %s (errno=%s)", e, error_no)
            await self.handle_failed(e)
            raise
        except Exception as e:
            await self.handle_crash(e)
            raise
        finally:
            await self.cleanup()

    async def startup(self):
        """Start the health HTTP server."""
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()
        app = web.Application()
        hassette_key = MyAppKey[_HealthService]("health_service", _HealthService)
        app[hassette_key] = self
        app.router.add_get("/healthz", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        self.logger.info("Health service listening on %s:%s", self.host, self.port)

        self.mark_ready(reason="Health service started")

    async def shutdown(self, *args, **kwargs) -> None:
        await self.cleanup()
        return await super().shutdown(*args, **kwargs)

    async def cleanup(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self.logger.debug("Health service stopped")
        if self.status != ResourceStatus.STOPPED:
            await self.handle_stop()

        await super().cleanup()

    async def _handle_health(self, request: web.Request) -> web.Response:
        # You can check internals here (e.g., WS status)
        ws_running = self.hassette._websocket.status == ResourceStatus.RUNNING
        if ws_running:
            self.logger.debug("Health check OK")
            return web.json_response({"status": "ok", "ws": "connected"})
        self.logger.warning("Health check FAILED: WebSocket disconnected")
        return web.json_response({"status": "degraded", "ws": "disconnected"}, status=503)
