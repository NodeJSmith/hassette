"""WebApiService: runs the FastAPI/uvicorn server."""

import asyncio
import typing

import uvicorn

from hassette.resources.base import Service
from hassette.web.app import create_fastapi_app

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.resources.base import Resource


class WebApiService(Service):
    """Runs the FastAPI/uvicorn server for the web API and healthcheck."""

    host: str
    port: int
    _server: uvicorn.Server | None

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        inst = cls(hassette=hassette, parent=parent)
        inst.host = hassette.config.web_api_host
        inst.port = hassette.config.web_api_port
        inst._server = None
        return inst

    @property
    def config_log_level(self):
        return self.hassette.config.web_api_log_level

    async def before_initialize(self) -> None:
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
            self.logger.warning("Web API service disabled by configuration")
            self.mark_ready(reason="Web API disabled")
            return

        # Wait for DataSyncService to be ready
        await self.hassette.wait_for_ready([self.hassette._data_sync_service])

        self.mark_ready(reason="Web API service initialized")

    async def serve(self) -> None:
        if not self.hassette.config.run_web_api:
            await self.shutdown_event.wait()  # stay alive so handle_stop() doesn't undo mark_ready
            return

        app = create_fastapi_app(self.hassette)

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level=self.config_log_level.lower(),
            lifespan="off",
        )
        self._server = uvicorn.Server(config)

        self.logger.info("Web API server starting on %s:%s", self.host, self.port)

        try:
            await self._server.serve()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("Web API server encountered an error")
            raise

    async def before_shutdown(self) -> None:
        if self._server is not None:
            self.logger.debug("Signalling Web API server to shut down")
            self._server.should_exit = True

    async def on_shutdown(self) -> None:
        if self._server is not None:
            self.logger.debug("Cleaning up Web API server reference")
            self._server = None
