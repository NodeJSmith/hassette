"""Which REST failures ``ApiResource.rest_request`` retries and raises, counted at a stub HTTP server.

A GET retries every transport failure and transient status. Any other method retries only a request that
never reached Home Assistant (``CommandNotSentError``), so a write is sent once after it may have applied.
"""

import asyncio
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from unittest.mock import Mock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from tenacity import wait_none

from hassette.core import api_resource as api_resource_module
from hassette.core.api_resource import ApiResource
from hassette.core.retry_policy import MAX_RETRY_ATTEMPTS
from hassette.exceptions import (
    CommandNotSentError,
    EntityNotFoundError,
    HttpRequestError,
    ResponseLostError,
    ResponseTimeoutError,
)
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


async def test_get_timeout_uses_full_retry_budget(stub_and_resource: tuple[StubHomeAssistant, ApiResource]) -> None:
    stub, resource = stub_and_resource
    stub.respond = never_answer

    with pytest.raises(ResponseTimeoutError, match="no response within the caller's timeout") as exc_info:
        await resource.rest_request("GET", "states/light.kitchen", timeout=SHORT_READ_TIMEOUT)

    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert exc_info.value.original_data is None
    assert stub.request_count == MAX_RETRY_ATTEMPTS


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_write_timeout_is_sent_once(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource], method: str
) -> None:
    stub, resource = stub_and_resource
    stub.respond = never_answer

    with pytest.raises(ResponseTimeoutError):
        await resource.rest_request(method, "states/light.kitchen", timeout=SHORT_READ_TIMEOUT)

    assert stub.request_count == 1


async def test_write_dropped_connection_is_sent_once(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource],
) -> None:
    stub, resource = stub_and_resource
    stub.respond = drop_connection

    with pytest.raises(ResponseLostError) as exc_info:
        await resource.rest_request("POST", "states/light.kitchen", data={"state": "on"})

    assert isinstance(exc_info.value.__cause__, aiohttp.ClientConnectionError)
    assert exc_info.value.close_code is None
    assert stub.request_count == 1


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_write_transient_status_is_sent_once(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource], status: int
) -> None:
    stub, resource = stub_and_resource
    stub.respond = respond_with(status)

    with pytest.raises(HttpRequestError):
        await resource.rest_request("POST", "states/light.kitchen", data={"state": "on"})

    assert stub.request_count == 1


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_refused_connect_is_not_sent_and_uses_full_retry_budget(
    method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused connect never reached Home Assistant, so every method retries it."""
    monkeypatch.setattr(api_resource_module, "wait_exponential_jitter", wait_none)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]  # closed again before the request, so connects are refused

    resource = ApiResource(make_mock_hassette(), rest_url=f"http://127.0.0.1:{port}/api/", headers_factory=dict)
    await resource.on_initialize()
    try:
        assert resource._session is not None
        attempts = Mock(wraps=resource._session.request)
        resource._session.request = attempts  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(CommandNotSentError) as exc_info:
            await resource.rest_request(method, "states/light.kitchen")

        assert isinstance(exc_info.value.__cause__, aiohttp.ClientConnectorError)
        assert attempts.call_count == MAX_RETRY_ATTEMPTS
    finally:
        await resource.on_shutdown()


async def test_closed_session_is_not_sent(stub_and_resource: tuple[StubHomeAssistant, ApiResource]) -> None:
    stub, resource = stub_and_resource
    stub.respond = respond_with(200)
    assert resource._session is not None
    await resource._session.close()

    with pytest.raises(CommandNotSentError, match="session is not connected"):
        await resource.rest_request("POST", "states/light.kitchen", data={"state": "on"})

    assert stub.request_count == 0


async def test_default_timeout_bounds_the_connect(stub_and_resource: tuple[StubHomeAssistant, ApiResource]) -> None:
    """Without a connect bound, a host that drops packets would end in a total timeout and read as outcome-unknown."""
    stub, resource = stub_and_resource
    stub.respond = respond_with(200)
    assert resource._session is not None
    attempts = Mock(wraps=resource._session.request)
    resource._session.request = attempts  # pyright: ignore[reportAttributeAccessIssue]

    await resource.rest_request("GET", "states/light.kitchen")

    timeout = attempts.call_args.kwargs["timeout"]
    assert timeout.sock_connect == api_resource_module.REST_CONNECT_TIMEOUT_SECONDS
    assert timeout.total == resource.hassette.config.rest_request_timeout_seconds


async def test_hung_connect_is_not_sent(
    stub_and_resource: tuple[StubHomeAssistant, ApiResource], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connect that never completes must surface as not-sent through aiohttp's own ``sock_connect`` timer.

    The not-sent class depends on aiohttp wrapping the connect timeout in ``ConnectionTimeoutError``; an aiohttp
    release that stops doing so would turn every blackholed-host failure into an outcome-unknown timeout.
    """
    stub, resource = stub_and_resource
    stub.respond = respond_with(200)
    monkeypatch.setattr(api_resource_module, "REST_CONNECT_TIMEOUT_SECONDS", 0.05)
    connect_attempts = 0

    async def hang_connect(*_args: object, **_kwargs: object) -> socket.socket:
        nonlocal connect_attempts
        connect_attempts += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr("aiohttp.connector.aiohappyeyeballs.start_connection", hang_connect)

    with pytest.raises(CommandNotSentError) as exc_info:
        await resource.rest_request("POST", "states/light.kitchen", data={"state": "on"})

    assert isinstance(exc_info.value.__cause__, aiohttp.ConnectionTimeoutError)
    assert connect_attempts == MAX_RETRY_ATTEMPTS
    assert stub.request_count == 0
