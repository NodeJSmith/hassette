"""Restores the Hassette context for every Web API request.

uvicorn starts each request task in a fresh, empty ``contextvars.Context``, so the
``HASSETTE_INSTANCE`` and ``HASSETTE_CONFIG`` contextvars set at startup never reach a route
handler on their own (``tests/integration/web_api/test_request_context.py`` reproduces this under a
real server). Without this middleware, anything a handler reaches that reads them fails or silently
falls back: ``HassetteConfig.get_config()``, ``Hassette.get_instance()``, ``get_dev_mode()``, and
user app code calling any of those at import time during a web-triggered reload.

This must be the outermost middleware so every other middleware, and everything they await, runs
inside the restored context.
"""

import typing

from starlette.types import ASGIApp, Receive, Scope, Send

from hassette import context

if typing.TYPE_CHECKING:
    from hassette import Hassette


class HassetteContextMiddleware:
    """Sets ``HASSETTE_INSTANCE`` and ``HASSETTE_CONFIG`` for the duration of each ASGI call."""

    def __init__(self, app: ASGIApp, hassette: "Hassette") -> None:
        self.app = app
        self.hassette = hassette

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        with (
            context.use(context.HASSETTE_INSTANCE, self.hassette),
            context.use_hassette_config(self.hassette.config),
        ):
            await self.app(scope, receive, send)
