import typing

from aiohttp import web

from hassette.core.classes import Service
from hassette.core.enums import ResourceStatus

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


class _HealthService(Service):
    """Tiny HTTP server exposing /healthz for container healthchecks."""

    def __init__(self, hassette: "Hassette", host: str = "0.0.0.0", port: int | None = None):
        super().__init__(hassette)
        self.host = host
        self.port = port or hassette.config.health_service_port

        self._runner: web.AppRunner | None = None

    async def run_forever(self) -> None:
        if not self.hassette.config.run_health_service:
            self.logger.info("Health service disabled by configuration")
            return

        try:
            app = web.Application()
            try:
                hassette_key = web.AppKey["Hassette"]("hassette")
            except UnboundLocalError:
                # seen in tests, unsure if it happens in production
                hassette_key = "hassette"

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
        except OSError as e:
            error_no = e.errno if hasattr(e, "errno") else type(e)
            self.logger.error("Health service failed to start: %s (errno=%s)", e, error_no)
            await self.handle_failed(e)
            raise
        except Exception as e:
            await self.handle_crash(e)
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self.logger.debug("Health service stopped")
        if self.status != ResourceStatus.STOPPED:
            await self.handle_stop()

    async def _handle_health(self, request: web.Request) -> web.Response:
        # You can check internals here (e.g., WS status)
        ws_running = self.hassette._websocket.status == ResourceStatus.RUNNING
        if ws_running:
            self.logger.debug("Health check OK")
            return web.json_response({"status": "ok", "ws": "connected"})
        self.logger.warning("Health check FAILED: WebSocket disconnected")
        return web.json_response({"status": "degraded", "ws": "disconnected"}, status=503)
