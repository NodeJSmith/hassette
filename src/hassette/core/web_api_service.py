"""WebApiService: runs the FastAPI/uvicorn server."""

import asyncio
import typing
from typing import ClassVar

import uvicorn
from fastapi import FastAPI

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.exceptions import FatalError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.scheduler import Scheduler
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.net_utils import is_loopback_host
from hassette.web.app import create_fastapi_app
from hassette.web.auth import (
    EMPTY_TRUSTED_PROXY_SET,
    TrustedProxySet,
    refresh_trusted_proxies,
    resolve_auth_token,
    resolve_trusted_proxies,
)

if typing.TYPE_CHECKING:
    from hassette import Hassette

_GRACEFUL_SHUTDOWN_TIMEOUT = 3

_TRUSTED_PROXY_REFRESH_INTERVAL_MINUTES = 5
"""How often trusted_proxies hostname entries are re-resolved via DNS."""

_TRUSTED_PROXY_REFRESH_JOB_NAME = "web_api_trusted_proxy_refresh"


class WebApiService(Service):
    """Runs the FastAPI/uvicorn server for the web API and healthcheck."""

    depends_on: ClassVar[list[type[Resource]]] = [RuntimeQueryService, TelemetryQueryService, SchedulerService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=60,
    )

    host: str
    port: int
    scheduler: Scheduler
    _server: uvicorn.Server | None
    _app: FastAPI | None
    _resolved_auth_token: str | None
    _trusted_proxies: TrustedProxySet

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self.host = hassette.config.web_api.host
        self.port = hassette.config.web_api.port
        self._server = None
        self._app = None
        self._resolved_auth_token = None
        self._trusted_proxies = EMPTY_TRUSTED_PROXY_SET
        self.scheduler = self.add_child(Scheduler)

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.web_api

    async def on_initialize(self) -> None:
        if not self.hassette.config.web_api.run:
            self.logger.warning("Web API service disabled by configuration")
            mark_ready(self, reason="Web API disabled")
            return

        web_api_config = self.hassette.config.web_api
        loopback = is_loopback_host(web_api_config.host)

        # Hard block: an explicitly-disabled auth on a non-loopback bind would serve an
        # unauthenticated API to any network peer that can reach the port.
        if not web_api_config.auth_enabled and not loopback:
            raise FatalError(
                f"Cannot start Web API with auth_enabled=False and host={web_api_config.host!r}. "
                "Disabling auth_enabled requires host to be a loopback address (127.0.0.1, ::1, or "
                "localhost) — otherwise the API would be unauthenticated for any network peer that "
                "can reach the port. Set auth_enabled=True, or bind host to a loopback address."
            )

        # Warning only: no evidence of a fronting proxy, so hassette cannot detect whether TLS is
        # terminated anywhere in front of it. Auth (token/cookie) still protects the API — this is
        # about transport security, not authentication.
        if not loopback and not web_api_config.trusted_proxies:
            self.logger.warning(
                "Web API is bound to non-loopback host %r with no trusted_proxies configured. "
                "Hassette has no TLS support of its own — if this instance is reachable from an "
                "untrusted network, put a TLS-terminating reverse proxy in front of it.",
                web_api_config.host,
            )

        # Neither DefaultDenyMiddleware nor authorize_ws ever consults the resolved token or
        # trusted_proxies when auth is disabled (both bypass entirely on auth_enabled=False) — so
        # resolving/writing them here would be pure overhead, and could even fail startup
        # (AuthTokenWriteError, TrustedProxyConfigError) for machinery this run never uses.
        if web_api_config.auth_enabled:
            self._resolved_auth_token = resolve_auth_token(web_api_config, self.hassette.config.data_dir)

            self._trusted_proxies = await resolve_trusted_proxies(web_api_config.trusted_proxies)
            await self.scheduler.run_every(
                self._refresh_trusted_proxies,
                minutes=_TRUSTED_PROXY_REFRESH_INTERVAL_MINUTES,
                name=_TRUSTED_PROXY_REFRESH_JOB_NAME,
                if_exists="skip",
                mode="single",
            )

        # RuntimeQueryService, TelemetryQueryService, and SchedulerService are guaranteed ready
        # by depends_on auto-wait.
        mark_ready(self, reason="Web API service initialized")

    async def _refresh_trusted_proxies(self) -> None:
        """Periodic job body: re-resolve trusted_proxies hostname entries.

        Scheduled via ``self.scheduler.run_every()`` in ``on_initialize()``. Delegates entirely
        to :func:`hassette.web.auth.refresh_trusted_proxies`, which never raises — a hostname
        that fails to re-resolve keeps its last-known-good addresses.

        ``serve()`` builds the FastAPI app once and hands ``self._trusted_proxies`` to
        :func:`hassette.web.app.create_fastapi_app`, which copies it onto ``app.state`` as a
        single reference — rebinding ``self._trusted_proxies`` alone would leave that reference
        stale for the life of the running server. Once ``serve()`` has built ``self._app``, this
        also writes the refreshed set through to ``self._app.state.trusted_proxies`` so a request
        against the already-serving app observes the refresh immediately, not just a future
        restart.
        """
        refreshed = await refresh_trusted_proxies(self._trusted_proxies)
        self._trusted_proxies = refreshed
        if self._app is not None:
            self._app.state.trusted_proxies = refreshed

    async def serve(self) -> None:
        if not self.hassette.config.web_api.run:
            await self.shutdown_event.wait()  # stay alive so handle_stop() doesn't undo mark_ready
            return

        app = create_fastapi_app(
            self.hassette,
            auth_token=self._resolved_auth_token,
            trusted_proxies=self._trusted_proxies,
        )
        self._app = app

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level=self.config_log_level.lower(),
            lifespan="off",
            ws="websockets-sansio",
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_TIMEOUT,
            # Uvicorn's own ProxyHeadersMiddleware would otherwise silently trust X-Forwarded-For
            # from whatever FORWARDED_ALLOW_IPS resolves to (default "127.0.0.1") and rewrite
            # scope["client"] before trusted_proxies' peer check ever sees the real peer.
            proxy_headers=False,
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
        self._app = None
