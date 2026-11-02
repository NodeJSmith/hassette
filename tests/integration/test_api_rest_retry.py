"""Which REST failures ``ApiResource.rest_request`` retries, counted at a stub HTTP server."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from tenacity import wait_none

from hassette.core import api_resource as api_resource_module
from hassette.core.api_resource import ApiResource
from hassette.core.retry_policy import MAX_RETRY_ATTEMPTS
from hassette.exceptions import EntityNotFoundError, HttpRequestError
from tests.support.mock_hassette import make_mock_hassette

Responder = Callable[["StubHomeAssistant", web.Request], Awaitable[web.StreamResponse]]

# Only the read timeout is short: an attempt must reach the stub and get counted before it times out.
SHORT_READ_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_read=0.25)


@dataclass
class StubHomeAssistant:
    """HTTP stub that counts every request it receives and answers through ``respond``."""

    respond: Responder | None = None
    request_count: int = 0
    release_hung_requests: asyncio.Event = field(default_factory=asyncio.Event)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.request_count += 1
        assert self.respond is not None
        return await self.respond(self, request)


def respond_with(*statuses: int) -> Responder:
    """Answer each request with the next status, repeating the last one once they run out."""

    async def respond(stub: StubHomeAssistant, _request: web.Request) -> web.StreamResponse:
        return web.Response(status=statuses[min(stub.request_count, len(statuses)) - 1])

    return respond


async def drop_connection(_stub: StubHomeAssistant, request: web.Request) -> web.StreamResponse:
    assert request.transport is not None
    request.transport.close()
    return web.Response()


async def never_answer(stub: StubHomeAssistant, _request: web.Request) -> web.StreamResponse:
    await stub.release_hung_requests.wait()
    return web.Response()


@pytest.fixture
async def stub_and_resource(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[StubHomeAssistant, ApiResource]]:
    # The attempt count is under test here, not the backoff schedule between attempts.
    monkeypatch.setattr(api_resource_module, "wait_exponential_jitter", wait_none)

    stub = StubHomeAssistant()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stub.handle)

    async with TestServer(app) as server:
        resource = ApiResource(make_mock_hassette(), rest_url=str(server.make_url("/api/")), headers_factory=dict)
        await resource.on_initialize()
        try:
            yield stub, resource
        finally:
            stub.release_hung_requests.set()
            await resource.on_shutdown()


@pytest.mark.parametrize("status", [400, 401, 403, 405, 409, 422])
async def test_deterministic_client_error_is_attempted_once(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource], status: int
) -> None:
    stub, resource = stub_and_resource
    stub.respond = respond_with(status)

    with pytest.raises(HttpRequestError) as exc_info:
        await resource.rest_request("POST", "states/light.kitchen", data={"state": "on"})

    assert exc_info.value.status == status
    assert stub.request_count == 1


async def test_not_found_is_attempted_once(stub_and_resource: tuple[StubHomeAssistant, ApiResource]) -> None:
    stub, resource = stub_and_resource
    stub.respond = respond_with(404)

    with pytest.raises(EntityNotFoundError):
        await resource.rest_request("GET", "states/light.missing", suppress_error_message=True)

    assert stub.request_count == 1


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_transient_status_uses_full_retry_budget(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource], status: int
) -> None:
    stub, resource = stub_and_resource
    stub.respond = respond_with(status)

    with pytest.raises(HttpRequestError) as exc_info:
        await resource.rest_request("GET", "states/light.kitchen")

    assert exc_info.value.status == status
    assert stub.request_count == MAX_RETRY_ATTEMPTS


async def test_transient_status_recovers_when_a_retry_succeeds(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource],
) -> None:
    stub, resource = stub_and_resource
    stub.respond = respond_with(503, 200)

    response = await resource.rest_request("GET", "states/light.kitchen")

    assert response.status == 200
    assert stub.request_count == 2


async def test_timeout_uses_full_retry_budget(stub_and_resource: tuple[StubHomeAssistant, ApiResource]) -> None:
    stub, resource = stub_and_resource
    stub.respond = never_answer

    with pytest.raises(TimeoutError):
        await resource.rest_request("GET", "states/light.kitchen", timeout=SHORT_READ_TIMEOUT)

    assert stub.request_count == MAX_RETRY_ATTEMPTS


async def test_connection_error_uses_full_retry_budget(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource],
) -> None:
    stub, resource = stub_and_resource
    stub.respond = drop_connection

    # POST, because aiohttp itself resends an idempotent method once on a reused connection, which would
    # double the count for each attempt.
    with pytest.raises(aiohttp.ClientConnectionError):
        await resource.rest_request("POST", "states/light.kitchen", data={"state": "on"})

    assert stub.request_count == MAX_RETRY_ATTEMPTS
