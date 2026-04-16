"""FastAPI application factory for the Hassette Web API."""

import typing
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse

from hassette.web.routes.apps import router as apps_router
from hassette.web.routes.bus import router as bus_router
from hassette.web.routes.config import router as config_router
from hassette.web.routes.events import router as events_router
from hassette.web.routes.health import router as health_router
from hassette.web.routes.logs import router as logs_router
from hassette.web.routes.services import router as services_router
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
    app.include_router(apps_router, prefix="/api")
    app.include_router(services_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(bus_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(ws_router, prefix="/api")
    app.include_router(telemetry_router, prefix="/api")

    # SPA serving (Preact)
    if hassette.config.run_web_ui and _SPA_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(_SPA_DIR / "assets")), name="spa-assets")
        if (_SPA_DIR / "fonts").exists():
            app.mount("/fonts", StaticFiles(directory=str(_SPA_DIR / "fonts")), name="spa-fonts")

        @app.get("/{path:path}")
        async def spa_catch_all(path: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
            """Serve index.html for SPA client-side routing.

            Static files in the SPA build output (e.g., hassette-logo.png) are
            served directly.  Other static-looking paths and API paths get a 404.
            """
            # Serve root-level SPA static files (logo, favicon, etc.)
            candidate = _SPA_DIR / path
            if candidate.is_file() and candidate.resolve().is_relative_to(_SPA_DIR.resolve()):
                return FileResponse(str(candidate))

            last_segment = path.rsplit("/", 1)[-1]
            is_static = any(last_segment.endswith(ext) for ext in _STATIC_EXTENSIONS)
            if path.startswith("api/") or is_static:
                raise HTTPException(status_code=404, detail=f"/{path} not found")
            return FileResponse(str(_SPA_DIR / "index.html"))

    return app
