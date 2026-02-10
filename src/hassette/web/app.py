"""FastAPI application factory for the Hassette Web API."""

import typing

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

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

if typing.TYPE_CHECKING:
    from hassette import Hassette


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
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    return app
