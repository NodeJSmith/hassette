import typing

from aiohttp import web

from hassette.core.classes import Service
from hassette.core.enums import ResourceStatus

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


class _HealthService(Service):
    """Tiny HTTP server exposing /healthz for container healthchecks."""

    def __init__(self, hassette: "Hassette", host: str = "0.0.0.0", port: int = 8126):
        super().__init__(hassette)
        self.host = host
        self.port = port

        self._runner: web.AppRunner | None = None

    async def run_forever(self) -> None:
        try:
            app = web.Application()
            hassette_key = web.AppKey["Hassette"]("hassette")
            app[hassette_key] = self.hassette
            app.router.add_get("/healthz", self._handle_health)

            self._runner = web.AppRunner(app)
            await self._runner.setup()
            site = web.TCPSite(self._runner, self.host, self.port)
            await site.start()

            self.logger.info("Health service listening on %s:%s", self.host, self.port)

            # don't send start event until server is running
            await self.handle_start()
            # Just idle until cancelled
            await self.hassette._shutdown_event.wait()
        except Exception as e:
            await self.handle_crash(e)
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self.logger.debug("Health service stopped")
        await self.handle_stop()

    async def _handle_health(self, request: web.Request) -> web.Response:
        # You can check internals here (e.g., WS status)
        ws_running = self.hassette._websocket.status == ResourceStatus.RUNNING
        if ws_running:
            self.logger.debug("Health check OK")
            return web.json_response({"status": "ok", "ws": "connected"})
        self.logger.warning("Health check FAILED: WebSocket disconnected")
        return web.json_response({"status": "degraded", "ws": "disconnected"}, status=503)
