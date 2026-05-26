"""WebApiService: runs the FastAPI/uvicorn server."""

import asyncio
import typing
from typing import ClassVar

import uvicorn

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.resources.base import Resource, RestartSpec, Service
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.web.app import create_fastapi_app

if typing.TYPE_CHECKING:
    from hassette import Hassette

_GRACEFUL_SHUTDOWN_TIMEOUT = 3


class WebApiService(Service):
    """Runs the FastAPI/uvicorn server for the web API and healthcheck."""

    depends_on: ClassVar[list[type[Resource]]] = [RuntimeQueryService, TelemetryQueryService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=60,
    )

    host: str
    port: int
    _server: uvicorn.Server | None

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self.host = hassette.config.web_api.host
        self.port = hassette.config.web_api.port
        self._server = None

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.web_api

    async def on_initialize(self) -> None:
        if not self.hassette.config.web_api.run:
            self.logger.warning("Web API service disabled by configuration")
            self.mark_ready(reason="Web API disabled")
            return

        # RuntimeQueryService is guaranteed ready by depends_on auto-wait.
        self.mark_ready(reason="Web API service initialized")

    async def serve(self) -> None:
        if not self.hassette.config.web_api.run:
            await self.shutdown_event.wait()  # stay alive so handle_stop() doesn't undo mark_ready
            return

        app = create_fastapi_app(self.hassette)

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level=self.config_log_level.lower(),
            lifespan="off",
            ws="websockets-sansio",
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_TIMEOUT,
        )
        self._server = uvicorn.Server(config)

        self.logger.info("Web API server starting on %s:%s", self.host, self.port)

        try:
            await self._server.serve()
        except asyncio.CancelledError:
            if self._server.started:
                self._server.should_exit = True
                try:
                    await asyncio.shield(self._server.shutdown())
                except Exception:
                    self.logger.warning("uvicorn shutdown raised during cancellation", exc_info=True)
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
