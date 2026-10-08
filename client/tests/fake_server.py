"""A recording fake hassette server for client tests, served by ``aiohttp.test_utils.TestServer``."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

TEST_TOKEN = "test-token"  # noqa: S105 - a fixture value, not a credential

HEALTH_BODY: dict[str, Any] = {
    "status": "ok",
    "websocket_connected": True,
    "bootstrap_released": True,
    "uptime_seconds": 12.5,
    "entity_count": 3,
    "app_count": 1,
    "version": "0.0.0-test",
}
"""A valid ``SystemStatusResponse`` body."""


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes


@dataclass
class CannedResponse:
    status: int = 200
    body: bytes = b"{}"
    content_type: str | None = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    hang: bool = False


@dataclass
class FakeServer:
    """Answers every request with ``response`` and records it in ``requests``."""

    base_url: str = ""
    response: CannedResponse = field(default_factory=CannedResponse)
    requests: list[RecordedRequest] = field(default_factory=list)
    released: asyncio.Event = field(default_factory=asyncio.Event)
    """Set at teardown, so a hanging response finishes instead of stalling the server's shutdown."""

    def respond(
        self,
        status: int = 200,
        body: Any = None,
        *,
        raw: bytes | None = None,
        content_type: str | None = "application/json",
        headers: dict[str, str] | None = None,
        hang: bool = False,
    ) -> None:
        """Answer every later request with this response: ``body`` is JSON-encoded, ``raw`` is sent as-is.

        ``content_type=None`` sends no ``Content-Type`` header at all. ``hang`` holds every response until
        teardown, for timeout tests.
        """
        payload = raw if raw is not None else json.dumps({} if body is None else body).encode()
        self.response = CannedResponse(status, payload, content_type, headers or {}, hang)

    def respond_problem(self, status: int, code: str, detail: str = "it failed") -> None:
        problem = {"type": "about:blank", "title": "Error", "status": status, "detail": detail, "code": code}
        self.respond(status, problem, content_type="application/problem+json")

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            RecordedRequest(
                request.method,
                request.raw_path.split("?", 1)[0],
                dict(request.query),
                dict(request.headers),
                await request.read(),
            )
        )
        canned = self.response
        if canned.hang:
            await self.released.wait()
        content_type = {} if canned.content_type is None else {"Content-Type": canned.content_type}
        return web.Response(status=canned.status, body=canned.body, headers={**content_type, **canned.headers})

    async def strip_default_content_type(self, request: web.Request, response: web.StreamResponse) -> None:
        """``on_response_prepare`` hook: aiohttp adds a default ``Content-Type``, which a proxy may not."""
        if self.response.content_type is None:
            response.headers.pop("Content-Type", None)
