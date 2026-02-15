"""FastAPI application factory for the Hassette Web API."""

import typing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, RedirectResponse

from hassette.web.routes.apps import router as apps_router
from hassette.web.routes.bus import router as bus_router
from hassette.web.routes.config import router as config_router
from hassette.web.routes.entities import router as entities_router
from hassette.web.routes.events import router as events_router
from hassette.web.routes.health import router as health_router
from hassette.web.routes.logs import router as logs_router
from hassette.web.routes.scheduler import router as scheduler_router
from hassette.web.routes.services import router as services_router
from hassette.web.routes.ws import router as ws_router
from hassette.web.ui import templates
from hassette.web.ui.context import base_context
from hassette.web.ui.partials import router as partials_router
from hassette.web.ui.router import router as ui_router

if typing.TYPE_CHECKING:
    from hassette import Hassette

_STATIC_DIR = Path(__file__).parent / "static"


def create_fastapi_app(hassette: "Hassette") -> FastAPI:
    app = FastAPI(
        title="Hassette Web API",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.hassette = hassette

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(hassette.config.web_api_cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    )

    # API routes
    app.include_router(health_router, prefix="/api")
    app.include_router(entities_router, prefix="/api")
    app.include_router(apps_router, prefix="/api")
    app.include_router(services_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")
    app.include_router(bus_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(ws_router, prefix="/api")

    # Web UI
    if hassette.config.run_web_ui:
        app.mount("/ui/static", StaticFiles(directory=str(_STATIC_DIR)), name="ui-static")
        app.include_router(ui_router, prefix="/ui")
        app.include_router(partials_router, prefix="/ui")
        app.add_api_route("/", _root_redirect, methods=["GET"])
        app.add_exception_handler(HTTPException, _ui_http_exception_handler)  # type: ignore[arg-type]

    return app


async def _ui_http_exception_handler(request: Request, exc: HTTPException) -> HTMLResponse:
    """Render HTML error pages for UI routes so hx-boost can select #page-content.

    API routes (``/api/``) fall through to FastAPI's default JSON handler.
    """
    if request.url.path.startswith("/api/"):
        from fastapi.exception_handlers import http_exception_handler

        return await http_exception_handler(request, exc)  # type: ignore[return-value]

    status_code = exc.status_code
    detail = exc.detail or "An unexpected error occurred"
    ctx = {
        **base_context("error"),
        "status_code": status_code,
        "detail": detail,
    }
    return templates.TemplateResponse(request, "pages/error.html", ctx, status_code=status_code)


async def _root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/", status_code=307)
