"""Request handlers see the Hassette context under a real uvicorn server (#2478).

uvicorn starts every request task in an empty ``contextvars.Context``, so the
``HASSETTE_INSTANCE``/``HASSETTE_CONFIG`` contextvars set at startup never reach a handler on
their own. In-process transports (``ASGITransport``) run the app in the test's own context, where
the harness has already set them, so only a real server reproduces the gap.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from hassette import context
from hassette.exceptions import HassetteNotInitializedError
from hassette.web.request_context import HassetteContextMiddleware
from tests.support.uvicorn import start_uvicorn_server, stop_uvicorn_server

ASYNC_PROBE_PATH = "/api/test-probe/context-async"
SYNC_PROBE_PATH = "/api/test-probe/context-sync"


def read_context(hassette: MagicMock) -> dict[str, bool]:
    """Report whether the ambient context resolves to the app's Hassette instance and config.

    A missing context is reported as data rather than raised, so the test fails on a readable
    assertion instead of an opaque 500.
    """
    try:
        return {
            "instance": context.get_hassette() is hassette,
            "config": context.get_hassette_config() is hassette.config,
        }
    except HassetteNotInitializedError:
        return {"instance": False, "config": False}


def add_probe_routes(app: FastAPI, hassette: MagicMock) -> None:
    """Add an async and a sync route that report what the ambient context resolves to.

    Inserted at the front of the router rather than via ``app.add_api_route``, which appends: when
    the SPA build exists, ``create_fastapi_app`` registers a ``/{path:path}`` catch-all that would
    match the probe paths first.
    """

    async def async_probe() -> dict[str, bool]:
        return read_context(hassette)

    def sync_probe() -> dict[str, bool]:
        return read_context(hassette)

    app.router.routes.insert(0, APIRoute(ASYNC_PROBE_PATH, async_probe, methods=["GET"]))
    app.router.routes.insert(0, APIRoute(SYNC_PROBE_PATH, sync_probe, methods=["GET"]))


@pytest.fixture
def live_server_url(app: FastAPI, mock_hassette: MagicMock) -> Iterator[str]:
    add_probe_routes(app, mock_hassette)
    server, thread, port = start_uvicorn_server(app)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_uvicorn_server(server, thread)


def test_context_middleware_is_outermost(app: FastAPI) -> None:
    """Guards against a later ``add_middleware`` call wrapping it; Starlette puts the last-added first."""
    assert app.user_middleware[0].cls is HassetteContextMiddleware


@pytest.mark.parametrize("path", [ASYNC_PROBE_PATH, SYNC_PROBE_PATH], ids=["async-route", "sync-route"])
async def test_request_handler_sees_hassette_context(live_server_url: str, path: str) -> None:
    async with httpx2.AsyncClient(base_url=live_server_url, timeout=10) as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == {"instance": True, "config": True}
