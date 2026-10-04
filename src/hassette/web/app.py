"""FastAPI application factory for the Hassette Web API."""

import re
import typing
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from hassette_wire import ProblemCode
from starlette.convertors import Convertor, register_url_convertor
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse

from hassette.web.auth.trusted_proxies import EMPTY_TRUSTED_PROXY_SET, TrustedProxySet
from hassette.web.body_limit import RequestBodySizeLimitMiddleware
from hassette.web.errors import WebApiError, install_problem_handlers, install_problem_openapi
from hassette.web.middleware import DefaultDenyMiddleware
from hassette.web.request_context import HassetteContextMiddleware
from hassette.web.routes.apps import router as apps_router
from hassette.web.routes.auth import router as auth_router
from hassette.web.routes.bus import router as bus_router
from hassette.web.routes.config import router as config_router
from hassette.web.routes.executions import router as executions_router
from hassette.web.routes.health import router as health_router
from hassette.web.routes.logs import router as logs_router
from hassette.web.routes.scheduler import router as scheduler_router
from hassette.web.routes.telemetry import router as telemetry_router
from hassette.web.routes.ws import router as ws_router

if typing.TYPE_CHECKING:
    from hassette import Hassette

_STATIC_DIR = Path(__file__).parent / "static"
_SPA_DIR = _STATIC_DIR / "spa"

_STATIC_EXTENSIONS = frozenset(
    {
        ".js",
        ".css",
        ".ico",
        ".png",
        ".svg",
        ".map",
        ".json",
        ".woff",
        ".woff2",
        ".txt",
        ".webmanifest",
    }
)

_CORS_ALLOW_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
_CORS_ALLOW_HEADERS = ("Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With")

API_PREFIX = "/api"
"""URL prefix every API router is mounted under; ``SpaPathConvertor.regex`` is derived from it."""

SPA_PATH_CONVERTOR = "hassette_spa_path"
"""Path convertor for the SPA catch-all: any path except ``/api`` and ``/api/...``."""


class SpaPathConvertor(Convertor[str]):
    """Matches every path except the API prefix, so unknown ``/api`` paths get the router's own
    404 (and real 405s survive) whether or not the SPA is served.
    """

    regex = rf"(?!{re.escape(API_PREFIX.removeprefix('/'))}(?:/|$)).*"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


# Starlette keeps convertors in one module-level registry shared by every app in the process, with
# no per-app scope. So this registers once at import (not per create_fastapi_app() call) under a
# hassette-specific key; re-registration would be idempotent, and only routes that name the key
# are affected.
register_url_convertor(SPA_PATH_CONVERTOR, SpaPathConvertor())


def create_fastapi_app(
    hassette: "Hassette",
    auth_token: str | None = None,
    trusted_proxies: TrustedProxySet | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Hassette Web API",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    install_problem_handlers(app)
    install_problem_openapi(app)
    app.state.hassette = hassette
    app.state.auth_token = auth_token
    app.state.trusted_proxies = trusted_proxies or EMPTY_TRUSTED_PROXY_SET

    # Starlette wraps middleware so the LAST one added is OUTERMOST: it sees the request first and
    # the response last. Each comment below gives only that middleware's placement reason.

    # Innermost of the auth/CORS stack, so CORSMiddleware can answer a genuine preflight before this
    # rejects it with an opaque 401 (test_cors_preflight_gets_cors_response_not_opaque_401).
    app.add_middleware(DefaultDenyMiddleware)

    # Outside DefaultDeny, so an oversized body is refused before auth runs (POST /api/auth/session is
    # credential-free); inside CORS, so the 413 carries CORS headers instead of an opaque network error.
    app.add_middleware(RequestBodySizeLimitMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(hassette.config.web_api.cors_origins),
        allow_credentials=True,
        allow_methods=_CORS_ALLOW_METHODS,
        allow_headers=_CORS_ALLOW_HEADERS,
    )

    # Added last so it is outermost; see hassette/web/request_context.py.
    app.add_middleware(HassetteContextMiddleware, hassette=hassette)

    # API routes
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(apps_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(logs_router, prefix=API_PREFIX)
    app.include_router(executions_router, prefix=API_PREFIX)
    app.include_router(bus_router, prefix=API_PREFIX)
    app.include_router(config_router, prefix=API_PREFIX)
    app.include_router(ws_router, prefix=API_PREFIX)
    app.include_router(telemetry_router, prefix=API_PREFIX)
    app.include_router(scheduler_router, prefix=API_PREFIX)

    # SPA serving (Preact)
    if hassette.config.web_api.run_ui and _SPA_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(_SPA_DIR / "assets")), name="spa-assets")
        if (_SPA_DIR / "fonts").exists():
            app.mount("/fonts", StaticFiles(directory=str(_SPA_DIR / "fonts")), name="spa-fonts")

        # Out of the schema: an HTML route, and the OpenAPI document must not depend on run_ui.
        @app.get(f"/{{path:{SPA_PATH_CONVERTOR}}}", include_in_schema=False)
        async def spa_catch_all(path: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
            """Serve index.html for SPA client-side routing.

            Static files in the SPA build output (e.g., hassette-logo.png) are
            served directly.  Other static-looking paths get a 404. API paths never
            reach this route (see ``SpaPathConvertor``).
            """
            # Serve root-level SPA static files (logo, favicon, etc.)
            candidate = _SPA_DIR / path
            if candidate.is_file() and candidate.resolve().is_relative_to(_SPA_DIR.resolve()):
                return FileResponse(str(candidate))

            last_segment = path.rsplit("/", 1)[-1]
            is_static = any(last_segment.endswith(ext) for ext in _STATIC_EXTENSIONS)
            if is_static:
                raise WebApiError(ProblemCode.NOT_FOUND, f"/{path} not found")
            return FileResponse(str(_SPA_DIR / "index.html"))

    return app
