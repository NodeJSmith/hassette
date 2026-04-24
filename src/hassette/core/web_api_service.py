"""WebApiService: runs the FastAPI/uvicorn server."""

import asyncio
import typing
from typing import ClassVar

import uvicorn

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.resources.base import Resource, Service
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.web.app import create_fastapi_app

if typing.TYPE_CHECKING:
    from hassette import Hassette


class WebApiService(Service):
    """Runs the FastAPI/uvicorn server for the web API and healthcheck."""

    depends_on: ClassVar[list[type[Resource]]] = [RuntimeQueryService]

    host: str
    port: int
    _server: uvicorn.Server | None

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self.host = hassette.config.web_api_host
        self.port = hassette.config.web_api_port
        self._server = None

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.web_api_log_level

    async def on_initialize(self) -> None:
        if not self.hassette.config.run_web_api:
            self.logger.warning("Web API service disabled by configuration")
            self.mark_ready(reason="Web API disabled")
            return

        # RuntimeQueryService is guaranteed ready by depends_on auto-wait.
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
